"""Minimal development API. Production: HTTPS reverse proxy + CRM integration."""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse
from config import load_local_env

load_local_env()

ROOT = Path(__file__).resolve().parent
DB = ROOT / "partners.sqlite3"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED = os.environ.get("ALLOWED_ORIGIN", "")
ADMIN_ID = 758398804  # Verify signed Telegram user ID, never the mutable username.
PARTNER_STATES = {"pending", "active", "rejected"}
OFFER_STATES = {"draft", "approved", "rejected", "paused"}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def db():
    conn = sqlite3.connect(DB, factory=ClosingConnection, timeout=5)
    conn.execute("""CREATE TABLE IF NOT EXISTS partners (
        telegram_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS offers (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
        rate INTEGER NOT NULL, goal TEXT NOT NULL, hold INTEGER NOT NULL,
        description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
        updated_at INTEGER NOT NULL
    )""")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.commit()
    return conn


def verify_init_data(data: str):
    if not TOKEN or not data or len(data) > 8192:
        return None
    params = dict(parse_qsl(data, keep_blank_values=True))
    check = params.pop("hash", "")
    if not check or "auth_date" not in params or "user" not in params:
        return None
    try:
        if abs(time.time() - int(params["auth_date"])) > 3600:
            return None
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        body = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
        expected = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, check):
            return None
        user = json.loads(params["user"])
        if not isinstance(user.get("id"), int):
            return None
        return user
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def partner_for(telegram_id):
    with db() as conn:
        row = conn.execute("SELECT telegram_id,username,name,phone,status FROM partners WHERE telegram_id=?", (telegram_id,)).fetchone()
    return dict(zip(["telegram_id", "username", "name", "phone", "status"], row)) if row else None


def approved_offers():
    with db() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT id,name,type,rate,goal,hold,description,status FROM offers WHERE status='approved' ORDER BY updated_at DESC")]


def admin_snapshot():
    with db() as conn:
        conn.row_factory = sqlite3.Row
        partners = [dict(r) for r in conn.execute(
            "SELECT telegram_id,username,name,phone,status,created_at FROM partners ORDER BY created_at DESC")]
        offers = [dict(r) for r in conn.execute(
            "SELECT id,name,type,rate,goal,hold,description,status,updated_at FROM offers ORDER BY updated_at DESC")]
    return {"partners": partners, "offers": offers}


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, body):
        payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if ALLOWED:
            self.send_header("Access-Control-Allow-Origin", ALLOWED)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/api/health":
            return self.respond(200, {"ok": True})
        if route == "/api/offers":
            return self.respond(200, {"offers": approved_offers()})
        return self.respond(404, {"error": "Не найдено"})

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.respond(400, {"error": "Неверный размер запроса"})
        if size < 1 or size > 16384:
            return self.respond(400, {"error": "Неверный размер запроса"})
        try:
            body = json.loads(self.rfile.read(size))
        except (ValueError, TypeError):
            return self.respond(400, {"error": "Неверный JSON"})
        if not isinstance(body, dict):
            return self.respond(400, {"error": "Неверный запрос"})
        user = verify_init_data(body.get("initData", ""))
        if not user:
            return self.respond(401, {"error": "Данные Telegram не прошли проверку"})
        uid = user["id"]
        route = urlparse(self.path).path
        if route == "/api/auth/telegram":
            with db() as conn:
                conn.execute("""INSERT INTO partners(telegram_id, username, name, created_at)
                    VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                    username=excluded.username, name=excluded.name""",
                    (uid, str(user.get("username") or ""), str(user.get("first_name") or "Партнёр"), int(time.time())))
            return self.respond(200, {"profile": partner_for(uid), "isAdmin": uid == ADMIN_ID})
        if route.startswith("/api/admin/"):
            if uid != ADMIN_ID:
                return self.respond(403, {"error": "Недостаточно прав"})
            if route == "/api/admin/snapshot":
                return self.respond(200, admin_snapshot())
            if route == "/api/admin/partners/status":
                status = body.get("status")
                partner_id = body.get("telegram_id")
                if status not in {"active", "rejected", "pending"} or type(partner_id) is not int:
                    return self.respond(400, {"error": "Неверные параметры"})
                if partner_id == ADMIN_ID:
                    return self.respond(400, {"error": "Нельзя менять собственную роль"})
                with db() as conn:
                    changed = conn.execute("UPDATE partners SET status=? WHERE telegram_id=?",
                                           (status, partner_id)).rowcount
                return self.respond(200 if changed else 404, {"ok": bool(changed)})
            if route == "/api/admin/offers/save":
                offer = body.get("offer")
                if not isinstance(offer, dict):
                    return self.respond(400, {"error": "Неверный оффер"})
                fields = ("id", "name", "type", "goal", "description")
                if any(not isinstance(offer.get(k), str) or not offer[k].strip() or len(offer[k]) > 1000 for k in fields):
                    return self.respond(400, {"error": "Заполните поля оффера"})
                if len(offer["id"]) > 80 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in offer["id"]):
                    return self.respond(400, {"error": "Неверный ID"})
                if offer.get("status") not in OFFER_STATES or type(offer.get("rate")) is not int or type(offer.get("hold")) is not int:
                    return self.respond(400, {"error": "Неверные значения"})
                if not (0 <= offer["rate"] <= 100000000 and 0 <= offer["hold"] <= 365):
                    return self.respond(400, {"error": "Значение вне диапазона"})
                with db() as conn:
                    conn.execute("""INSERT INTO offers(id,name,type,rate,goal,hold,description,status,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,type=excluded.type,rate=excluded.rate,
                        goal=excluded.goal,hold=excluded.hold,description=excluded.description,
                        status=excluded.status,updated_at=excluded.updated_at""",
                        tuple(offer[k].strip() if isinstance(offer[k], str) else offer[k]
                              for k in ("id", "name", "type", "rate", "goal", "hold", "description", "status"))
                        + (int(time.time()),))
                return self.respond(200, {"ok": True})
            if route == "/api/admin/offers/status":
                status, offer_id = body.get("status"), body.get("id")
                if status not in OFFER_STATES or not isinstance(offer_id, str):
                    return self.respond(400, {"error": "Неверные параметры"})
                with db() as conn:
                    changed = conn.execute("UPDATE offers SET status=?,updated_at=? WHERE id=?",
                                           (status, int(time.time()), offer_id)).rowcount
                return self.respond(200 if changed else 404, {"ok": bool(changed)})
            return self.respond(404, {"error": "Не найдено"})
        if route.startswith("/api/links/"):
            return self.respond(503, {"error": "Выдача ссылок станет доступна после подключения CRM и трекинга"})
        return self.respond(404, {"error": "Не найдено"})


if __name__ == "__main__":
    db().close()
    port = int(os.environ.get("SERVER_PORT", "8788"))
    print(f"Partner API listening on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
