"""Stage 1/2: Telegram viewport, safe areas and mobile dock geometry.

Synthetic Telegram session; production, user accounts and devices are untouched.
"""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler
from tests.test_profile_stage6_browser import FIXTURE


TELEGRAM = r"""(() => {
  const listeners = {};
  window.__setTelegramFullscreen = value => {
    window.Telegram.WebApp.isFullscreen = value;
    (listeners.fullscreenChanged || []).forEach(fn => fn());
  };
  window.Telegram = {WebApp: {
    initData: 'test', isFullscreen: false,
    safeAreaInset: {top: 56, right: 0, bottom: 24, left: 0},
    contentSafeAreaInset: {top: 0, right: 0, bottom: 0, left: 0},
    ready() {}, expand() {}, disableVerticalSwipes() {},
    setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
    requestFullscreen() { window.__fullscreenRequested = true; },
    onEvent(name, fn) { (listeners[name] ||= []).push(fn); },
    BackButton: {show() {}, hide() {}}
  }};
})()"""


class MobileWebviewStage1Tests(unittest.TestCase):
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

    def test_safe_areas_and_dock_at_iphone_widths(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for width in (320, 375, 390, 430):
                    with self.subTest(width=width):
                        page = browser.new_page(viewport={"width": width, "height": 844})
                        page.route("https://telegram.org/js/telegram-web-app.js", lambda route: route.fulfill(body="", content_type="application/javascript"))
                        page.add_init_script(TELEGRAM + ";\n" + FIXTURE)
                        page.goto(self.base + "/partners/#tgWebAppData=stage1")
                        page.locator("#participant-nav").wait_for(state="visible")
                        self.assertFalse(page.evaluate("Boolean(window.__fullscreenRequested)"))
                        self.assertEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                        page.locator('#participant-nav [data-view="profile"]').click()
                        page.locator("#participant-credit-save").wait_for(state="visible")
                        normal = page.evaluate("""() => {
                          const nav = document.querySelector('#participant-nav').getBoundingClientRect();
                          const root = getComputedStyle(document.querySelector('.shell'));
                          return {navBottom: innerHeight-nav.bottom, bottomPadding: parseFloat(root.paddingBottom),
                            shellTop: parseFloat(root.paddingTop), navHeight:nav.height};
                        }""")
                        self.assertGreaterEqual(normal["navBottom"], 20, normal)
                        self.assertGreaterEqual(normal["bottomPadding"], normal["navHeight"] + normal["navBottom"] + 24, normal)
                        self.assertLess(normal["shellTop"], 64, normal)  # not in forced fullscreen

                        page.evaluate("window.__setTelegramFullscreen(true)")
                        full = page.evaluate("""() => {
                          const root=document.documentElement;
                          const shell=document.querySelector('.shell');
                          return {overlay:parseFloat(getComputedStyle(root).getPropertyValue('--tg-overlay-clearance')),
                            top:parseFloat(getComputedStyle(shell).paddingTop),
                            mask:getComputedStyle(document.body,'::before').position};
                        }""")
                        self.assertGreaterEqual(full["top"], 112, full)
                        self.assertEqual(full["mask"], "fixed", full)

                        page.locator("#participant-credit-save").evaluate("el => el.scrollIntoView({block:'end'})")
                        geometry = page.evaluate("""() => ({
                          button:document.querySelector('#participant-credit-save').getBoundingClientRect().bottom,
                          dock:document.querySelector('#participant-nav').getBoundingClientRect().top
                        })""")
                        self.assertLessEqual(geometry["button"], geometry["dock"] - 12, geometry)

                        keyboard_visibility = page.evaluate("""() => {
                          document.documentElement.classList.add('tg-keyboard-open');
                          return getComputedStyle(document.querySelector('#participant-nav')).visibility;
                        }""")
                        self.assertEqual(keyboard_visibility, "hidden")
                        page.evaluate("document.documentElement.classList.remove('tg-keyboard-open')")
                        page.locator("#finance-request-amount").focus()
                        self.assertTrue(page.locator("html").evaluate("el => el.classList.contains('tg-keyboard-open')"))
                        self.assertEqual(page.locator("#participant-nav").evaluate("el => getComputedStyle(el).display"),"none")
                        self.assertTrue(page.locator(".tg-keyboard-done").is_visible())
                        page.locator(".tg-keyboard-done").click()
                        self.assertFalse(page.locator("html").evaluate("el => el.classList.contains('tg-keyboard-open')"))
                        self.assertNotEqual(page.evaluate("document.activeElement.id"),"finance-request-amount")
                        page.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
