"""A deliberately small API; static frontend is served separately by nginx."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from server.auth import verify_init_data
from server.settings import admin_id, bot_token


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
        if urlsplit(self.path).path != "/api/session":
            return self.send_json(404, {"error": "Маршрут не найден"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 12000:
                return self.send_json(400, {"error": "Неверный размер запроса"})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                return self.send_json(400, {"error": "Неверный запрос"})
        except (ValueError, UnicodeError):
            return self.send_json(400, {"error": "Неверный JSON"})
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
