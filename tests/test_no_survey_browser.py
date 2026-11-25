"""Focused mobile smoke: no profile survey and a directly usable assigned offer."""
import threading
import unittest
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
from tests.test_admin_participant_browser import BrowserHandler
from tests.test_participant_redesign_browser import FIXTURE

BOOTSTRAP = FIXTURE.replace(
    "if (endpoint === '/invitations/referral')",
    """if (endpoint === '/finance/overview') return Promise.resolve(
      new Response(JSON.stringify({balances:{
        accrued_rub:0,paid_rub:0,reserved_rub:0,available_rub:0},
        accruals:[],withdrawals:[]}),{status:200,
        headers:{'Content-Type':'application/json'}}));
    if (endpoint === '/invitations/referral')""")


class NoSurveyBrowserTests(unittest.TestCase):
    def test_active_lead_sees_offer_without_profile_forms(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    for width in (320, 390):
                        page = browser.new_page(viewport={"width": width, "height": 844})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.add_init_script(BOOTSTRAP)
                        page.goto(f"http://127.0.0.1:{server.server_port}/partners/#tgWebAppData=fixture")
                        page.locator("#kpi-total").get_by_text("4", exact=True).wait_for(timeout=10000)
                        self.assertEqual(page.locator("#participant-identity-panel").count(), 0)
                        self.assertEqual(page.locator("#participant-credit-panel").count(), 0)
                        page.locator('#participant-nav [data-view="offers"]').click()
                        self.assertIn("Альфа Банк", page.locator("#participant-offers-view").inner_text())
                        self.assertFalse(errors, errors)
                        self.assertEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                        page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
