"""Focused Mini App registration UX checks with synthetic Telegram session."""
import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright
from tests.test_admin_participant_browser import BrowserHandler


FIXTURE = r"""(() => {
  const params=new URLSearchParams(location.hash.slice(1));
  let status=params.get('state')||'invited';
  window.__registerCalls=[];
  const baseFetch=window.fetch.bind(window);
  window.fetch=(url,opts)=>{
    const path=String(url).replace('/partners/api','');
    let data;
    const user={id:719001,internal_id:status==='invited'?null:124,
      display_id:status==='invited'?null:'L-000124',
      first_name:'Тест',last_name:'',username:'sample_user',role:'lead',
      status,decision_reason:status==='rejected'?'Не подошли условия участия':''};
    if(path==='/session')data={user,role:'lead',status,source:'telegram',
      open_registration:true,registration:null};
    if(path==='/register'){
      window.__registerCalls.push(JSON.parse(opts.body));
      status='pending';
      data={user:{...user,status:'pending',internal_id:124,display_id:'L-000124'},role:'lead',status:'pending'};
    }
    if(data!==undefined)return Promise.resolve(new Response(JSON.stringify(data),
      {status:200,headers:{'Content-Type':'application/json'}}));
    return baseFetch(url,opts);
  };
})()"""


class OnboardingRegistrationBrowserTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(("127.0.0.1",0),BrowserHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_registration_form_and_pending_id_in_webview(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for width in (320,390):
                    with self.subTest(width=width):
                        page=browser.new_page(viewport={"width":width,"height":844})
                        page.add_init_script(FIXTURE)
                        errors=[]
                        page.on("pageerror",lambda exc:errors.append(str(exc)))
                        page.goto(self.base+"/partners/#tgWebAppData=fixture&state=invited")
                        form=page.locator("#register-form");form.wait_for(state="visible")
                        self.assertEqual(form.locator('input[type="number"]').count(),0)
                        self.assertFalse(page.locator("#pending-panel").is_visible())
                        self.assertEqual(form.locator('input[type="date"]').count(),0)
                        form.locator('label:has(input[name="register-credit-band"][value="1-3"])').click()
                        form.locator("#consent").check()
                        form.locator("#register-terms-consent").check()
                        form.locator("#register-adult-confirmed").check()
                        page.locator("#register-submit").click()
                        page.locator("#pending-panel").wait_for(state="visible")
                        self.assertEqual(page.locator("#pending-internal-id").inner_text(),"L-000124")
                        payload=page.evaluate("window.__registerCalls[0]")
                        self.assertNotIn("birth_date",payload)
                        self.assertNotIn("credit_cards",payload)
                        self.assertEqual(payload["credit_band"],"1-3")
                        self.assertTrue(payload["adult_confirmed"])
                        self.assertTrue(payload["privacy_accepted"])
                        self.assertTrue(payload["terms_accepted"])
                        self.assertEqual(len(page.evaluate("window.__registerCalls")),1)
                        self.assertEqual(page.evaluate("document.documentElement.scrollWidth"),width)
                        self.assertFalse(errors,errors)
                        page.close()
            finally:
                browser.close()

    def test_rejected_view_keeps_id_and_reason(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={"width":320,"height":844})
                page.add_init_script(FIXTURE)
                page.goto(self.base+"/partners/#tgWebAppData=fixture&state=rejected")
                page.locator("#rejected-panel").wait_for(state="visible")
                self.assertEqual(page.locator("#rejected-internal-id").inner_text(),"L-000124")
                self.assertIn("Не подошли условия",page.locator("#rejected-reason").inner_text())
                self.assertFalse(page.locator("#register-form").is_visible())
                page.close()
            finally:
                browser.close()


if __name__=="__main__":
    unittest.main()
