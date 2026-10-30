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


def db():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS partners (
        telegram_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL
    )""")
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
            return self.respond(200, {"offers": [], "message": "CRM offers endpoint not connected"})
        return self.respond(404, {"error": "Не найдено"})

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1 or size > 16384:
            return self.respond(400, {"error": "Неверный размер запроса"})
        try:
            body = json.loads(self.rfile.read(size))
        except (ValueError, TypeError):
            return self.respond(400, {"error": "Неверный JSON"})
        user = verify_init_data(body.get("initData", ""))
        if not user:
            return self.respond(401, {"error": "Данные Telegram не прошли проверку"})
        uid = user["id"]
        if self.path == "/api/auth/telegram":
            with db() as conn:
                conn.execute("""INSERT INTO partners(telegram_id, username, name, created_at)
                    VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                    username=excluded.username, name=excluded.name""",
                    (uid, str(user.get("username") or ""), str(user.get("first_name") or "Партнёр"), int(time.time())))
            return self.respond(200, {"profile": partner_for(uid)})
        if self.path.startswith("/api/links/"):
            return self.respond(503, {"error": "Выдача ссылок станет доступна после подключения CRM и трекинга"})
        return self.respond(404, {"error": "Не найдено"})


if __name__ == "__main__":
    db().close()
    port = int(os.environ.get("SERVER_PORT", "8788"))
    print(f"Partner API listening on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
