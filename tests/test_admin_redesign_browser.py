"""Local stage-5 visual, role and mobile tests for the existing admin API UI."""

import threading
import io
import unittest
from http.server import ThreadingHTTPServer

from PIL import Image
from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler


BOOTSTRAP = r"""(() => {
  const params = new URLSearchParams(location.hash.slice(1));
  const role = params.get('role') || 'owner';
  const stage4 = params.get('stage4') === '1';
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
  const stage4Offers = [sampleOffer,
    {id:'manual_b',name:'Кредитный продукт — тест',category:'МФО',payout_rub:600,
     hold_days:7,active:true,target_action:'Оформить'},
    {id:'manual_c',name:'Отключённый оффер',category:'Дебетовые карты',
     payout_rub:500,hold_days:5,active:false}];
  const stage4People = [
    {id:881032,internal_id:113,first_name:'Второй',username:'second_participant',
     role:'lead',status:'active'},
    {id:881033,internal_id:114,first_name:'Третий',username:'third_referrer',
     role:'referrer',status:'active'}
  ];
  const savedAssignments = new Set();
  window.__assignmentCalls = [];
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
    if(path==='/admin/mvp/events') data={events:[
      {id:'evt_1',review_status:'pending'},
      {id:'evt_2',review_status:'pending'}]};
    if(path==='/admin/finance/withdrawals'){
      const status=JSON.parse(opts?.body||'{}').status;
      data={withdrawals:status==='pending'?[{id:'wd_a',status:'pending'}]:
        status==='confirmed'?[{id:'wd_b',status:'confirmed'}]:[]};
    }
    if(path==='/admin/mvp/catalog') data={offers:stage4?stage4Offers:[sampleOffer]};
    if(path==='/admin/mvp/assignment-candidates'){
      const body=JSON.parse(opts?.body||'{}');
      const query=String(body.query||'').toLowerCase();
      const filtered=(stage4?stage4People:people.filter(p=>p.status==='active'))
        .filter(p=>(body.role_filter==='all'||!body.role_filter||p.role===body.role_filter)
          && (!query||(p.first_name+' '+p.username+' '+p.id+' '+p.internal_id).toLowerCase().includes(query)));
      data={users:body.page>1?[]:filtered,total:filtered.length,page:body.page||1,has_next:false};
    }
    if(path==='/admin/mvp/bulk-assignment'){
      const body=JSON.parse(opts?.body||'{}');
      window.__assignmentCalls.push(body);
      const pairs=body.mode==='offer_to_leads'
        ? [...new Set(body.user_ids)].map(id=>id+':'+body.offer_id)
        : [...new Set(body.offer_ids)].map(id=>body.user_id+':'+id);
      const already=pairs.filter(pair=>savedAssignments.has(pair)).length;
      if(!body.preview)for(const pair of pairs)savedAssignments.add(pair);
      data={preview:!!body.preview,requested:pairs.length,
        to_create:body.preview?pairs.length-already:0,
        already_assigned:already,created:body.preview?0:pairs.length-already};
    }
    if(path==='/admin/mvp/offer') {
      window.__lastOfferPayload=JSON.parse(opts.body);
      data={offer_id:'manual_12345678901234567890'};
    }
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

    def open_admin(self,browser,width,role='owner',stage4=False):
        page=browser.new_page(viewport={'width':width,'height':844})
        page.add_init_script(BOOTSTRAP)
        page.goto(self.base+f'/partners/admin/#tgWebAppData=visual-fixture&role={role}&stage4={int(stage4)}')
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
                        self.assertFalse(page.locator('[data-panel="pending"]').is_visible())
                        self.assertTrue(page.locator('.admin-hero').is_visible())
                        self.assertTrue(page.locator('.admin-overview').is_visible())
                        self.assertEqual(page.locator('.admin-tabs [data-section]').count(),5)
                        page.locator('[data-section="people"]').click()
                        self.assertTrue(page.locator('[data-panel="pending"]').is_visible())
                        page.locator('[data-subtab="users"]').click()
                        self.assertTrue(page.locator('[data-panel="users"]').is_visible())
                        self.assertFalse(page.locator('.admin-hero').is_visible())
                        self.assertFalse(page.locator('.admin-overview').is_visible())
                        self.assertTrue(page.locator('#admin-screen-intro').is_visible())
                        self.assertIn('Пользователи',page.locator('#admin-screen-heading').inner_text())
                        self.assertEqual(page.title(),'The Affiliates — Пользователи')
                        self.assertIn('04',page.locator('.admin-topline-index').inner_text())
                        page.locator('#users-list .admin-data-row').first.wait_for()
                        self.assertEqual(page.locator('#users-list .admin-data-row').count(),2)
                        self.assertEqual(page.locator('[data-subtab="users"]').get_attribute('aria-pressed'),'true')
                        page.locator('[data-section="more"]').click()
                        self.assertIn('Ещё',page.locator('#admin-screen-heading').inner_text())
                        self.assertIn('05',page.locator('.admin-topline-index').inner_text())
                        self.assertTrue(page.locator('[data-panel="invitations"]').is_visible())
                        self.assertFalse(page.locator('[data-panel="users"]').is_visible())
                        page.go_back()
                        self.assertTrue(page.locator('[data-panel="users"]').is_visible())
                        self.assertIn('Пользователи',page.locator('#admin-screen-heading').inner_text())
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

    def test_overview_action_center_shows_real_queues_and_routes(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for role,width in (('owner',1440),('admin',390),('staff',320)):
                    with self.subTest(role=role,width=width):
                        page=self.open_admin(browser,width,role)
                        errors=[]
                        page.on('pageerror',lambda e:errors.append(str(e)))
                        page.locator('#admin-action-reviews').get_by_text('2',exact=True).wait_for()
                        self.assertEqual(page.locator('#admin-action-pending').inner_text(),'1')
                        self.assertEqual(page.locator('#admin-action-finance').inner_text(),'2')
                        self.assertEqual(page.locator('.admin-action-card').count(),3)
                        self.assertFalse(page.evaluate(
                            'document.documentElement.scrollWidth > document.documentElement.clientWidth + 1'))
                        page.locator('[data-action-card="reviews"] button').click()
                        self.assertTrue(page.locator('[data-panel="offer_reviews"]').is_visible())
                        page.locator('[data-section="overview"]').click()
                        page.locator('[data-action-card="finance"] button').click()
                        self.assertTrue(page.locator('[data-panel="finance"]').is_visible())
                        page.locator('[data-section="overview"]').click()
                        page.locator('[data-action-card="pending"] button').click()
                        self.assertTrue(page.locator('[data-panel="pending"]').is_visible())
                        self.assertFalse(errors,errors)
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
                        page.locator('[data-section="offers"]').click()
                        page.locator('#admin-offers-list .admin-catalog-card').first.wait_for()
                        page.get_by_role('button',name='Управлять каталогом').click()
                        dialog=page.locator('#mvp-catalog-dialog')
                        dialog.wait_for(state='visible')
                        dialog.get_by_text('Дебетовая карта Альфа Банк').first.wait_for()
                        self.assertEqual(dialog.locator('.admin-catalog-card').count(),1)
                        self.assertEqual(dialog.locator('form.admin-catalog-form').count(),1 if role=='owner' else 0)
                        dialog.get_by_role('button',name='Закрыть').click()
                        if role=='owner':
                            page.locator('#admin-offers-list').get_by_role('button',name='Редактировать').first.click()
                            editor=page.locator('#mvp-catalog-dialog form.admin-catalog-form')
                            self.assertEqual(editor.locator('input[name="name"]').input_value(),
                                'Дебетовая карта Альфа Банк — длинное наименование')
                            editor.get_by_role('button',name='Отменить редактирование').click()
                            page.locator('#mvp-catalog-dialog').get_by_role('button',name='Закрыть').click()
                        page.locator('[data-section="people"]').click()
                        page.locator('[data-subtab="users"]').click()
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

    def test_catalog_editor_centered_mobile_switch_and_edit_cancel(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for width in (320,390,768,1440):
                    with self.subTest(width=width):
                        page=self.open_admin(browser,width,role='owner')
                        page.locator('[data-section="offers"]').click()
                        page.get_by_role('button',name='Управлять каталогом').click()
                        dialog=page.locator('#mvp-catalog-dialog')
                        dialog.wait_for(state='visible')
                        form=dialog.locator('form.admin-catalog-form')
                        self.assertTrue(form.is_visible())
                        toggle=form.locator('#admin-catalog-active')
                        self.assertTrue(toggle.is_checked())
                        toggle.uncheck()
                        self.assertFalse(toggle.is_checked())
                        toggle.check()
                        grid=form.locator('.admin-catalog-field-grid')
                        columns=grid.evaluate('node => getComputedStyle(node).gridTemplateColumns.split(" ").length')
                        self.assertEqual(columns,1 if width<=740 else 2)
                        self.assertEqual(form.locator('textarea[name="instructions"]').count(),1)
                        rect=dialog.bounding_box()
                        self.assertLessEqual(abs(rect['x']+rect['width']/2-width/2),2,rect)
                        self.assertLessEqual(rect['x']+rect['width'],width+1,rect)
                        self.assertFalse(form.get_by_role('button',name='Отменить редактирование').is_visible())
                        dialog.get_by_role('button',name='Редактировать').first.click()
                        self.assertTrue(form.get_by_role('button',name='Отменить редактирование').is_visible())
                        self.assertEqual(form.locator('input[name="name"]').input_value(),
                                         'Дебетовая карта Альфа Банк — длинное наименование')
                        form.get_by_role('button',name='Отменить редактирование').click()
                        self.assertEqual(form.locator('input[name="name"]').input_value(),'')
                        self.assertTrue(toggle.is_checked())
                        page.close()
            finally:
                browser.close()

    def test_stage3_category_options_and_logo_upload(self):
        buffer=io.BytesIO()
        Image.new('RGBA',(64,64),(230,115,40,190)).save(buffer,format='PNG')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=self.open_admin(browser,390)
                page.locator('[data-section="offers"]').click()
                page.get_by_role('button',name='Управлять каталогом').click()
                form=page.locator('#mvp-catalog-dialog form.admin-catalog-form')
                form.locator('input[name="name"]').fill('Тест МФО')
                form.locator('input[name="category"]').fill('МФО')
                form.locator('input[name="target_action"]').fill('Заявка')
                self.assertTrue(form.locator('.admin-offer-stage-option input[value="application_sent"]').is_checked())
                self.assertTrue(form.locator('.admin-offer-stage-option input[value="loan_issued"]').is_checked())
                self.assertFalse(form.locator('.admin-offer-stage-option input[value="meeting_scheduled"]').is_checked())
                form.locator('input#admin-offer-logo-file').set_input_files(
                    {'name':'logo.png','mimeType':'image/png','buffer':buffer.getvalue()})
                self.assertTrue(form.locator('.admin-logo-preview img').is_visible())
                form.get_by_role('button',name='Сохранить оффер').click()
                page.wait_for_function('Boolean(window.__lastOfferPayload)')
                payload=page.evaluate('window.__lastOfferPayload')
                self.assertEqual(payload['lead_stages'],['application_sent','loan_issued'])
                self.assertTrue(payload['logo_data'].startswith('data:image/webp;base64,'))
                self.assertNotIn('age_min',payload)
                self.assertNotIn('auto_assign',payload)
                page.close()
            finally:
                browser.close()

    def test_stage4_two_bulk_modes_preview_commit_and_mobile_geometry(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for width in (320,390):
                    with self.subTest(width=width):
                        page=self.open_admin(browser,width,stage4=True)
                        errors=[]
                        page.on("pageerror",lambda e:errors.append(str(e)))
                        page.locator('[data-section="assignments"]').click()
                        page.locator('#admin-assignment-users input[type="checkbox"]').first.wait_for()
                        self.assertEqual(page.locator('#admin-assignment-users input[type="checkbox"]').count(),2)
                        self.assertEqual(page.locator('#admin-assignment-offer option').count(),3)
                        self.assertFalse(page.locator('#admin-assignment-review').is_enabled())
                        page.locator('#admin-assignment-offer').select_option('manual_a')
                        page.locator('#admin-assignment-select-all').click()
                        self.assertIn('Выбрано: 2',page.locator('#admin-assignment-selected-count').inner_text())
                        page.locator('#admin-assignment-review').click()
                        dialog=page.locator('#admin-bulk-confirm')
                        dialog.wait_for(state='visible')
                        self.assertEqual(dialog.locator('.admin-bulk-stat strong').all_inner_texts(),['2','2','0'])
                        dialog.locator('#admin-bulk-commit').click()
                        page.locator('#admin-assignment-result').get_by_text('Добавлено: 2',exact=False).wait_for()
                        page.locator('[data-assign-mode="lead_to_offers"]').click()
                        self.assertTrue(page.locator('#admin-assignment-offers-panel').is_visible())
                        page.locator('#admin-assignment-users input[type="radio"]').first.check()
                        self.assertEqual(page.locator('#admin-assignment-offers input[type="checkbox"]').count(),2)
                        self.assertFalse(page.locator('#admin-assignment-offers input[value="manual_c"]').count())
                        page.locator('#admin-assignment-category-filter').select_option('МФО')
                        self.assertEqual(page.locator('#admin-assignment-offers input[type="checkbox"]').count(),1)
                        page.locator('#admin-assignment-select-all').click()
                        page.locator('#admin-assignment-category-filter').select_option('')
                        self.assertTrue(page.locator('#admin-assignment-offers input[value="manual_b"]').is_checked())
                        page.locator('#admin-assignment-select-all').click()
                        page.locator('#admin-assignment-review').click()
                        dialog.wait_for(state='visible')
                        self.assertEqual(dialog.locator('.admin-bulk-stat strong').all_inner_texts(),['2','1','1'])
                        dialog.locator('#admin-bulk-commit').click()
                        page.locator('#admin-assignment-result').get_by_text('Добавлено: 1',exact=False).wait_for()
                        self.assertEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                        self.assertFalse(errors,errors)
                        calls=page.evaluate('window.__assignmentCalls')
                        self.assertEqual([call['mode'] for call in calls],
                                         ['offer_to_leads','offer_to_leads','lead_to_offers','lead_to_offers'])
                        page.close()
            finally:
                browser.close()
