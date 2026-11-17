"""Stage 4: participant visual layout with synthetic frontend-only API payloads."""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler


FIXTURE = r"""(() => {
  const params = new URLSearchParams(location.hash.slice(1));
  const state = params.get('state') || 'active';
  const initial = window.fetch.bind(window);
  window.fetch = (url, options) => {
    const endpoint = String(url).replace('/partners/api', '');
    const user = {
      id: 881031, internal_id: 123, first_name: 'Александр',
      username: 'long_telegram_username_for_testing', role: 'lead', status: state
    };
    const data = {
      '/session': {
        source:'telegram',user,role:'lead',status:state,
        registered:state !== 'unregistered',open_registration:true
      },
      '/mvp/overview': {
        statistics:{total:4,in_progress:2,completed:1},
        offers:[
          {id:'manual_a',name:'Альфа Банк — очень длинное название банковского предложения',
           category:'Дебетовая карта',payout_rub:900,hold_days:10,stage:'assigned',
           target_action:'Активировать карту',instructions:'Шаг 1. Откройте предложение\nШаг 2. Пройдите условия',
           note:'Проверить документы',referral_url:'https://example.org/offer'},
          {id:'manual_b',name:'Вторая карта',category:'Карты',payout_rub:3000,hold_days:14,
           stage:'in_progress',target_action:'Покупка',instructions:'Условия участия'},
          {id:'manual_c',name:'Третье предложение',category:'Банк',payout_rub:1200,hold_days:5,
           stage:'submitted',target_action:'Оформление'},
          {id:'manual_d',name:'Завершённое',category:'Карта',payout_rub:500,hold_days:7,
           stage:'completed',target_action:'Получение карты'}
        ]
      }
    }[endpoint];
    if (data !== undefined) return Promise.resolve(new Response(
      JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}}
    ));
    if (endpoint === '/invitations/referral') return Promise.resolve(new Response(
      JSON.stringify({error:'Unavailable'}),{status:403,headers:{'Content-Type':'application/json'}}
    ));
    return initial(url,options);
  };
})()"""


class ParticipantRedesignBrowserTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_active_cards_kpis_navigation_and_mobile_layout(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (320, 375, 390, 430, 768, 1440):
                    with self.subTest(width=width):
                        page = browser.new_page(viewport={"width": width, "height": 844})
                        errors = []
                        page.on("pageerror", lambda exc: errors.append(str(exc)))
                        page.add_init_script(FIXTURE)
                        page.goto(self.base + "/partners/#tgWebAppData=ui-fixture&state=active")
                        page.locator("#kpi-total").get_by_text("4", exact=True).wait_for()
                        self.assertTrue(page.locator("#stats-section").is_visible())
                        self.assertTrue(page.locator("#participant-nav").is_visible())
                        self.assertEqual(page.locator("#kpi-total").inner_text(), "4")
                        self.assertEqual(page.locator("#kpi-in-progress").inner_text(), "1")
                        self.assertEqual(page.locator("#kpi-submitted").inner_text(), "1")
                        self.assertEqual(page.locator("#kpi-completed").inner_text(), "1")
                        page.locator('#participant-nav [data-view="offers"]').click()
                        self.assertTrue(page.locator("#participant-offers-view").is_visible())
                        page.locator("#offers .offer-item").first.wait_for()
                        self.assertEqual(page.locator("#offers .offer-item").count(), 4)
                        self.assertIn("900 ₽", page.locator("#offers").inner_text())
                        self.assertIn("Холд: 10", page.locator("#offers").inner_text())
                        self.assertIn("Назначено", page.locator("#offers").inner_text())
                        first = page.locator("#offers .offer-item").first
                        self.assertFalse(first.locator(".participant-offer-instructions").is_visible())
                        first.locator("summary").click()
                        self.assertTrue(first.locator(".participant-offer-instructions").is_visible())
                        self.assertIn("Проверить документы", first.inner_text())
                        self.assertEqual(
                            first.locator(".participant-offer-link").get_attribute("href"),
                            "https://example.org/offer",
                        )
                        self.assertIn("@long_telegram_username", page.locator("#profile-username").inner_text())
                        self.assertFalse(errors, errors)
                        if width <= 430:
                            sizes = page.evaluate("""() => ({
                              viewport: document.documentElement.clientWidth,
                              scroll: document.documentElement.scrollWidth
                            })""")
                            self.assertLessEqual(sizes["scroll"], sizes["viewport"] + 1, sizes)
                        page.close()
            finally:
                browser.close()

    def test_pending_and_unregistered_do_not_show_offer_stats(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for state in ("pending", "unregistered"):
                    with self.subTest(state=state):
                        page = browser.new_page(viewport={"width": 390, "height": 844})
                        page.add_init_script(FIXTURE)
                        page.goto(self.base + f"/partners/#tgWebAppData=ui-fixture&state={state}")
                        page.locator("#account").wait_for(state="visible")
                        self.assertFalse(page.locator("#stats-section").is_visible())
                        self.assertFalse(page.locator("#participant-nav").is_visible())
                        self.assertFalse(page.locator("#offers .offer-item").count())
                        if state == "unregistered":
                            self.assertTrue(page.locator("#register-form").is_visible())
                            self.assertEqual(page.locator("#hero-cta").get_attribute("href"), "#register-panel")
                        page.close()
            finally:
                browser.close()
