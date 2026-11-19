"""Stage 4: participant visual layout with synthetic frontend-only API payloads."""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler


FIXTURE = r"""(() => {
  const params = new URLSearchParams(location.hash.slice(1));
  const state = params.get('state') || 'active';
  const overviewMode = params.get('overview') || 'normal';
  let overviewAttempts = 0;
  const initial = window.fetch.bind(window);
  window.fetch = (url, options) => {
    const endpoint = String(url).replace('/partners/api', '');
    if(endpoint === '/mvp/overview') {
      overviewAttempts++;
      if(overviewMode === 'error-once' && overviewAttempts === 1) {
        return Promise.resolve(new Response(JSON.stringify({error:'Temporary error'}),{
          status:503,headers:{'Content-Type':'application/json'}
        }));
      }
      if(overviewMode === 'empty') {
        return Promise.resolve(new Response(JSON.stringify({statistics:{total:0},offers:[]}),{
          status:200,headers:{'Content-Type':'application/json'}
        }));
      }
    }
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
                        self.assertFalse(page.locator("#participant-access-summary").is_visible())
                        self.assertEqual(page.locator("#participant-next-title").inner_text(),"Продолжить работу")
                        self.assertTrue(page.locator(".participant-stats-disclaimer").is_visible())
                        self.assertFalse(page.locator(".participant-stats-disclaimer p").is_visible())
                        page.locator(".participant-stats-disclaimer summary").click()
                        self.assertIn("не означает начисление",page.locator(".participant-stats-disclaimer").inner_text())
                        self.assertEqual(page.locator("#kpi-total").inner_text(), "4")
                        self.assertEqual(page.locator("#kpi-in-progress").inner_text(), "1")
                        self.assertEqual(page.locator("#kpi-submitted").inner_text(), "1")
                        self.assertEqual(page.locator("#kpi-completed").inner_text(), "1")
                        self.assertLess(
                            page.locator("#participant-kpis .metric").first.bounding_box()["height"], 110
                        )
                        page.locator('#participant-nav [data-view="offers"]').click()
                        self.assertTrue(page.locator("#participant-offers-view").is_visible())
                        help_panel = page.locator(".participant-help")
                        help_panel.locator("summary").click()
                        self.assertIn("не подтверждение банковского начисления",help_panel.inner_text())
                        page.locator("#offers .offer-item").first.wait_for()
                        self.assertEqual(page.locator("#offers .offer-item").count(), 4)
                        self.assertIn("900 ₽", page.locator("#offers").inner_text())
                        self.assertIn("Назначено", page.locator("#offers").inner_text())
                        first = page.locator("#offers .offer-item").first
                        self.assertEqual(first.locator(".participant-offer-next").inner_text(), "Прочитать условия")
                        self.assertEqual(first.locator("h3").evaluate("el=>getComputedStyle(el).webkitLineClamp"),"2")
                        measurements=first.evaluate("""node=>{
                          const css=getComputedStyle(node);
                          const button=node.querySelector('.participant-offer-detail-button');
                          const rect=button.getBoundingClientRect();
                          return {padding:parseFloat(css.paddingTop),buttonHeight:rect.height,
                            summaryColumns:getComputedStyle(node.querySelector('.participant-offer-summary')).gridTemplateColumns};
                        }""")
                        self.assertLessEqual(measurements["padding"],17)
                        self.assertGreaterEqual(measurements["buttonHeight"],44)
                        self.assertEqual(len(measurements["summaryColumns"].split()),2)
                        self.assertEqual(first.locator(".participant-offer-status .participant-status-symbol").count(),1)
                        self.assertEqual(first.locator(".participant-offer-instructions").count(), 0)
                        first.locator(".participant-offer-detail-button").click()
                        dialog = page.locator("#participant-offer-dialog")
                        self.assertTrue(dialog.is_visible())
                        self.assertIn("10 дн.", dialog.inner_text())
                        self.assertIn("Проверить документы", dialog.inner_text())
                        self.assertIn("Следующий шаг", dialog.inner_text())
                        self.assertIn("Изучите условия оффера", dialog.locator(".participant-offer-full-next").inner_text())
                        self.assertEqual(
                            dialog.locator(".participant-offer-link").get_attribute("href"),
                            "https://example.org/offer",
                        )
                        dialog.get_by_role("button", name="Закрыть подробности").click()
                        self.assertFalse(dialog.is_visible())
                        page.locator('[data-offer-filter="submitted"]').click()
                        self.assertEqual(page.locator("#offers .offer-item").count(), 1)
                        self.assertIn("Третье предложение", page.locator("#offers").inner_text())
                        self.assertIn("Ожидает проверки",page.locator("#offers .participant-offer-next").inner_text())
                        self.assertEqual(page.locator("#offers .participant-offer-status").get_attribute("data-status"),"submitted")
                        page.locator('[data-offer-filter="completed"]').click()
                        self.assertIn("Отмечено администратором",page.locator("#offers .participant-offer-next").inner_text())
                        page.locator("#offers .participant-offer-detail-button").first.click()
                        self.assertIn("не подтверждение банковского начисления",page.locator(".participant-offer-full-next").inner_text())
                        page.locator("#participant-offer-close").click()
                        page.locator('[data-offer-filter="all"]').click()
                        page.locator("#offer-sort").select_option("payout_desc")
                        self.assertIn("Вторая карта",page.locator("#offers .offer-item").first.inner_text())
                        toolbar = page.locator("#offer-controls")
                        toolbar_metrics = toolbar.evaluate("""node=>{
                          const filter=node.querySelector('.participant-offer-filter');
                          const sort=node.querySelector('#offer-sort');
                          const r=node.getBoundingClientRect(), f=filter.getBoundingClientRect(), s=sort.getBoundingClientRect();
                          return {height:r.height,filterScrollable:filter.scrollWidth>filter.clientWidth,
                            sortHeight:s.height,sameRow:Math.abs(f.top-s.top)<4,
                            sortLabel:sort.getAttribute('aria-label'),
                            activeSort:sort.parentElement.classList.contains('is-custom-sort')};
                        }""")
                        self.assertLessEqual(toolbar_metrics["height"],54)
                        self.assertTrue(toolbar_metrics["sameRow"])
                        self.assertGreaterEqual(toolbar_metrics["sortHeight"],44)
                        self.assertEqual(toolbar_metrics["sortLabel"],"Сортировка офферов")
                        self.assertTrue(toolbar_metrics["activeSort"])
                        if width <= 430:
                            self.assertTrue(toolbar_metrics["filterScrollable"])
                        page.locator('#participant-nav [data-view="profile"]').click()
                        profile = page.locator("#profile-section")
                        self.assertTrue(profile.is_visible())
                        self.assertIn("Участник",profile.inner_text())
                        self.assertFalse(profile.locator("#profile-id").is_visible())
                        profile.locator(".participant-technical summary").click()
                        self.assertTrue(profile.locator("#profile-id").is_visible())
                        self.assertEqual(profile.locator("#profile-id").inner_text(),"881031")
                        self.assertIn("ПРИГЛАШЕНИЕ",profile.inner_text())
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

    def test_profile_motion_preferences(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for reduced in (False, True):
                    with self.subTest(reduced_motion=reduced):
                        page = browser.new_page(
                            viewport={"width":390,"height":844},
                            reduced_motion="reduce" if reduced else "no-preference",
                        )
                        page.add_init_script(FIXTURE)
                        page.goto(self.base + "/partners/#tgWebAppData=ui-fixture&state=active")
                        page.locator("#participant-nav").wait_for(state="visible")
                        page.locator('#participant-nav [data-view="profile"]').click()
                        values = page.evaluate("""() => ({
                          animation: getComputedStyle(document.querySelector('#participant-profile-view')).animationName,
                          font: parseFloat(getComputedStyle(document.querySelector('#profile-username')).fontSize),
                          summary: document.querySelector('.participant-technical summary').getBoundingClientRect().height,
                          overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
                        })""")
                        self.assertEqual(values["animation"] == "none",reduced)
                        self.assertGreaterEqual(values["font"],14)
                        self.assertGreaterEqual(values["summary"],44)
                        self.assertFalse(values["overflow"])
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
                            self.assertIn("После одобрения",page.locator("#register-panel").inner_text())
                        else:
                            self.assertTrue(page.locator("#pending-panel").is_visible())
                            self.assertFalse(page.locator("#register-panel").is_visible())
                            self.assertIn("Срок рассмотрения не установлен",page.locator("#pending-panel").inner_text())
                            page.locator("#pending-refresh").click()
                            self.assertTrue(page.locator("#pending-panel").is_visible())
                        page.close()
            finally:
                browser.close()

    def test_empty_offers_and_recoverable_error(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for mode in ("empty", "error-once"):
                    with self.subTest(mode=mode):
                        page = browser.new_page(viewport={"width":390,"height":844})
                        page.add_init_script(FIXTURE)
                        page.goto(self.base + f"/partners/#tgWebAppData=ui-fixture&state=active&overview={mode}")
                        page.locator('#participant-nav [data-view="offers"]').click()
                        if mode == "empty":
                            page.locator(".participant-offer-state-empty").wait_for()
                            self.assertIn("не назначил",page.locator("#offers").inner_text())
                            self.assertFalse(page.locator("#offer-controls").is_visible())
                            self.assertEqual(page.locator("#kpi-total").inner_text(),"0")
                        else:
                            page.locator(".participant-offer-state-error").wait_for()
                            self.assertFalse(page.locator("#offer-controls").is_visible())
                            self.assertEqual(page.locator("#kpi-total").inner_text(),"—")
                            page.get_by_role("button",name="Повторить попытку").click()
                            page.locator("#offers .offer-item").first.wait_for()
                            self.assertEqual(page.locator("#offers .offer-item").count(),4)
                            self.assertTrue(page.locator("#offer-controls").is_visible())
                        self.assertFalse(page.locator(".participant-offer-skeletons").count())
                        page.close()
            finally:
                browser.close()
