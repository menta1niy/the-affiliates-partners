"""Stage 3: presentational component contracts in local Chromium only."""

import threading
import unittest
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler


class CoreComponentsBrowserTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_shared_buttons_inputs_and_statuses(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for path in ("/partners/", "/partners/admin/"):
                    for width in (320, 390, 1440):
                        with self.subTest(path=path, width=width):
                            page = browser.new_page(viewport={"width": width, "height": 844})
                            page.goto(self.origin + path)
                            page.evaluate("""() => {
                                // Test semantics; do not add fake data to actual app.
                                let fixture = document.createElement('div');
                                fixture.id = 'component-fixture';
                                fixture.style.cssText = 'position:absolute;left:8px;top:8px;width:240px';
                                fixture.innerHTML = '<button class="btn primary">Primary</button>'
                                  + '<button class="btn danger">Danger</button>'
                                  + '<button class="btn ghost" disabled>Disabled</button>'
                                  + '<input aria-label="Test field" placeholder="Search">'
                                  + '<span class="pill" data-status="pending">Ожидает</span>';
                                document.body.append(fixture);
                            }""")
                            values = page.evaluate("""() => {
                                const css = selector => getComputedStyle(document.querySelector('#component-fixture ' + selector));
                                return {
                                  primary: css('.primary').backgroundColor,
                                  ink: css('.primary').color,
                                  primaryHeight: Number.parseFloat(css('.primary').minHeight),
                                  dangerStyle: css('.danger').borderTopStyle,
                                  disabledCursor: css(':disabled').cursor,
                                  inputHeight: Number.parseFloat(css('input').minHeight),
                                  pillStyle: css('.pill').borderTopStyle
                                };
                            }""")
                            self.assertEqual(values["primary"], "rgb(228, 163, 74)")
                            self.assertEqual(values["ink"], "rgb(24, 17, 10)")
                            self.assertGreaterEqual(values["primaryHeight"], 44)
                            self.assertGreaterEqual(values["inputHeight"], 44)
                            self.assertEqual(values["dangerStyle"], "dashed")
                            self.assertEqual(values["disabledCursor"], "not-allowed")
                            self.assertEqual(values["pillStyle"], "dashed")
                            page.close()
            finally:
                browser.close()

    def test_admin_tabs_and_dynamic_offer_dialog_share_theme(self):
        # UI-only response fixtures: no authenticated production data or writes.
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.add_init_script("""(() => {
                    const original = window.fetch.bind(window);
                    window.fetch = (url, options) => {
                      const endpoint = String(url).replace('/partners/api', '');
                      const payload = {
                        '/session': {role:'owner',status:'active',user:{id:758398804,role:'owner'}},
                        '/admin/dashboard': {counts:{total:0,pending:0,active:0,blocked:0},users:[],pending:[],invites:[]},
                        '/admin/users': {users:[],total:0,has_next:false},
                        '/admin/mvp/catalog': {offers:[]}
                      }[endpoint];
                      if (payload !== undefined) return Promise.resolve(new Response(JSON.stringify(payload),{
                        status:200,headers:{'Content-Type':'application/json'}
                      }));
                      return original(url, options);
                    };
                })();""")
                page.goto(self.origin + "/partners/admin/#tgWebAppData=ui-fixture")
                page.locator("#admin-app").wait_for(state="visible")
                page.locator('[data-tab="users"]').click()
                self.assertEqual(
                    page.locator('[data-tab="users"]').get_attribute("aria-selected"), "true"
                )
                self.assertEqual(
                    page.locator('[data-tab="pending"]').get_attribute("aria-selected"), "false"
                )
                page.get_by_role("button", name="Каталог офферов").click()
                dialog = page.locator("#mvp-catalog-dialog")
                dialog.wait_for(state="visible")
                values = dialog.evaluate("""el => ({
                    background: getComputedStyle(el).backgroundColor,
                    color: getComputedStyle(el).color,
                    border: getComputedStyle(el).borderTopColor,
                    submit: getComputedStyle(el.querySelector('.btn.primary')).backgroundColor,
                })""")
                self.assertEqual(values["color"], "rgb(247, 247, 245)")
                self.assertEqual(values["submit"], "rgb(228, 163, 74)")
                self.assertNotEqual(values["background"], "rgb(11, 43, 38)")
                self.assertTrue(values["border"].startswith("rgba("))
                dialog.get_by_role("button", name="Закрыть").click()
            finally:
                browser.close()
