"""Local browser UI smoke checks with synthetic API responses, never Telegram auth."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

WEB = Path(__file__).resolve().parents[1] / "web"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        mapping = {
            "/partners/": "index.html",
            "/partners/style.css": "style.css",
            "/partners/app.js": "app.js",
        }
        if path not in mapping:
            self.send_error(404)
            return
        filename = WEB / mapping[path]
        body = filename.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/css" if path.endswith(".css") else "application/javascript" if path.endswith(".js") else "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/partners/"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for width in (390, 1440):
                context = browser.new_context(viewport={"width": width, "height": 850})
                page = context.new_page()
                page.goto(url)
                page.get_by_text("Нужен вход через Telegram").wait_for(timeout=12000)
                assert page.get_by_role("heading", name="Войдите через Telegram").is_visible()
                assert page.locator("#account").is_hidden()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"missing-auth overflow at {width}px"

                def invalid(route):
                    route.fulfill(status=401, content_type="application/json", body=json.dumps({"error": "Недействительная подпись Telegram"}))

                page.route("**/partners/api/session", invalid)
                page.goto(url + "?tgWebAppData=invalid")
                page.get_by_text("Не удалось проверить вход").wait_for(timeout=12000)
                assert "Недействительная подпись" in page.locator("#error").inner_text()
                assert page.locator("#account").is_hidden()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"invalid-auth overflow at {width}px"

                page.unroute("**/partners/api/session", invalid)
                def synthetic_api(route):
                    endpoint = route.request.url.rsplit("/api/", 1)[-1]
                    payload = {
                        "session": {"source": "telegram", "status": "active", "role": "lead", "user": {"id": 42, "first_name": "Тест", "status": "active"}},
                        "tasks": {"tasks": [{"id": "offer-sample", "name": "Тестовое назначение", "instructions": "Выполните условия"}], "history": []},
                        "status": {"applications": [{"offer_id": "offer-sample", "stage": "applied"}], "lead_payouts": []},
                        "invitations/referral": {"error": "no invitation"},
                        "tasks/report": {"ok": True},
                    }.get(endpoint, {})
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))
                page.route("**/partners/api/**", synthetic_api)
                page.goto(url + "?tgWebAppData=synthetic-test-only")
                page.get_by_role("heading", name="Тестовое назначение").wait_for(timeout=12000)
                assert page.get_by_text("Заявка отправлена").is_visible()
                assert page.get_by_role("button", name="Сообщить о действии").is_visible()
                page.get_by_role("button", name="Сообщить о действии").click()
                page.get_by_text("Отчёт принят. Подтверждение результата ожидается от CRM.").wait_for(timeout=12000)
                assert page.get_by_role("heading", name="Тестовое назначение").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"active-state overflow at {width}px"
                context.close()
            browser.close()
    finally:
        server.shutdown()
    print("PASS: Chromium 390px + 1440px, missing/invalid Telegram initData, synthetic active tasks/status/report, no horizontal overflow")


if __name__ == "__main__":
    main()
