"""Browser-level visual token assertions; no backend or production mutation."""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler


class VisualFoundationSmoke(unittest.TestCase):
    def test_graphite_foundation_and_amber_primary_in_both_documents(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    for page_path in ("/partners/", "/partners/admin/"):
                        for width in (320, 390, 1440):
                            with self.subTest(page=page_path, width=width):
                                page = browser.new_page(viewport={"width": width, "height": 844})
                                errors = []
                                page.on("pageerror", lambda error: errors.append(str(error)))
                                page.goto(
                                    f"http://127.0.0.1:{server.server_port}{page_path}",
                                    wait_until="domcontentloaded",
                                )
                                result = page.evaluate("""() => {
                                    const root = getComputedStyle(document.documentElement);
                                    const color = key => root.getPropertyValue(key).trim();
                                    const primary = document.querySelector('.btn.primary');
                                    const computed = primary && getComputedStyle(primary);
                                    return {
                                        bg: color('--color-bg'),
                                        accent: color('--color-accent'),
                                        glass: color('--glass-functional'),
                                        font: root.fontFamily,
                                        primaryBg: computed?.backgroundColor,
                                        primaryInk: computed?.color,
                                        themeColor: document.querySelector('meta[name="theme-color"]')?.content,
                                    };
                                }""")
                                self.assertEqual(result["bg"], "#080909")
                                self.assertEqual(result["accent"], "#FFFFFF")
                                self.assertEqual(result["glass"], "rgba(255,255,255,.045)")
                                self.assertIn("Plus Jakarta Sans", result["font"])
                                self.assertEqual(result["primaryBg"], "rgb(228, 163, 74)")
                                self.assertEqual(result["primaryInk"], "rgb(24, 17, 10)")
                                self.assertEqual(result["themeColor"], "#080909")
                                self.assertFalse(errors, errors)
                                page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
