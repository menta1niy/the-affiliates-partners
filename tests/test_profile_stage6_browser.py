"""Stage 6: responsive profile editor and server-provided offer access status."""
import threading
import unittest
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler


FIXTURE = r"""(() => {
  const params=new URLSearchParams(location.hash.slice(1));
  const minor=params.get('minor')==='1';
  const legacy=params.get('legacy')==='1';
  const simple=params.get('simple')==='1';
  let complete=false;
  let creditFresh=!minor;
  window.__profileActions=[];
  const original=window.fetch.bind(window);
  const unavailable=()=>{
    if(minor)return 'underage';
    if(!complete)return 'identity';
    if(!creditFresh)return 'credit_review';
    return '';
  };
  window.fetch=(url,opts)=>{
    const path=String(url).replace('/partners/api','');
    let data;
    const birth=minor?'2010-08-18':'2000-08-18';
    const user={id:721001,first_name:'Тест',username:'testlead',role:'lead',
      internal_id:121,display_id:'L-000121',status:'active'};
    if(path==='/session')data={
      source:'telegram',user,role:'lead',status:'active',open_registration:true,
      registration:legacy&&!creditFresh?null:{birth_date:simple?null:birth,age:simple?null:minor?16:26,adult_confirmed:!minor,submitted_at:100,
        credit_updated_at:creditFresh?Math.round(Date.now()/1000):100,
        credit_products:{credit_cards:1,installments:0,loans:0,mortgages:0}},
      identity:complete?{complete:true,surname:'Иванов',given_name:'Иван',
        patronymic:'',inn_masked:'********2259'}:{complete:false}
    };
    if(path==='/mvp/overview'){
      const deny=unavailable();
      data={statistics:{total:1,in_progress:0,completed:0},
        offers:[{id:'manual_a',name:'Тест кредитной карты',category:'Кредитные карты',
          payout_rub:900,hold_days:7,stage:'assigned',target_action:'Оформить',
          referral_url:deny?'':'https://bank.test/offer',
          can_apply:!deny,unavailable_reason:deny}]};
    }
    if(path==='/profile/identity'){
      const body=JSON.parse(opts.body);
      window.__profileActions.push({path,body});
      complete=true;
      data={saved:true,identity:{complete:true,surname:body.surname,given_name:body.given_name,
        patronymic:body.patronymic,inn_masked:'********2259'}};
    }
    if(path==='/profile/credit-survey'){
      window.__profileActions.push({path,body:JSON.parse(opts.body)});
      creditFresh=true;data={registration:{credit_products_total:2}};
    }
    if(path==='/profile/onboarding'){
      window.__profileActions.push({path,body:JSON.parse(opts.body)});
      creditFresh=true;data={registration:{birth_date:birth,credit_products_total:1},id_unchanged:121};
    }
    if(path==='/invitations/referral'){
      data={code:'ref_abcdef12345678'};
    }
    if(data!==undefined)return Promise.resolve(new Response(JSON.stringify(data),
      {status:200,headers:{'Content-Type':'application/json'}}));
    return original(url,opts);
  };
})()"""


class ProfileStage6BrowserTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(("127.0.0.1",0),BrowserHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def open(self,browser,width,minor=False,legacy=False,simple=False):
        page=browser.new_page(viewport={"width":width,"height":844})
        page.add_init_script(FIXTURE)
        page.goto(self.base+f"/partners/#tgWebAppData=fixture&minor={int(minor)}&legacy={int(legacy)}&simple={int(simple)}")
        page.locator("#kpi-total").get_by_text("1",exact=True).wait_for()
        return page

    def test_locked_offer_switches_to_profile_and_unlocks_after_completion(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for width in (320,390):
                    with self.subTest(width=width):
                        page=self.open(browser,width,simple=True)
                        errors=[]
                        page.on("pageerror",lambda err:errors.append(str(err)))
                        page.locator('#participant-nav [data-view="offers"]').click()
                        page.locator(".participant-offer-access-pill").get_by_text("Недоступно").wait_for()
                        page.locator(".participant-offer-detail-button").click()
                        modal=page.locator("#participant-offer-dialog")
                        self.assertTrue(modal.locator(".participant-offer-unavailable").is_disabled())
                        self.assertEqual(modal.locator('a[href="https://bank.test/offer"]').count(),0)
                        modal.locator(".participant-offer-profile-action").click()
                        page.locator("#participant-identity-panel").wait_for(state="visible")
                        self.assertTrue(page.locator("#participant-credit-panel").is_visible())
                        page.locator(".participant-technical summary").click()
                        self.assertEqual(page.locator("#profile-internal-id").inner_text(),"L-000121")
                        page.locator("#participant-surname").fill("Иванов")
                        page.locator("#participant-given-name").fill("Иван")
                        self.assertNotIn('18 лет',page.locator('#participant-identity-status').inner_text())
                        page.locator("#participant-inn").fill("5001 0073 2259")
                        page.locator("#participant-identity-save").click()
                        page.locator("#participant-identity-status").get_by_text("Реквизиты сохранены",exact=False).wait_for()
                        page.locator('#participant-nav [data-view="offers"]').click()
                        page.locator(".participant-offer-detail-button").click()
                        self.assertEqual(page.locator("#participant-offer-dialog .participant-offer-unavailable").count(),0)
                        self.assertEqual(page.locator('#participant-offer-dialog a[href="https://bank.test/offer"]').count(),1)
                        self.assertFalse(page.evaluate("document.documentElement.scrollWidth>innerWidth"))
                        self.assertFalse(errors,errors)
                        actions=page.evaluate("window.__profileActions")
                        self.assertEqual(actions[0]["path"],"/profile/identity")
                        self.assertEqual(actions[0]["body"]["inn"],"500100732259")
                        page.close()
            finally:
                browser.close()

    def test_minor_has_grey_disabled_action_and_referral_panel(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=self.open(browser,320,minor=True)
                page.locator('#participant-nav [data-view="offers"]').click()
                page.locator(".participant-offer-detail-button").click()
                self.assertTrue(page.locator(".participant-offer-unavailable").is_disabled())
                self.assertEqual(page.locator(".participant-offer-profile-action").count(),0)
                page.locator("#participant-offer-close").click()
                page.locator('#participant-nav [data-view="profile"]').click()
                self.assertTrue(page.locator("#referral-panel").is_visible())
                self.assertFalse(page.evaluate("document.documentElement.scrollWidth>innerWidth"))
                page.close()
            finally:
                browser.close()

    def test_existing_account_legacy_onboarding_keeps_internal_id(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=self.open(browser,390,legacy=True,minor=True)
                page.locator('#participant-nav [data-view="profile"]').click()
                self.assertTrue(page.locator("#participant-legacy-onboarding").is_visible())
                self.assertTrue(page.locator("#participant-identity-save").is_disabled())
                page.locator('label:has(input[name="participant-credit-band"][value="1-3"])').click()
                page.locator("#participant-legacy-privacy").check()
                page.locator("#participant-legacy-terms").check()
                page.locator("#participant-legacy-adult").check()
                page.locator("#participant-credit-save").click()
                page.wait_for_function("window.__profileActions.length>0")
                self.assertEqual(page.evaluate("window.__profileActions[0].path"),"/profile/onboarding")
                self.assertEqual(page.evaluate("window.__profileActions[0].body.credit_band"),"1-3")
                self.assertTrue(page.evaluate("window.__profileActions[0].body.adult_confirmed"))
                page.close()
            finally:
                browser.close()


if __name__=="__main__":
    unittest.main()
