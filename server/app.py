"""Minimal development API. Production: HTTPS reverse proxy + CRM integration."""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
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
    if not TOKEN or not isinstance(data, str) or not data or len(data) > 8192:
        return None
    try:
        pairs = parse_qsl(data, keep_blank_values=True, strict_parsing=True, max_num_fields=64)
        # Duplicate keys make the signed payload ambiguous between parsers.
        if len(pairs) != len({key for key, _ in pairs}):
            return None
        params = dict(pairs)
        check = params.pop("hash", "")
        if len(check) != 64 or "auth_date" not in params or "user" not in params:
            return None
        auth_date = int(params["auth_date"])
        if auth_date > time.time() + 60 or time.time() - auth_date > 3600:
            return None
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        body = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
        expected = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, check):
            return None
        user = json.loads(params["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or not (0 < user["id"] <= 9223372036854775807):
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


def notify_partner_status(telegram_id, status):
    """Best-effort Telegram notification; database changes never depend on delivery."""
    if not TOKEN:
        return
    messages = {
        "active": "Ваша заявка The Affiliates Partners одобрена. Откройте кабинет через бота.",
        "rejected": "Ваша заявка The Affiliates Partners отклонена. Для повторной подачи отправьте /retry боту.",
        "pending": "Статус вашей заявки The Affiliates Partners: на рассмотрении.",
    }
    payload = json.dumps({"chat_id": telegram_id, "text": messages[status]}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        print("Partner status notification failed", flush=True)


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
        except (ValueError, TypeError, UnicodeDecodeError):
            return self.respond(400, {"error": "Неверный JSON"})
        if not isinstance(body, dict):
            return self.respond(400, {"error": "Неверный запрос"})
        user = verify_init_data(body.get("initData", ""))
        if not user:
            return self.respond(401, {"error": "Данные Telegram не прошли проверку"})
        uid = user["id"]
        route = urlparse(self.path).path
        if route == "/api/offers":
            profile = partner_for(uid)
            if uid != ADMIN_ID and (not profile or profile["status"] != "active" or not profile["phone"]):
                return self.respond(403, {"error": "Офферы доступны только одобренным партнёрам"})
            return self.respond(200, {"offers": approved_offers()})
        if route == "/api/auth/telegram":
            if uid != ADMIN_ID:
                with db() as conn:
                    conn.execute("""INSERT INTO partners(telegram_id, username, name, created_at)
                        VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                        username=excluded.username, name=excluded.name""",
                        (uid, str(user.get("username") or ""), str(user.get("first_name") or "Партнёр"), int(time.time())))
            profile = partner_for(uid)
            if uid == ADMIN_ID and profile is None:
                # Owner identity comes from verified Telegram initData, not a synthetic DB user.
                profile = {"telegram_id": uid, "username": str(user.get("username") or ""),
                           "name": str(user.get("first_name") or "Администратор"),
                           "phone": "", "status": "active"}
            return self.respond(200, {"profile": profile, "isAdmin": uid == ADMIN_ID})
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
                    if status == "active":
                        row = conn.execute("SELECT phone FROM partners WHERE telegram_id=?", (partner_id,)).fetchone()
                        if row and not row[0]:
                            return self.respond(400, {"error": "Сначала требуется подтверждение телефона"})
                    changed = conn.execute("UPDATE partners SET status=? WHERE telegram_id=?",
                                           (status, partner_id)).rowcount
                if changed:
                    notify_partner_status(partner_id, status)
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
