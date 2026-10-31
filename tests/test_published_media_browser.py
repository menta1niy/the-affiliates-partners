"""Browser rendering smoke; API fixtures are synthetic, never signed Telegram identity."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

WEB = Path(__file__).resolve().parents[1] / "web"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        filename = {"/partners/": "index.html", "/partners/style.css": "style.css", "/partners/app.js": "app.js"}.get(path)
        if filename is None:
            self.send_error(404)
            return
        data = (WEB / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/css" if filename.endswith(".css") else "application/javascript" if filename.endswith(".js") else "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(data)


def verify():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for width in (390, 1440):
                page = browser.new_page(viewport={"width": width, "height": 820})
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                offer = {
                    "id": "synthetic-offer", "name": "Synthetic published offer",
                    "instructions": "Published baseline",
                    "published_instruction": {
                        "text": "<img src=x onerror=alert(1)>\nSafe text",
                        "images": [
                            {"url": "https://assets.example.test/safe.png", "alt": "<script>alt</script>"},
                            {"url": "javascript:alert(1)"},
                            {"url": "https://evil.test@assets.example.test/x.png"},
                            {"url": "https://user:secret@assets.example.test/hidden.png"},
                        ],
                        "links": [
                            {"url": "https://docs.example.test/guide", "label": "<b>Guide</b>"},
                            {"url": "data:text/html,evil", "label": "Unsafe"},
                            {"url": "http://insecure.test/x", "label": "Insecure"},
                        ],
                    },
                }

                def api(route):
                    path = route.request.url.rsplit("/api/", 1)[-1]
                    response = {
                        "session": {"source": "telegram", "status": "active", "role": "lead", "user": {"id": 10, "first_name": "Synthetic"}},
                        "tasks": {"tasks": [offer, {"id": "legacy", "name": "No attachments", "instructions": "Legacy safe instruction"}], "history": []},
                        "status": {"applications": [], "lead_payouts": []},
                        "invitations/referral": {},
                    }.get(path, {})
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(response))

                page.route("**/partners/api/**", api)
                page.goto(f"http://127.0.0.1:{server.server_port}/partners/?tgWebAppData=synthetic-test-data")
                page.get_by_role("heading", name="Synthetic published offer").wait_for(timeout=15000)
                assert page.get_by_text("<img src=x onerror=alert(1)>", exact=False).count() > 0
                assert page.locator(".published-instruction-images img").count() == 1
                assert page.locator(".published-instruction-links a").count() == 1
                assert page.locator(".published-instruction-links a").first.get_attribute("href") == "https://docs.example.test/guide"
                assert page.locator(".published-instruction-links a").first.get_attribute("rel") == "noopener noreferrer"
                assert page.locator(".published-instruction-text img").count() == 0
                assert page.get_by_text("Published baseline").count() == 0
                assert page.get_by_role("heading", name="No attachments").is_visible()
                assert page.get_by_text("Legacy safe instruction").is_visible()
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        server.shutdown()
    print("PASS: published text, HTTPS image/link whitelist, XSS and 390/1440px layout")


if __name__ == "__main__":
    verify()
