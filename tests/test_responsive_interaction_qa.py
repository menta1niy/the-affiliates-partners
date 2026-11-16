"""Stage 6: UI-only responsive, accessibility and Telegram WebView simulation."""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler
from tests.test_admin_redesign_browser import BOOTSTRAP
from tests.test_participant_redesign_browser import FIXTURE


TELEGRAM_MOCK = r"""(() => {
  const events = {};
  window.__tgEvents = events;
  window.Telegram = {WebApp: {
    initData: 'ui-fixture',
    safeAreaInset:{top:48,left:9,right:9,bottom:26},
    contentSafeAreaInset:{top:56,left:13,right:13,bottom:34},
    isFullscreen:true,
    ready(){},expand(){},disableVerticalSwipes(){},
    setHeaderColor(){},setBackgroundColor(){},setBottomBarColor(){},
    onEvent(event,fn){events[event]=fn;},
    requestFullscreen(){},
  }};
})()"""


class ResponsiveInteractionQA(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def open_page(self, browser, admin=False, width=390, viewport_height=844, reduced_motion=False):
        page = browser.new_page(
            viewport={"width": width, "height": viewport_height},
            reduced_motion="reduce" if reduced_motion else "no-preference",
        )
        # The real Telegram SDK overwrites window.Telegram; replace only its
        # external script in this isolated local simulation.
        page.route(
            "https://telegram.org/js/telegram-web-app.js",
            lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
        )
        page.add_init_script(TELEGRAM_MOCK)
        page.add_init_script(BOOTSTRAP if admin else FIXTURE)
        route = "/partners/admin/" if admin else "/partners/"
        page.goto(self.base + route + "#tgWebAppData=ui-fixture&state=active&role=owner")
        page.locator("#admin-app" if admin else "#account").wait_for(state="visible")
        return page

    def test_safe_area_and_content_layout_across_sizes(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for admin in (False, True):
                    for width in (320, 375, 390, 430, 768, 1024, 1440):
                        with self.subTest(admin=admin, width=width):
                            page = self.open_page(browser, admin, width)
                            values = page.evaluate("""() => {
                              const shell = document.querySelector('.shell');
                              const style = getComputedStyle(shell);
                              return {
                                scroll: document.documentElement.scrollWidth,
                                available: document.documentElement.clientWidth,
                                top: parseFloat(style.paddingTop),
                                left: parseFloat(style.paddingLeft),
                                right: parseFloat(style.paddingRight),
                                bottom: parseFloat(style.paddingBottom),
                              };
                            }""")
                            self.assertLessEqual(values["scroll"], values["available"] + 1, values)
                            self.assertGreaterEqual(values["top"], 56, values)
                            self.assertGreaterEqual(values["left"], 13, values)
                            self.assertGreaterEqual(values["right"], 13, values)
                            self.assertGreaterEqual(values["bottom"], 34, values)
                            page.close()
            finally:
                browser.close()

    def test_short_viewport_dialog_and_keyboard_simulation(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = self.open_page(browser, admin=True, width=390, viewport_height=540)
                page.locator('[data-tab="users"]').click()
                page.locator("#users-list").get_by_role("button", name="Карточка").first.click()
                dialog = page.locator("#participant-detail")
                dialog.wait_for(state="visible")
                dims = dialog.evaluate("""node => ({
                  top:node.getBoundingClientRect().top,
                  bottom:node.getBoundingClientRect().bottom,
                  height:node.getBoundingClientRect().height,
                  viewport:window.innerHeight
                })""")
                self.assertGreaterEqual(dims["top"], -1, dims)
                self.assertLessEqual(dims["bottom"], dims["viewport"] + 1, dims)
                dialog.get_by_role("button", name="Сохранить статус").wait_for()
                dialog.locator('input[aria-label^="Комментарий к офферу"]').fill("Тест комментария")
                self.assertEqual(
                    dialog.locator('input[aria-label^="Комментарий к офферу"]').input_value(),
                    "Тест комментария",
                )
                # Simulate the available viewport shrinking after the keyboard
                # appears while the modal and its focused input are still open.
                page.set_viewport_size({"width":390,"height":410})
                bounds = dialog.evaluate("""node => ({
                    top:node.getBoundingClientRect().top,
                    bottom:node.getBoundingClientRect().bottom,
                    scrollHeight:node.scrollHeight,
                    clientHeight:node.clientHeight,
                    viewport:window.innerHeight,
                })""")
                self.assertGreaterEqual(bounds["top"], -1, bounds)
                self.assertLessEqual(bounds["bottom"], bounds["viewport"]+1, bounds)
                self.assertGreater(bounds["scrollHeight"], bounds["clientHeight"], bounds)
                self.assertTrue(dialog.get_by_role("button",name="Закрыть").count())
                page.close()
            finally:
                browser.close()

    def test_telegram_safe_area_event_updates_padding(self):
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                page=self.open_page(browser,admin=True,width=390)
                result=page.evaluate("""() => {
                    window.Telegram.WebApp.contentSafeAreaInset.top=83;
                    window.Telegram.WebApp.contentSafeAreaInset.bottom=61;
                    window.__tgEvents.contentSafeAreaChanged();
                    const shell=getComputedStyle(document.querySelector('.shell'));
                    return {top:parseFloat(shell.paddingTop),bottom:parseFloat(shell.paddingBottom)};
                }""")
                self.assertGreaterEqual(result["top"],83,result)
                self.assertGreaterEqual(result["bottom"],61,result)
                page.close()
            finally:
                browser.close()

    def test_reduced_motion_focus_and_navigation(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for admin in (False, True):
                    page = self.open_page(browser, admin, reduced_motion=True)
                    target = page.locator("#reload" if admin else "#hero-cta")
                    target.focus()
                    style = target.evaluate("""node => {
                      const css=getComputedStyle(node);
                      return {outline:css.outlineStyle,duration:css.transitionDuration};
                    }""")
                    self.assertNotEqual(style["outline"], "none")
                    self.assertEqual(style["duration"], "0s")
                    page.close()
            finally:
                browser.close()
