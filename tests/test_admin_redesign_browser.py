"""Local stage-5 visual, role and mobile tests for the existing admin API UI."""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler


BOOTSTRAP = r"""(() => {
  const params = new URLSearchParams(location.hash.slice(1));
  const role = params.get('role') || 'owner';
  const actor = {id:758398804,first_name:'Александр',role,status:'active'};
  const people = [
    {id:881031,internal_id:112,first_name:'Тестовый участник с длинным именем',
     username:'very_long_telegram_username_for_mobile_testing',role:'lead',status:'pending',
     source:'agency',agency_id:758398804,manager_id:758398804},
    {id:881032,internal_id:113,first_name:'Второй',username:'second_participant',
     role:'lead',status:'active',source:'agency',agency_id:758398804,manager_id:758398804}
  ];
  const sampleOffer = {id:'manual_a',name:'Дебетовая карта Альфа Банк — длинное наименование',
    category:'Дебетовые карты',payout_rub:3000,hold_days:14,
    target_action:'Активировать карту',active:true,stage:'assigned'};
  const baseFetch=window.fetch.bind(window);
  window.fetch = (url, opts) => {
    const path=String(url).replace('/partners/api','');
    let data;
    if(path==='/session') data={source:'telegram',role,status:'active',user:actor};
    if(path==='/admin/dashboard') data={counts:{total:2,pending:1,active:1,blocked:0},
      users:people,pending:people.slice(0,1),invites:[]};
    if(path==='/admin/users') {
      const body=JSON.parse(opts?.body||'{}');
      const filtered=body.status==='pending'?people.slice(0,1):people;
      data={users:filtered,total:filtered.length,has_next:false};
    }
    if(path==='/admin/audit') data={events:[]};
    if(path==='/admin/mvp/catalog') data={offers:[sampleOffer]};
    if(path==='/admin/participant') data={user:people[0],
      manual:{statistics:{total:1,in_progress:0,completed:0},offers:[sampleOffer]},audit:[]};
    if(data!==undefined)return Promise.resolve(new Response(JSON.stringify(data),
      {status:200,headers:{'Content-Type':'application/json'}}));
    return baseFetch(url,opts);
  };
})()"""


class AdminRedesignBrowserTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),BrowserHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def open_admin(self,browser,width,role='owner'):
        page=browser.new_page(viewport={'width':width,'height':844})
        page.add_init_script(BOOTSTRAP)
        page.goto(self.base+f'/partners/admin/#tgWebAppData=visual-fixture&role={role}')
        page.locator('#admin-app').wait_for(state='visible')
        return page

    def test_control_center_mobile_desktop_sections_and_navigation(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for width in (320,375,390,430,768,1024,1440):
                    with self.subTest(width=width):
                        page=self.open_admin(browser,width)
                        errors=[]
                        page.on('pageerror',lambda e:errors.append(str(e)))
                        self.assertEqual(page.locator('#count-total').inner_text(),'2')
                        self.assertEqual(page.locator('#count-pending').inner_text(),'1')
                        self.assertIn('УПРАВЛЯЙ.',page.locator('#admin-title').inner_text())
                        self.assertTrue(page.locator('[data-panel="pending"]').is_visible())
                        page.locator('[data-tab="users"]').click()
                        self.assertTrue(page.locator('[data-panel="users"]').is_visible())
                        page.locator('#users-list .admin-data-row').first.wait_for()
                        self.assertEqual(page.locator('#users-list .admin-data-row').count(),2)
                        self.assertEqual(page.locator('[data-tab="users"]').get_attribute('aria-selected'),'true')
                        self.assertFalse(errors,errors)
                        if width<=430:
                            measured=page.evaluate('''() => ({
                              viewport:document.documentElement.clientWidth,
                              scroll:document.documentElement.scrollWidth,
                              tableDisplay:getComputedStyle(document.querySelector('#users-list table')).display,
                              sidebarDisplay:getComputedStyle(document.querySelector('.admin-sidebar')).display
                            })''')
                            self.assertLessEqual(measured['scroll'],measured['viewport']+1,measured)
                            self.assertEqual(measured['tableDisplay'],'block')
                        page.close()
            finally:
                browser.close()

    def test_catalog_owner_can_edit_admin_read_only_and_profile_assignments(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for role in ('owner','admin'):
                    with self.subTest(role=role):
                        page=self.open_admin(browser,390,role)
                        page.get_by_role('button',name='Каталог офферов').click()
                        dialog=page.locator('#mvp-catalog-dialog')
                        dialog.wait_for(state='visible')
                        dialog.get_by_text('Дебетовая карта Альфа Банк').first.wait_for()
                        self.assertEqual(dialog.locator('.admin-catalog-card').count(),1)
                        self.assertEqual(dialog.locator('form.admin-catalog-form').count(),1 if role=='owner' else 0)
                        dialog.get_by_role('button',name='Закрыть').click()
                        page.locator('[data-tab="users"]').click()
                        page.locator('#users-list').get_by_role('button',name='Карточка').first.click()
                        profile=page.locator('#participant-detail')
                        self.assertTrue(profile.is_visible())
                        profile.get_by_role('button',name='Сохранить статус').wait_for()
                        profile.get_by_role('button',name='Убрать оффер').wait_for()
                        profile.get_by_role('button',name='Закрыть').click()
                        page.close()
            finally:
                browser.close()

    def test_unauthenticated_navigation_is_not_exposed(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={'width':390,'height':844})
                page.goto(self.base+'/partners/admin/')
                page.locator('#no-access').wait_for(state='visible')
                self.assertFalse(page.locator('.admin-sidebar').is_visible())
                self.assertFalse(page.locator('#admin-primary-action').is_visible())
                self.assertFalse(page.locator('#admin-app').is_visible())
            finally:
                browser.close()
