"""Mobile regressions for the public offer catalogue and contact gate."""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler
from tests.test_participant_redesign_browser import FIXTURE


# Four published offers: two available to start, one in progress, one submitted.
# Unassigned offers must be visible without inflating personal progress counters.
PUBLIC_FIXTURE = (
    FIXTURE
    .replace("stage:'assigned',\n           target_action:",
             "stage:'assigned',is_assigned:false,can_apply:true,\n           target_action:")
    .replace("stage:'completed',target_action:",
             "stage:'assigned',is_assigned:false,can_apply:true,target_action:")
)


class PublicCatalogMobileRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/partners/#tgWebAppData=fixture"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_public_catalog_and_personal_progress_are_distinct(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (320, 375, 390):
                    with self.subTest(width=width):
                        page = browser.new_page(viewport={"width": width, "height": 844})
                        page.add_init_script(PUBLIC_FIXTURE)
                        page.goto(self.url)
                        page.locator("#kpi-total").get_by_text("4", exact=True).wait_for()
                        self.assertEqual(page.locator("#participant-kpis .metric span").first.inner_text(), "ДОСТУПНО")
                        self.assertEqual(page.locator("#kpi-in-progress").inner_text(), "1")
                        self.assertEqual(page.locator("#kpi-submitted").inner_text(), "1")
                        self.assertEqual(page.locator("#kpi-completed").inner_text(), "0")
                        page.locator('#participant-nav [data-view="offers"]').click()
                        cards = page.locator("#offers .offer-item")
                        self.assertEqual(cards.count(), 4)
                        self.assertEqual(cards.locator('.participant-offer-status', has_text='Доступен').count(), 2)
                        self.assertEqual(cards.locator('.participant-offer-status', has_text='Не начато').count(), 0)
                        cards.first.locator(".participant-offer-detail-button").click()
                        self.assertIn("Доступен", page.locator("#participant-offer-dialog").inner_text())
                        self.assertTrue(page.locator(".participant-offer-start").is_visible())
                        self.assertLessEqual(
                            page.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth"), 1
                        )
                        page.close()
            finally:
                browser.close()

    def test_contact_gate_clears_previous_account_navigation(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.add_init_script(PUBLIC_FIXTURE)
                page.goto(self.url)
                page.locator("#participant-nav").wait_for(state="visible")
                page.locator('#participant-nav [data-view="profile"]').click()
                page.evaluate("""() => {
                    const original = window.fetch;
                    window.fetch = (url, options) => String(url).endsWith('/partners/api/session')
                      ? Promise.resolve(new Response(JSON.stringify({
                          user:{id:881031,role:'lead',status:'active'},
                          role:'lead',status:'active',source:'telegram',contact_required:true
                        }),{status:200,headers:{'Content-Type':'application/json'}}))
                      : original(url, options);
                    // A stale session is re-checked after contact authorization changes.
                    document.getElementById('refresh').click();
                }""")
                page.locator("#connect").wait_for(state="visible")
                self.assertFalse(page.locator("#participant-nav").is_visible())
                self.assertFalse(page.locator("#account").is_visible())
                self.assertFalse(page.locator("#pending-panel").is_visible())
                self.assertFalse(page.locator("#rejected-panel").is_visible())
                self.assertIn("«Кабинет»", page.locator("#connect-description").inner_text())
                page.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
