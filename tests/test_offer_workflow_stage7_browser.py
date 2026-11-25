"""Browser QA for lead evidence + MFO request and admin review panel."""
import threading
import io
import unittest
from http.server import ThreadingHTTPServer
from PIL import Image

from playwright.sync_api import sync_playwright
from tests.test_admin_participant_browser import BrowserHandler
from tests.test_admin_redesign_browser import BOOTSTRAP


LEAD_BOOT = r"""(() => {
  const fetchOriginal=window.fetch.bind(window);
  let mfoApproved=false, pendingStage=false, pendingMfo=false;
  window.__stage7Calls=[];
  window.fetch=(url,opts)=>{
    const route=String(url).replace('/partners/api','');
    let data;
    if(route==='/session')data={source:'telegram',
      user:{id:721001,internal_id:124,first_name:'Тест',role:'lead',status:'active'},
      role:'lead',status:'active',open_registration:true,
      registration:{birth_date:'2000-01-01',age:26,credit_updated_at:Math.floor(Date.now()/1000),
        credit_products:{credit_cards:0,installments:0,loans:0,mortgages:0}},
      identity:{complete:true,surname:'Тестов',given_name:'Тест',inn_masked:'********2259'}};
    if(route==='/mvp/overview')data={statistics:{total:2,in_progress:0,completed:0},
      offers:[
        {id:'manual_c',name:'Дебетовая карта',category:'Дебетовые карты',payout_rub:1000,
         hold_days:7,stage:'assigned',target_action:'Оформить',can_apply:true,
         unavailable_reason:'',lead_stages:['application_sent','meeting_scheduled'],next_stage:'application_sent',
         referral_url:'https://bank.test/debit',
         latest_event:pendingStage?{id:'evt_a',kind:'stage',lead_stage:'application_sent',
           review_status:'pending',review_note:''}:null},
        {id:'manual_m',name:'Микрозайм МФО',category:'МФО',payout_rub:900,
         hold_days:14,stage:mfoApproved?'in_progress':'assigned',
         target_action:'Оформить',can_apply:mfoApproved,
         unavailable_reason:mfoApproved?'':'mfo_request',
         requires_request:true,mfo_approved:mfoApproved,
         lead_stages:['application_sent','loan_issued'],
         referral_url:mfoApproved?'https://bank.test/mfo':'',
         latest_event:pendingMfo?{id:'evt_b',kind:'mfo_request',lead_stage:'',
           review_status:'pending',review_note:''}:null}
      ]};
    if(route==='/mvp/submit'){
      const payload=JSON.parse(opts.body);window.__stage7Calls.push(payload);
      if(payload.kind==='mfo_request')pendingMfo=true;
      else pendingStage=true;
      data={created:true,event:{id:'evt_test',kind:payload.kind,review_status:'pending'}};
    }
    if(route==='/invitations/referral')data={code:'ref_abcdefgh123456'};
    if(data!==undefined)return Promise.resolve(new Response(JSON.stringify(data),{
      status:200,headers:{'Content-Type':'application/json'}}));
    return fetchOriginal(url,opts);
  };
})()"""

ADMIN_BOOT = BOOTSTRAP.replace(
    "if(path==='/admin/mvp/offer') {",
    """if(path==='/admin/mvp/events') {
      data={events:[{id:'evt_123456789012345678901234',user_id:881032,
        display_id:'L-000113',offer_id:'manual_123',offer_name:'Дебетовая карта',
        kind:'stage',lead_stage:'application_sent',proof_url:'https://example.test/proof',
        has_screenshot:false,review_status:'pending',review_note:''}]};
    }
    if(path==='/admin/mvp/review-event'){
      window.__reviewStage7=JSON.parse(opts.body);data={changed:true,review_status:'approved'};
    }
    if(path==='/admin/mvp/offer') {"""
)


