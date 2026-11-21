"""Stage 2/2: iPhone card, filter, profile, and finance visual regression.

Synthetic Telegram HTTP fixture only; no personal data or remote calls.
"""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler
from tests.test_profile_stage6_browser import FIXTURE


FINANCE_OK = FIXTURE.replace(
    "if(path==='/invitations/referral'){",
    """if(path==='/finance/overview') data={
      balances:{available_rub:200,reserved_rub:0,paid_rub:0,accrued_rub:200},
      withdrawals:[],accruals:[]};
    if(path==='/invitations/referral'){""",
)
LEGACY_FIXTURE = FIXTURE.replace("let creditFresh=!minor;", "let creditFresh=!minor&&!legacy;")


class MobileVisualStage2Tests(unittest.TestCase):
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

    def open(self, browser, width, *, legacy=False, finance_ok=False):
        page = browser.new_page(viewport={"width": width, "height": 844})
        page.add_init_script(FINANCE_OK if finance_ok else LEGACY_FIXTURE if legacy else FIXTURE)
        page.goto(self.base + f"/partners/#tgWebAppData=stage2&legacy={int(legacy)}")
        page.locator("#participant-nav").wait_for(state="visible")
        return page

    def assert_no_horizontal_overflow(self, page, width):
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width + 1)

    def test_offers_filters_target_and_profile_form(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for width in (320, 375, 390, 430):
                    with self.subTest(width=width):
                        page = self.open(browser, width, legacy=True)
                        page.locator('#participant-nav [data-view="offers"]').click()
                        page.locator("#offer-controls").wait_for(state="visible")
                        sections = page.evaluate("""() => {
                          const intro = document.querySelector('#participant-offers-view .participant-screen-offers').getBoundingClientRect();
                          const offers = document.querySelector('#offers-section').getBoundingClientRect();
                          return {gap: offers.top - intro.bottom};
                        }""")
                        self.assertGreaterEqual(sections["gap"], 20, sections)
                        self.assertLessEqual(sections["gap"], 26, sections)
                        geometry = page.locator(".participant-offer-filter button").evaluate_all("""buttons =>
                          buttons.map(btn => ({x:btn.getBoundingClientRect().left,
                            right:btn.getBoundingClientRect().right,
                            y:btn.getBoundingClientRect().top,
                            width:btn.getBoundingClientRect().width}))""")
                        self.assertEqual(len(geometry), 4)
                        self.assertEqual(len({item["y"] for item in geometry}), 2, geometry)
                        self.assertTrue(all(item["width"] >= 65 for item in geometry), geometry)
                        controls = page.locator("#offer-controls").bounding_box()
                        self.assertTrue(all(item["x"] >= controls["x"] - 1 and
                                            item["right"] <= controls["x"] + controls["width"] + 1
                                            for item in geometry), geometry)
                        target = page.locator(".participant-offer-target strong").first
                        self.assertEqual(target.evaluate("el => getComputedStyle(el).overflow"), "visible")
                        self.assert_no_horizontal_overflow(page, width)

                        page.locator('#participant-nav [data-view="profile"]').click()
                        page.locator("#participant-legacy-onboarding").wait_for(state="visible")
                        self.assertEqual(page.locator("#participant-legacy-onboarding label.check > span").count(), 3)
                        self.assert_no_horizontal_overflow(page, width)
                        page.close()
            finally:
                browser.close()

    def test_finance_request_disabled_on_error_and_enabled_on_valid_balance(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for width in (320, 375, 390, 430):
                    with self.subTest(width=width):
                        page = self.open(browser, width)
                        page.locator('#participant-nav [data-view="profile"]').click()
                        page.locator("#finance-load-status").get_by_text(
                            "Баланс временно недоступен", exact=False).wait_for()
                        self.assertTrue(page.locator("#finance-request-submit").is_disabled())
                        self.assertIn("Запрос выплаты недоступен", page.locator("#finance-request-feedback").inner_text())
                        self.assert_no_horizontal_overflow(page, width)
                        page.close()

                        good = self.open(browser, width, finance_ok=True)
                        good.locator('#participant-nav [data-view="profile"]').click()
                        good.locator("#finance-available").get_by_text("200 ₽").wait_for()
                        self.assertTrue(good.locator("#finance-request-submit").is_enabled())
                        self.assertFalse(good.locator("#finance-load-status").is_visible())
                        self.assert_no_horizontal_overflow(good, width)
                        good.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
