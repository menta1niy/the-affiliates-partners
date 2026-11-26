"""Referral profile KPIs stay readable on narrow Telegram WebViews."""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler
from tests.test_profile_stage6_browser import FIXTURE as PROFILE_FIXTURE


REFERRAL_FIXTURE = PROFILE_FIXTURE.replace(
    "if(path==='/invitations/referral'){",
    """if(path==='/finance/overview'){
      const large=params.get('large')==='1';
      data={balances:{available_rub:0,reserved_rub:0,paid_rub:0,accrued_rub:0},
        accruals:[],withdrawals:[],
        referral:{invited_count:large?1234:0,earned_kopeks:large?123456789:0,rewards:[]}};
    }
    if(path==='/invitations/referral'){"""
)


class ReferralSummaryMobileBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/partners/"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_two_kpi_cards_are_aligned_and_readable(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (320, 375, 390, 430):
                    for large in (False, True):
                        with self.subTest(width=width, large=large):
                            page = browser.new_page(viewport={"width": width, "height": 844})
                            errors = []
                            page.on("pageerror", lambda exc: errors.append(str(exc)))
                            page.add_init_script(REFERRAL_FIXTURE)
                            page.goto(self.url + f"#tgWebAppData=fixture&large={int(large)}")
                            page.locator('#participant-nav [data-view="profile"]').click()
                            summary = page.locator("#participant-referral-summary")
                            summary.wait_for(state="visible", timeout=10000)
                            self.assertEqual(summary.locator(":scope > div").count(), 2)
                            invited = page.locator("#referral-invited").inner_text()
                            earned = page.locator("#referral-earned").inner_text()
                            self.assertEqual(invited, "1\u00a0234" if large else "0")
                            self.assertEqual(earned, "1\u00a0234\u00a0567,89 ₽" if large else "0,00 ₽")
                            geometry = summary.evaluate("""node => {
                              const cards = [...node.children];
                              return {
                                grid:getComputedStyle(node).gridTemplateColumns.split(' ').length,
                                gap:parseFloat(getComputedStyle(node).columnGap),
                                parent:node.getBoundingClientRect().toJSON(),
                                cards:cards.map(card => {
                                  const label=card.querySelector('span').getBoundingClientRect();
                                  const number=card.querySelector('strong').getBoundingClientRect();
                                  const rect=card.getBoundingClientRect();
                                  return {left:rect.left,right:rect.right,top:rect.top,
                                    bottom:rect.bottom,padding:parseFloat(getComputedStyle(card).paddingLeft),
                                    separation:number.top-label.bottom,
                                    numberColor:getComputedStyle(card.querySelector('strong')).color,
                                    lineHeight:parseFloat(getComputedStyle(card.querySelector('strong')).lineHeight)};
                                })
                              };
                            }""")
                            self.assertEqual(geometry["grid"], 2, geometry)
                            self.assertGreaterEqual(geometry["gap"], 8, geometry)
                            first, second = geometry["cards"]
                            self.assertGreaterEqual(first["padding"], 12, geometry)
                            self.assertGreaterEqual(second["padding"], 12, geometry)
                            self.assertGreater(first["separation"], 3, geometry)
                            self.assertGreater(second["separation"], 3, geometry)
                            self.assertLessEqual(abs(first["top"] - second["top"]), 1, geometry)
                            self.assertLessEqual(first["right"] + geometry["gap"] - 1, second["left"], geometry)
                            self.assertLessEqual(second["right"], geometry["parent"]["right"] + 1, geometry)
                            self.assertEqual(first["numberColor"], "rgb(228, 163, 74)")
                            self.assertGreater(first["lineHeight"], 19)
                            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                            self.assertFalse(errors, errors)
                            page.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
