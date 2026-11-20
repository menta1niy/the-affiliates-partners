"""Read-only mobile-browser smoke of the staged standalone legal documents."""
import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright
from tests.test_admin_participant_browser import BrowserHandler


class Stage13LegalBrowserTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), BrowserHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_legal_drafts_render_and_are_clearly_marked_unapproved(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (320, 390):
                    page = browser.new_page(viewport={'width': width, 'height': 844})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    for name in ('privacy', 'data-consent', 'terms', 'referrals', 'bloggers'):
                        response = page.goto(self.base + f'/partners/legal/{name}.html')
                        self.assertEqual(response.status, 200)
                        self.assertIn('ПРОЕКТ', page.locator('aside').inner_text())
                        self.assertTrue(page.locator('h1').is_visible())
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width+1)
                    self.assertFalse(errors, errors)
                    page.close()
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
