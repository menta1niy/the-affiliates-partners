"""Participant branding is text-only; the admin keeps its selected AP icon."""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler


class HeaderLogoBrowserTests(unittest.TestCase):
    def test_participant_text_brand_and_admin_ap_icon(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    for path in ("/partners/", "/partners/admin/"):
                        for width in (320, 390, 1440):
                            with self.subTest(path=path, width=width):
                                page = browser.new_page(viewport={"width": width, "height": 844})
                                page.goto(f"http://127.0.0.1:{server.server_port}{path}")
                                marks = page.locator("a.brand .mark img")
                                if path == "/partners/":
                                    self.assertEqual(marks.count(), 0)
                                    self.assertEqual(page.locator(".participant-top .brand").inner_text(), "THE AFFILIATES\nPARTNERS")
                                    self.assertEqual(page.locator(".participant-top .header-label").count(), 0)
                                    self.assertNotIn("NETWORK", page.locator(".participant-top").inner_text())
                                    self.assertEqual(page.locator(".participant-hero .eyebrow").inner_text().split("—")[0].strip(), "THE AFFILIATES / PARTNERS")
                                    header = page.locator(".participant-top .brand")
                                    self.assertLessEqual(header.bounding_box()["x"] + header.bounding_box()["width"], width)
                                    colors = header.evaluate("""element => ({
                                        title: getComputedStyle(element).color,
                                        subtitle: getComputedStyle(element.querySelector('small')).color
                                    })""")
                                    self.assertNotEqual(colors["title"], colors["subtitle"])
                                else:
                                    self.assertGreater(marks.count(), 0)
                                    self.assertTrue(page.locator(".admin-mobile-header .admin-back-link").count() == 1)
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
