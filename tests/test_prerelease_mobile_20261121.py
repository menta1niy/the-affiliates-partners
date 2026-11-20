"""Focused prerelease navigation and legal-link checks in a local Chromium webview.

API replies are synthetic; no real Telegram authentication or production requests.
"""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler
from tests.test_admin_redesign_browser import BOOTSTRAP as ADMIN_FIXTURE
from tests.test_onboarding_registration_browser import FIXTURE as REGISTRATION_FIXTURE


LEGAL_DOCUMENTS = ("privacy", "data-consent", "terms", "referrals", "bloggers")


class PrereleaseMobileBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def assert_fits_viewport(self, page, width):
        dimensions = page.evaluate("""() => ({
            viewport: document.documentElement.clientWidth,
            scroll: document.documentElement.scrollWidth
        })""")
        self.assertLessEqual(dimensions["scroll"], dimensions["viewport"] + 1, dimensions)
        self.assertEqual(dimensions["viewport"], width, dimensions)

    def test_registration_links_open_local_legal_documents(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for width in (320, 390, 768):
                    with self.subTest(width=width):
                        page = browser.new_page(viewport={"width": width, "height": 844})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.add_init_script(REGISTRATION_FIXTURE)
                        page.goto(self.base + "/partners/#tgWebAppData=fixture&state=invited")
                        form = page.locator("#register-form")
                        form.wait_for(state="visible")
                        self.assert_fits_viewport(page, width)
                        for name in LEGAL_DOCUMENTS[:4]:
                            with self.subTest(width=width, document=name):
                                anchor = form.locator(f'a[href="/partners/legal/{name}.html"]').first
                                self.assertTrue(anchor.is_visible())
                                self.assertEqual(anchor.get_attribute("target"), "_blank")
                                with page.expect_popup() as popup_info:
                                    anchor.click()
                                popup = popup_info.value
                                popup.wait_for_load_state("domcontentloaded")
                                self.assertEqual(popup.url, self.base + f"/partners/legal/{name}.html")
                                self.assertTrue(popup.locator("h1").is_visible())
                                self.assertNotIn("ПРОЕКТ", popup.locator("aside").inner_text())
                                self.assertIn("Митряков Денис Анатольевич", popup.locator("main").inner_text())
                                self.assert_fits_viewport(popup, width)
                                popup.close()
                        self.assert_fits_viewport(page, width)
                        self.assertFalse(errors, errors)
                        page.close()
            finally:
                browser.close()

    def test_admin_sections_and_history_mobile_geometry(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for width in (320, 390, 768):
                    with self.subTest(width=width):
                        page = browser.new_page(viewport={"width": width, "height": 844})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.add_init_script(ADMIN_FIXTURE)
                        page.goto(self.base + "/partners/admin/#tgWebAppData=fixture&role=owner")
                        page.locator("#admin-app").wait_for(state="visible")
                        self.assert_fits_viewport(page, width)
                        for section in ("offers", "assignments", "people", "more"):
                            page.locator(f'[data-section="{section}"]').click()
                            self.assert_fits_viewport(page, width)
                        page.go_back()
                        self.assertTrue(page.locator('[data-panel="pending"]').is_visible())
                        self.assert_fits_viewport(page, width)
                        self.assertFalse(errors, errors)
                        page.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
