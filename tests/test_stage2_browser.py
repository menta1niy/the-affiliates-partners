"""Mobile/browser smoke for lead event timeline, files, and live activity."""
import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright
from tests.test_admin_participant_browser import BrowserHandler
from tests.test_offer_workflow_stage7_browser import LEAD_BOOT


EVENT_BOOT = LEAD_BOOT.replace(
    "if(route==='/mvp/submit'){",
    """if(route==='/mvp/my-events'){
      const event={id:'evt_123456789012345678901234',offer_id:'manual_c',
        offer_name:'Дебетовая карта',kind:'stage',lead_stage:'application_sent',
        review_status:'approved',review_note:'Проверено',
        created_at:1764200000,reviewed_at:1764200200,
        has_screenshot:true,file_name:'proof.pdf',file_mime:'application/pdf'};
      data={events:[event]};
    }
    if(route==='/mvp/evidence')data={name:'proof.pdf',mime:'application/pdf',data:'aGVsbG8='};
    if(route==='/mvp/submit'){"""
).replace("hold_days:7,stage:'assigned'", "hold_days:7,is_assigned:true,stage:'assigned'")
EVENT_BOOT=EVENT_BOOT.replace(
    "data={code:'ref_abcdefgh123456'}", "data={code:'TJ7VSD'}"
)


class Stage2LeadBrowserTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(("127.0.0.1",0),BrowserHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)

    def test_offer_timeline_file_and_activity(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for width in (320,390):
                    with self.subTest(width=width):
                        page=browser.new_page(viewport={"width":width,"height":844})
                        errors=[]
                        page.on("pageerror",lambda exc:errors.append(str(exc)))
                        page.add_init_script(EVENT_BOOT)
                        page.goto(self.base+"/partners/#tgWebAppData=stage2")
                        page.locator("#kpi-total").wait_for(state="visible")
                        page.locator('#participant-nav [data-view="offers"]').click()
                        page.locator(".participant-offers .offer-item").first.locator(".participant-offer-detail-button").click()
                        timeline=page.locator(".participant-offer-timeline")
                        timeline.get_by_text("Отправил заявку",exact=True).wait_for()
                        self.assertEqual(timeline.locator(".participant-timeline-entry").count(),1)
                        timeline.get_by_role("button",name="Открыть файл: proof.pdf").click()
                        evidence=page.locator("dialog.participant-evidence-dialog")
                        evidence.wait_for(state="visible")
                        self.assertIn("proof.pdf",evidence.inner_text())
                        self.assertEqual(evidence.locator('a[download="proof.pdf"]').count(),1)
                        evidence.get_by_role("button",name="Закрыть").click()
                        page.locator("#participant-offer-close").click()
                        page.locator('#participant-nav [data-view="statistics"]').click()
                        activity=page.locator("#participant-activity-timeline")
                        activity.get_by_text("Подтверждено: Отправил заявку",exact=False).wait_for()
                        self.assertGreaterEqual(activity.locator(".participant-timeline-entry").count(),2)
                        page.locator('#participant-nav [data-view="profile"]').click()
                        page.locator("#referral-link").wait_for(state="visible")
                        self.assertEqual(
                            page.locator("#referral-link").input_value(),
                            "https://t.me/affialite_partners_bot?start=TJ7VSD")
                        self.assertTrue(page.locator("#copy-referral").is_enabled())
                        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"),width+1)
                        self.assertFalse(errors,errors)
                        page.close()
            finally:
                browser.close()
