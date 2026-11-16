"""The selected AP icon replaces the former letter mark in both UI headers."""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler


class HeaderLogoBrowserTests(unittest.TestCase):
    def test_selected_ap_icon_is_loaded_and_visible(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    for path in ("/partners/", "/partners/admin/"):
                        for width in (390, 1440):
                            with self.subTest(path=path, width=width):
                                page = browser.new_page(viewport={"width": width, "height": 844})
                                page.goto(f"http://127.0.0.1:{server.server_port}{path}")
                                marks = page.locator("a.brand .mark img")
                                self.assertGreater(marks.count(), 0)
                                for mark in marks.all():
                                    self.assertEqual(mark.get_attribute("src"), "/partners/ap-mark.png")
                                    self.assertTrue(mark.evaluate("img => img.complete && img.naturalWidth > 0"))
                                    if mark.is_visible():
                                        self.assertGreater(mark.bounding_box()["width"], 30)
                                page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
