"""A deliberately small API; static frontend is served separately by nginx."""
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from server.auth import verify_init_data
from server.bot import response_for
from server.settings import admin_id, bot_token, webhook_secret


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlsplit(self.path).path == "/api/health":
            return self.send_json(200, {"ok": True, "service": "the-affiliates-partners-v2"})
        return self.send_json(404, {"error": "Маршрут не найден"})

    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in {"/api/session", "/api/telegram/webhook"}:
            return self.send_json(404, {"error": "Маршрут не найден"})
        if route == "/api/telegram/webhook":
            secret = webhook_secret()
            header = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not secret or not hmac.compare_digest(secret, header):
                return self.send_json(403, {"error": "Недостаточно прав"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 24000:
                return self.send_json(400, {"error": "Неверный размер запроса"})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                return self.send_json(400, {"error": "Неверный запрос"})
        except (ValueError, UnicodeError):
            return self.send_json(400, {"error": "Неверный JSON"})
        if route == "/api/telegram/webhook":
            if type(body.get("update_id")) is not int:
                return self.send_json(400, {"error": "Неверное обновление Telegram"})
            return self.send_json(200, response_for(body) or {"ok": True})
        token = bot_token()
        if not token:
            return self.send_json(503, {"error": "Telegram не настроен на сервере"})
        user = verify_init_data(body.get("initData"), token)
        if user is None:
            return self.send_json(401, {"error": "Telegram не подтвердил данные входа"})
        return self.send_json(200, {
            "user": user,
            "role": "owner" if user["id"] == admin_id() else "partner",
            "source": "telegram",
        })


def main():
    port = int(os.environ.get("SERVER_PORT", "8788"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Partners API listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
