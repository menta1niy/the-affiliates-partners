"""Focused mobile finance and admin payment UX contracts, no real payments."""
import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright
from tests.test_admin_participant_browser import BrowserHandler
from tests.test_profile_stage6_browser import FIXTURE as PROFILE_BOOTSTRAP
from tests.test_admin_redesign_browser import BOOTSTRAP as ADMIN_BOOTSTRAP


LEAD_BOOTSTRAP = PROFILE_BOOTSTRAP.replace(
    "if(path==='/invitations/referral'){",
    """if(path==='/finance/overview'){
      const balance=window.__financeBalance??1500;
      data={balances:{accrued_rub:1500,paid_rub:0,
        reserved_rub:1500-balance,available_rub:balance},
        accruals:[{id:'ac_123',offer_id:'manual_a',amount_rub:1500,source_reference:'bank.ref.1'}],
        withdrawals:window.__financeWithdrawals??[]};
    }
    if(path==='/finance/withdraw'){
      const body=JSON.parse(opts.body);
      window.__financeSubmitted=body;
      window.__financeBalance=1500-body.amount_rub;
      window.__financeWithdrawals=[{id:'wd_123456789012345678901234',amount_rub:body.amount_rub,status:'pending',
        review_note:''}];
      data={withdrawal:{id:'wd_123456789012345678901234',amount_rub:body.amount_rub,status:'pending'},
        balances:{available_rub:window.__financeBalance}};
    }
    if(path==='/invitations/referral'){"""
)

ADMIN_FINANCE_BOOTSTRAP = ADMIN_BOOTSTRAP.replace(
    "if(path==='/admin/mvp/offer') {",
    """if(path==='/admin/finance/withdrawals'){
      const state=window.__financeReview?.decision==='confirm'?'confirmed':'pending';
      data={withdrawals:[{id:'wd_123456789012345678901234',user_id:881032,
        display_id:'L-000113',amount_rub:700,status:state,review_note:'',has_payout_details:true}]};
    }
    if(path==='/admin/finance/payout-details'){
      data={details:{phone:'+79000000000',bank:'Test Bank'}};
    }
    if(path==='/admin/finance/decision'){
      window.__financeReview=JSON.parse(opts.body);data={changed:true,status:'confirmed'};
    }
    if(path==='/admin/mvp/offer') {"""
)


class Stage8BrowserTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(("127.0.0.1",0),BrowserHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_lead_finance_request_mobile(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for width in (320,390):
                    with self.subTest(width=width):
                        page=browser.new_page(viewport={"width":width,"height":844})
                        errors=[]
                        page.on("pageerror",lambda ex:errors.append(str(ex)))
                        page.add_init_script(LEAD_BOOTSTRAP)
                        page.goto(self.base+"/partners/#tgWebAppData=finance")
                        page.locator("#kpi-total").get_by_text("1",exact=True).wait_for()
                        page.locator('#participant-nav [data-view="profile"]').click()
                        page.locator("#finance-available").get_by_text("1 500 ₽").wait_for()
                        self.assertTrue(page.locator("#participant-finance-panel").is_visible())
                        self.assertFalse(page.locator("#participant-finance-request").is_visible())
                        self.assertFalse(page.locator("#finance-request-support").is_visible())
                        page.locator("#finance-request-open").click()
                        page.locator("#finance-request-amount").fill("700")
                        page.locator("#finance-payout-phone").fill("+79000000000")
                        page.locator("#finance-payout-bank").fill("Test Bank")
                        page.on("dialog",lambda dialog:dialog.accept())
                        page.locator("#finance-request-submit").click()
                        page.wait_for_function("Boolean(window.__financeSubmitted)")
                        page.locator("#finance-available").get_by_text("800 ₽").wait_for()
                        self.assertEqual(page.locator("#finance-reserved").inner_text(),"700 ₽")
                        self.assertEqual(page.evaluate("window.__financeSubmitted.amount_rub"),700)
                        self.assertEqual(page.evaluate("window.__financeSubmitted.payout_bank"),"Test Bank")
                        self.assertTrue(page.locator("#finance-request-support").is_visible())
                        self.assertEqual(page.locator("#finance-request-support").get_attribute("href"),"https://t.me/AffiliatesAdmin")
                        self.assertIn("WD-123456789012345678901234",page.locator("#finance-request-number").inner_text())
                        self.assertIn("WD-123456789012345678901234",page.locator("#finance-withdrawals").inner_text())
                        self.assertTrue(page.locator("#finance-withdrawals").get_by_text("На рассмотрении",exact=False).is_visible())
                        self.assertEqual(page.evaluate("document.documentElement.scrollWidth"),width)
                        self.assertFalse(errors,errors)
                        page.close()
            finally:
                browser.close()

    def test_admin_finance_tab_mobile(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={"width":320,"height":844})
                errors=[]
                page.on("pageerror",lambda ex:errors.append(str(ex)))
                page.add_init_script(ADMIN_FINANCE_BOOTSTRAP)
                page.goto(self.base+"/partners/admin/#tgWebAppData=finance&role=owner")
                page.locator("#admin-app").wait_for(state="visible")
                page.locator('[data-section="people"]').click()
                page.locator('[data-subtab="finance"]').click()
                page.locator("#admin-finance-list .admin-offer-event-card").first.wait_for()
                self.assertIn("L-000113",page.locator("#admin-finance-list").inner_text())
                self.assertIn("WD-123456789012345678901234",page.locator("#admin-finance-list").inner_text())
                page.locator("#admin-finance-list").get_by_role("button",name="Показать реквизиты СБП").click()
                page.locator("#admin-finance-list").get_by_text("Банк: Test Bank",exact=False).wait_for()
                page.on("dialog",lambda dialog:dialog.accept())
                page.locator("#admin-finance-list").get_by_role("button",name="Подтвердить").click()
                page.wait_for_function("Boolean(window.__financeReview)")
                self.assertEqual(page.evaluate("window.__financeReview.decision"),"confirm")
                self.assertEqual(page.evaluate("document.documentElement.scrollWidth"),320)
                self.assertFalse(errors,errors)
                page.close()
            finally:
                browser.close()


if __name__=="__main__":
    unittest.main()
