"""Local final-stage Telegram lead UX checks with synthetic, authorized fixtures."""
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler
from tests.test_participant_redesign_browser import FIXTURE
from tests.test_responsive_interaction_qa import TELEGRAM_MOCK


class LeadFinalUXQA(unittest.TestCase):
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

    def open_lead(self, browser, width, height=844, state="active", telegram=True):
        page = browser.new_page(viewport={"width":width, "height":height})
        if telegram:
            page.route("https://telegram.org/js/telegram-web-app.js",
                       lambda route:route.fulfill(status=200,content_type="application/javascript",body=""))
            page.add_init_script(TELEGRAM_MOCK)
        page.add_init_script(FIXTURE)
        page.goto(self.base + f"/partners/#tgWebAppData=ui-fixture&state={state}")
        page.locator("#account").wait_for(state="visible")
        return page

    def test_lead_modal_safe_area_keyboard_and_navigation(self):
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                for width,height in [(320,568),(375,667),(390,844),(430,932)]:
                    with self.subTest(width=width,height=height):
                        page=self.open_lead(browser,width,height)
                        page.locator('#participant-nav [data-view="offers"]').click()
                        page.locator("#offers .offer-item").first.wait_for()
                        page.locator("#offers .participant-offer-detail-button").first.click()
                        dialog=page.locator("#participant-offer-dialog")
                        self.assertTrue(dialog.evaluate("node=>node.matches(':modal')"))
                        size=dialog.evaluate("""node=>{
                          const r=node.getBoundingClientRect();
                          const close=node.querySelector('#participant-offer-close').getBoundingClientRect();
                          return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,
                            closeTop:close.top,closeRight:close.right,viewportW:innerWidth,viewportH:innerHeight,
                            scrollHeight:node.scrollHeight,clientHeight:node.clientHeight};
                        }""")
                        self.assertGreaterEqual(size["top"],112,size)
                        self.assertLessEqual(size["bottom"],height+1,size)
                        self.assertLessEqual(size["right"],width+1,size)
                        self.assertGreaterEqual(size["closeTop"],112,size)
                        self.assertGreaterEqual(size["left"],0,size)
                        self.assertLessEqual(size["closeRight"],width+1,size)
                        self.assertGreaterEqual(dialog.locator("#participant-offer-close").bounding_box()["width"],44)
                        self.assertGreaterEqual(dialog.locator("#participant-offer-close").bounding_box()["height"],44)
                        heading=dialog.locator(".participant-offer-dialog-head").evaluate("""node=>{
                          const style=getComputedStyle(node);
                          const label=node.querySelector('.section-kicker').getBoundingClientRect();
                          const button=node.querySelector('#participant-offer-close').getBoundingClientRect();
                          return {position:style.position,background:style.backgroundColor,
                            labelTop:label.top,buttonTop:button.top,
                            headerHeight:node.getBoundingClientRect().height};
                        }""")
                        self.assertEqual(heading["position"],"relative")
                        self.assertEqual(heading["background"],"rgba(0, 0, 0, 0)")
                        self.assertLessEqual(abs(heading["labelTop"]-heading["buttonTop"]),24)
                        self.assertLessEqual(heading["headerHeight"],60)
                        if size["scrollHeight"]>size["clientHeight"]:
                            page.evaluate("""()=>{
                              const dialog=document.querySelector('#participant-offer-dialog');
                              dialog.scrollTop=dialog.scrollHeight;
                            }""")
                            dialog.evaluate("node=>node.scrollTop=0")
                        if height<=667:
                            page.set_viewport_size({"width":width,"height":410})
                            compressed=dialog.bounding_box()
                            self.assertLessEqual(compressed["y"]+compressed["height"],411,compressed)
                        page.keyboard.press("Escape")
                        self.assertFalse(dialog.is_visible())
                        page.locator('#participant-nav [data-view="profile"]').click()
                        self.assertTrue(page.locator("#profile-section").is_visible())
                        page.go_back()
                        self.assertTrue(page.locator("#participant-offers-view").is_visible())
                        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth"),1)
                        page.close()
            finally:
                browser.close()

    def test_telegram_insets_update_nav_and_registration(self):
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                page=self.open_lead(browser,390)
                page.locator("#participant-nav").wait_for(state="visible")
                initial=page.locator("#participant-nav").evaluate("node=>getComputedStyle(node).bottom")
                result=page.evaluate("""()=>{
                  Telegram.WebApp.contentSafeAreaInset.bottom=72;
                  window.__tgEvents.contentSafeAreaChanged();
                  return {bottom:getComputedStyle(document.querySelector('#participant-nav')).bottom,
                    scroll:document.documentElement.scrollWidth,
                    width:document.documentElement.clientWidth};
                }""")
                self.assertNotEqual(initial,result["bottom"])
                self.assertGreaterEqual(float(result["bottom"].replace("px","")),72)
                self.assertLessEqual(result["scroll"],result["width"]+1)
                page.close()

                pending=self.open_lead(browser,390,state="pending")
                self.assertTrue(pending.locator("#pending-panel").is_visible())
                self.assertFalse(pending.locator("#participant-nav").is_visible())
                pending.locator("#pending-refresh").click()
                self.assertTrue(pending.locator("#pending-panel").is_visible())
                pending.close()
                signup=self.open_lead(browser,320,state="unregistered")
                self.assertTrue(signup.locator("#register-form").is_visible())
                signup.locator("#consent").check()
                self.assertTrue(signup.locator("#consent").is_checked())
                self.assertLessEqual(signup.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth"),1)
                signup.close()
            finally:
                browser.close()

    def test_capture_local_design_review(self):
        """Save synthetic-only review captures; do not upload or publish them."""
        out=Path("D:/GPT/_ta-partners-releases/ux-stage6-screenshots")
        out.mkdir(parents=True,exist_ok=True)
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                for width,height in [(320,568),(390,844),(1440,900)]:
                    page=self.open_lead(browser,width,height)
                    page.locator("#kpi-total").get_by_text("4",exact=True).wait_for()
                    page.screenshot(path=str(out/f"lead-home-{width}.png"))
                    page.locator('#participant-nav [data-view="offers"]').click()
                    page.locator("#offers .offer-item").first.wait_for()
                    page.screenshot(path=str(out/f"lead-offers-{width}.png"))
                    page.locator("#offers .participant-offer-detail-button").first.click()
                    page.screenshot(path=str(out/f"lead-details-{width}.png"))
                    page.locator("#participant-offer-close").click()
                    page.locator('#participant-nav [data-view="profile"]').click()
                    page.screenshot(path=str(out/f"lead-profile-{width}.png"))
                    page.close()
            finally:
                browser.close()


if __name__=="__main__":
    unittest.main()
