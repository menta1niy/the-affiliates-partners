"""Stage 11 fourth-tab responsive statistics and truthful money labels."""
import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright
from tests.test_admin_participant_browser import BrowserHandler
from tests.test_profile_stage6_browser import FIXTURE


BOOTSTRAP = FIXTURE.replace(
    "if(path==='/invitations/referral'){",
    """if(path==='/statistics/overview'){
      window.__statsRequested=(window.__statsRequested||0)+1;
      data={assigned_count:3,
        stages:{assigned:1,in_progress:1,submitted:0,completed:1,rejected:0},
        potential:{not_started_rub:1200,in_work_rub:2300,hold_rub:4100},
        verified:{available_rub:150,paid_rub:900,reserved_rub:300,accrued_rub:1350}};
    }
    if(path==='/invitations/referral'){""",
)


class Stage11BrowserTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_fourth_tab_at_320_and_390_px(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for width in (320, 390):
                    with self.subTest(width=width):
                        page = browser.new_page(viewport={"width": width, "height": 844})
                        errors = []
                        page.on("pageerror", lambda exc: errors.append(str(exc)))
                        page.add_init_script(BOOTSTRAP)
                        page.goto(self.base + "/partners/#tgWebAppData=stage11")
                        page.locator("#kpi-total").get_by_text("1", exact=True).wait_for()
                        self.assertEqual(page.locator("#participant-nav [data-view]").count(), 4)
                        page.locator('#participant-nav [data-view="statistics"]').click()
                        page.locator("#statistics-paid").get_by_text("900 ₽").wait_for()
                        self.assertEqual(page.locator("#statistics-not-started").inner_text(), "1 200 ₽")
                        self.assertEqual(page.locator("#statistics-hold").inner_text(), "4 100 ₽")
                        self.assertEqual(page.locator("#statistics-available").inner_text(), "150 ₽")
                        self.assertTrue(page.locator("#participant-statistics-view").is_visible())
                        self.assertFalse(page.locator("#participant-profile-view").is_visible())
                        self.assertEqual(page.locator('#participant-nav [data-view="statistics"]').get_attribute("aria-current"), "page")
                        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width+1)
                        self.assertFalse(errors, errors)
                        page.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