class Stage7BrowserTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(("127.0.0.1",0),BrowserHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_lead_stage_and_mfo_request_mobile(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for width in (320,390):
                    with self.subTest(width=width):
                        page=browser.new_page(viewport={"width":width,"height":844})
                        errors=[]
                        page.on("pageerror",lambda e:errors.append(str(e)))
                        page.add_init_script(LEAD_BOOT)
                        page.goto(self.base+"/partners/#tgWebAppData=stage7")
                        page.locator("#kpi-total").get_by_text("2",exact=True).wait_for()
                        page.locator('#participant-nav [data-view="offers"]').click()
                        cards=page.locator(".participant-offers .offer-item")
                        self.assertEqual(cards.count(),2)
                        cards.first.locator(".participant-offer-detail-button").click()
                        details=page.locator("#participant-offer-dialog .participant-offer-details")
                        self.assertEqual(details.locator(".participant-offer-detail").count(),3)
                        self.assertEqual(details.locator(".participant-offer-target").count(),1)
                        self.assertTrue(page.locator(".participant-offer-start").is_visible())
                        guide=page.locator("#participant-offer-dialog .participant-offer-workflow")
                        gap=page.evaluate("""() => {
                          const guide=document.querySelector('.participant-offer-workflow').getBoundingClientRect();
                          const start=document.querySelector('.participant-offer-start').getBoundingClientRect();
                          return start.top-guide.bottom;
                        }""")
                        self.assertGreaterEqual(gap,18)
                        self.assertEqual(guide.locator("li").count(),4)
                        self.assertEqual(guide.locator("li strong").all_inner_texts(),
                            ["Изучите условия","Выполните действие",
                             "Отправьте подтверждение","Дождитесь решения"])
                        self.assertIn("Порядок выполнения",guide.inner_text())
                        form=page.locator(".participant-offer-report-form")
                        form.wait_for(state="visible")
                        self.assertEqual(form.locator("select option").count(),1)
                        self.assertEqual(form.locator("select").input_value(),"application_sent")
                        self.assertEqual(form.locator('input[type="url"]').count(),0)
                        raw=io.BytesIO()
                        Image.new("RGB",(180,90),(20,80,130)).save(raw,format="PNG")
                        form.locator('input[type="file"]').set_input_files({
                            "name":"proof.png","mimeType":"image/png","buffer":raw.getvalue()})
                        form.locator('button[type="submit"]').click()
                        page.locator("#participant-offer-dialog").wait_for(state="hidden")
                        cards.last.locator(".participant-offer-detail-button").click()
                        mfo_guide=page.locator("#participant-offer-dialog .participant-offer-workflow")
                        self.assertEqual(mfo_guide.locator("li").nth(1).locator("strong").inner_text(),
                                         "Запросите доступ")
                        self.assertTrue(page.locator(".participant-offer-request").is_visible())
                        self.assertFalse(page.locator(".participant-offer-unavailable").is_enabled())
                        page.locator(".participant-offer-request").click()
                        page.locator("#participant-offer-dialog").wait_for(state="hidden")
                        actions=page.evaluate("window.__stage7Calls")
                        self.assertEqual([item["kind"] for item in actions],["stage","mfo_request"])
                        self.assertEqual(actions[0]["lead_stage"],"application_sent")
                        self.assertEqual(actions[0]["file"]["name"],"proof.png")
                        self.assertTrue(actions[0]["file"]["data"].startswith("iVBOR"))
                        self.assertEqual(page.evaluate("document.documentElement.scrollWidth"),width)
                        self.assertFalse(errors,errors)
                        page.close()
            finally:
                browser.close()

    def test_lead_stage_delayed_submit_is_not_sent_twice(self):
        delayed = LEAD_BOOT.replace(
            "if(data!==undefined)return Promise.resolve(new Response(JSON.stringify(data),{",
            "if(data!==undefined)return new Promise(resolve=>setTimeout(()=>resolve(new Response(JSON.stringify(data),{"
        ).replace(
            "status:200,headers:{'Content-Type':'application/json'}}));",
            "status:200,headers:{'Content-Type':'application/json'}})),route==='/mvp/submit'?500:0));"
        )
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={"width":320,"height":844})
                page.add_init_script(delayed)
                page.goto(self.base+"/partners/#tgWebAppData=stage9")
                page.locator("#kpi-total").get_by_text("2",exact=True).wait_for()
                page.locator('#participant-nav [data-view="offers"]').click()
                page.locator(".participant-offers .offer-item").first.locator(".participant-offer-detail-button").click()
                form=page.locator(".participant-offer-report-form")
                form.locator('input[type="file"]').set_input_files({
                    "name":"proof.txt","mimeType":"text/plain","buffer":b"test proof"})
                form.locator('button[type="submit"]').click()
                self.assertTrue(form.locator('button[type="submit"]').is_disabled())
                self.assertEqual(form.locator('button[type="submit"]').get_attribute("aria-busy"),"true")
                page.evaluate("""() => document.querySelector('.participant-offer-report-form')
                  .dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))""")
                page.locator("#participant-offer-dialog").wait_for(state="hidden")
                self.assertEqual(len(page.evaluate("window.__stage7Calls")),1)
                page.close()
            finally:
                browser.close()

    def test_admin_review_delayed_action_disables_sibling_controls(self):
        delayed=ADMIN_BOOT.replace(
            "if(path==='/admin/mvp/review-event'){",
            "if(path==='/admin/mvp/review-event'){window.__stage9ReviewCalls=(window.__stage9ReviewCalls||0)+1;"
        ).replace(
            "if(data!==undefined)return Promise.resolve(new Response(JSON.stringify(data),",
            "if(data!==undefined)return new Promise(resolve=>setTimeout(()=>resolve(new Response(JSON.stringify(data),"
        ).replace(
            "{status:200,headers:{'Content-Type':'application/json'}}));",
            "{status:200,headers:{'Content-Type':'application/json'}})),path==='/admin/mvp/review-event'?500:0));"
        )
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={"width":390,"height":844})
                page.add_init_script(delayed)
                page.goto(self.base+"/partners/admin/#tgWebAppData=stage9&role=owner")
                page.locator("#admin-app").wait_for(state="visible")
                page.locator('[data-section="people"]').click()
                page.locator('[data-subtab="offer_reviews"]').click()
                group=page.locator(".admin-offer-event-card .admin-offer-event-actions").first
                group.wait_for(state="visible")
                page.on("dialog",lambda dialog:dialog.accept())
                group.get_by_role("button",name="Подтвердить").click()
                self.assertTrue(group.get_by_role("button",name="Отклонить").is_disabled())
                self.assertEqual(group.locator('button[aria-busy="true"]').count(),1)
                page.evaluate("""() => document.querySelector('.admin-offer-event-actions button').click()""")
                page.wait_for_function("window.__stage9ReviewCalls===1")
                page.wait_for_function("!document.querySelector('.admin-offer-event-actions button')?.hasAttribute('aria-busy')")
                self.assertEqual(page.evaluate("window.__stage9ReviewCalls"),1)
                page.close()
            finally:
                browser.close()

    def test_admin_offer_review_tab_mobile(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={"width":320,"height":844})
                errors=[]
                page.on("pageerror",lambda e:errors.append(str(e)))
                page.add_init_script(ADMIN_BOOT)
                page.goto(self.base+"/partners/admin/#tgWebAppData=stage7&role=owner")
                page.locator("#admin-app").wait_for(state="visible")
                page.locator('[data-section="people"]').click()
                page.locator('[data-subtab="offer_reviews"]').click()
                page.locator(".admin-offer-event-card").first.wait_for()
                self.assertIn("L-000113",page.locator(".admin-offer-event-card").first.inner_text())
                self.assertEqual(page.locator(".admin-offer-event-card .status-source[data-source='review']").first.get_attribute("data-status"),"pending")
                page.on("dialog",lambda dialog:dialog.accept())
                page.locator(".admin-offer-event-card").get_by_role("button",name="Подтвердить").click()
                page.wait_for_function("Boolean(window.__reviewStage7)")
                self.assertEqual(page.evaluate("window.__reviewStage7.decision"),"approve")
                self.assertEqual(page.evaluate("document.documentElement.scrollWidth"),320)
                self.assertFalse(errors,errors)
                page.close()
            finally:
                browser.close()


if __name__=="__main__":
    unittest.main()
