"""Isolated browser parity: staff and admin see the owner's operational controls."""
import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler
from tests.test_admin_redesign_browser import BOOTSTRAP


BOOTSTRAP_PARITY = BOOTSTRAP.replace(
    "if(data!==undefined)return Promise.resolve(new Response(JSON.stringify(data),",
    """window.__adminMutations=window.__adminMutations||[];
    if(path==='/admin/assign'||path==='/admin/bloggers/create'){
      window.__adminMutations.push({path,body:JSON.parse(opts.body)});
      data=path==='/admin/assign'?{updated:true}:{display_id:'B-000118'};
    }
    if(path==='/admin/mvp/catalog')data={offers:[sampleOffer,{
      ...sampleOffer,id:'manual_extra',name:'Дополнительный оффер'}]};
    if(path==='/admin/bloggers/list') data={bloggers:[{
      blogger_uuid:'12345678-1234-1234-1234-123456789012',telegram_id:991002,
      display_id:'B-000117',channel:'@demo_channel',fixed_rub:1500,percent_bps:1500,
      active:true,rewards:[{id:'br_123456789012345678901234',kind:'fixed',
        amount_kopeks:150000,status:'earned'}]}]};
    if(path==='/admin/finance/withdrawals'){
      const status=JSON.parse(opts?.body||'{}').status;
      data={withdrawals:status==='pending'?[{
        id:'wd_123456789012345678901234',display_id:'L-000113',
        amount_rub:750,status:'pending',has_payout_details:true}]:[]};
    }
    if(path==='/admin/participant')data={user:{...people[0],status:'active'},
      finance:{balances:{accrued_rub:0,available_rub:0,reserved_rub:0,paid_rub:0}},
      manual:{statistics:{total:1,in_progress:0,completed:0},offers:[sampleOffer]},
      audit:[]};
    if(data!==undefined)return Promise.resolve(new Response(JSON.stringify(data),"""
)


class StaffOwnerParityBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),BrowserHandler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_staff_admin_owner_controls_and_mobile_geometry(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                for role,width in (('owner',390),('admin',375),('staff',320),('staff',430)):
                    with self.subTest(role=role,width=width):
                        page=browser.new_page(viewport={'width':width,'height':844})
                        errors=[]
                        page.on('pageerror',lambda exc:errors.append(str(exc)))
                        page.add_init_script(BOOTSTRAP_PARITY)
                        page.goto(self.base+'/partners/admin/#tgWebAppData=parity-fixture&role='+role)
                        page.locator('#admin-app').wait_for(state='visible')
                        # All roles can access the complete operational catalogue.
                        self.assertTrue(page.locator('[data-section="offers"]').is_visible())
                        self.assertTrue(page.locator('[data-section="assignments"]').is_visible())
                        self.assertTrue(page.locator('[data-go-section="assignments"]').is_visible())
                        page.locator('[data-section="offers"]').click()
                        page.locator('#admin-offers-list .admin-catalog-card').first.wait_for()
                        page.get_by_role('button',name='Управлять каталогом').click()
                        dialog=page.locator('#mvp-catalog-dialog')
                        dialog.wait_for(state='visible')
                        self.assertTrue(dialog.locator('form.admin-catalog-form').is_visible())
                        self.assertEqual(dialog.get_by_role('button',name='Удалить',exact=True).count(),2)
                        dialog.get_by_role('button',name='Закрыть').click()

                        page.locator('[data-section="assignments"]').click()
                        self.assertTrue(page.locator('[data-workspace="assignments"]').is_visible())
                        self.assertTrue(page.locator('#admin-assignment-review').is_visible())

                        page.locator('[data-section="people"]').click()
                        page.locator('[data-subtab="users"]').click()
                        row=page.locator('#users-list tbody tr').first
                        row.wait_for(state='visible')
                        for label in ('Карточка','Роль / менеджер','Исправить источник','Блокировать'):
                            self.assertEqual(row.get_by_role('button',name=label,exact=True).count(),1,
                                             (role,width,label))
                        row.get_by_role('button',name='Карточка').click()
                        profile=page.locator('#participant-detail')
                        self.assertTrue(profile.is_visible())
                        for label in ('Сохранить статус','Убрать оффер',
                                      'Добавить подтверждённое начисление','Назначить оффер'):
                            self.assertEqual(profile.get_by_role('button',name=label,exact=True).count(),1,
                                             (role,width,label))
                        profile.get_by_role('button',name='Закрыть').click()

                        page.locator('[data-subtab="finance"]').click()
                        payout=page.locator('#admin-finance-list .admin-offer-event-card').first
                        payout.wait_for(state='visible')
                        for label in ('Показать реквизиты СБП','Подтвердить','Отклонить'):
                            self.assertEqual(payout.get_by_role('button',name=label,exact=True).count(),1)
                        page.locator('[data-subtab="offer_reviews"]').click()
                        self.assertTrue(page.locator('[data-panel="offer_reviews"]').is_visible())

                        page.locator('[data-section="more"]').click()
                        self.assertTrue(page.locator('#invite-form').is_visible())
                        page.locator('[data-subtab="audit"]').click()
                        self.assertTrue(page.locator('[data-panel="audit"]').is_visible())
                        page.locator('[data-subtab="bloggers"]').click()
                        self.assertTrue(page.locator('#admin-blogger-form').is_visible())
                        blogger=page.locator('#admin-blogger-list .admin-offer-event-card').first
                        blogger.wait_for(state='visible')
                        for label in ('Сохранить условия','Подтвердить размещение','Отметить выплаченным'):
                            self.assertEqual(blogger.get_by_role('button',name=label,exact=True).count(),1,
                                             (role,width,label))
                        self.assertLessEqual(page.evaluate(
                            'document.documentElement.scrollWidth-document.documentElement.clientWidth'),1)
                        self.assertFalse(errors,errors)
                        page.close()
            finally:
                browser.close()

    def test_staff_can_submit_admin_promotion_and_blogger_creation(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={'width':390,'height':844})
                page.add_init_script(BOOTSTRAP_PARITY)
                page.goto(self.base+'/partners/admin/#tgWebAppData=parity-fixture&role=staff')
                page.locator('#admin-app').wait_for(state='visible')
                page.locator('[data-section="people"]').click()
                page.locator('[data-subtab="users"]').click()
                row=page.locator('#users-list tbody tr').first
                row.wait_for(state='visible')
                page.evaluate("""() => {
                  const answers=['admin',''];
                  window.prompt=()=>answers.shift()??null;
                }""")
                row.get_by_role('button',name='Роль / менеджер').click()
                page.wait_for_function("window.__adminMutations?.some(x=>x.path==='/admin/assign')")
                payload=page.evaluate("window.__adminMutations.find(x=>x.path==='/admin/assign').body")
                self.assertEqual(payload['role'],'admin')
                self.assertEqual(payload['user_id'],881031)

                page.locator('[data-section="more"]').click()
                page.locator('[data-subtab="bloggers"]').click()
                form=page.locator('#admin-blogger-form')
                self.assertTrue(form.is_visible())
                form.locator('#admin-blogger-telegram').fill('991015')
                form.locator('#admin-blogger-channel').fill('@test_campaign')
                form.locator('#admin-blogger-fixed').fill('1500')
                form.locator('#admin-blogger-percent').fill('15')
                form.get_by_role('button',name='Создать',exact=False).click()
                page.wait_for_function("window.__adminMutations?.some(x=>x.path==='/admin/bloggers/create')")
                created=page.evaluate("window.__adminMutations.find(x=>x.path==='/admin/bloggers/create').body")
                self.assertEqual(created['telegram_id'],991015)
                self.assertEqual(created['fixed_rub'],1500)
                self.assertEqual(created['percent_bps'],1500)
                page.close()
            finally:
                browser.close()


if __name__=='__main__':
    unittest.main()
