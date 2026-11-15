"""Real Chromium admin-edit -> participant-view standalone MVP smoke."""
import os
import unittest
from unittest.mock import patch
from urllib.parse import quote

from playwright.sync_api import sync_playwright

from server import db
from tests.test_admin_participant_browser import AdminDetailBrowserSmoke
from tests.test_registration import OWNER, TOKEN, init_data


class MvpBrowserSmoke(AdminDetailBrowserSmoke):
    def test_catalog_profile_status_and_participant_screen(self):
        with db.transaction() as conn:
            conn.execute("UPDATE users SET consent_at=100 WHERE id=?", (self.lead_a,))
        with (patch('server.api.bot_token',return_value=TOKEN),
              patch('server.api.admin_id',return_value=OWNER),
              patch.dict(os.environ,{'PARTNERS_MVP_OPEN_REGISTRATION':'true'}),
              sync_playwright() as p):
            browser=p.chromium.launch(headless=True)
            try:
                admin=browser.new_page(viewport={'width':390,'height':844})
                admin.goto(self.base+'/partners/admin/#tgWebAppData='+quote(init_data(OWNER),safe=''))
                admin.get_by_role('button',name='Каталог офферов').click()
                form=admin.locator('#mvp-catalog-dialog form')
                form.locator('[name="name"]').fill('Тестовый банковский оффер')
                form.locator('[name="category"]').fill('Дебетовая карта')
                form.locator('[name="target_action"]').fill('Активировать карту')
                form.locator('[name="payout_rub"]').fill('900')
                form.locator('[name="hold_days"]').fill('10')
                form.locator('[name="instructions"]').fill('Инструкция для участника')
                form.get_by_role('button',name='Сохранить оффер').click()
                admin.locator('#mvp-catalog-dialog').get_by_text('Тестовый банковский оффер').first.wait_for()
                admin.locator('#mvp-catalog-dialog').get_by_role('button',name='Закрыть').click()
                admin.locator('[data-tab="users"]').click()
                admin.locator('#user-query').fill(str(self.lead_a))
                admin.locator('#users-list').get_by_role('button',name='Карточка').click()
                detail=admin.locator('#participant-detail')
                detail.get_by_role('button',name='Назначить оффер').wait_for()
                detail.get_by_role('button',name='Назначить оффер').click()
                detail.get_by_text('Тестовый банковский оффер').first.wait_for()
                detail.get_by_role('button',name='Сохранить статус').click()
                user=browser.new_page(viewport={'width':390,'height':844})
                user.goto(self.base+'/partners/#tgWebAppData='+quote(init_data(self.lead_a),safe=''))
                user.locator('#offers').get_by_text('Тестовый банковский оффер').wait_for()
                self.assertIn('900 ₽', user.locator('#offers').inner_text())
                self.assertIn('Холд: 10', user.locator('#offers').inner_text())
                self.assertIn('Дебетовая карта', user.locator('#offers').inner_text())
                self.assertIn('Назначено', user.locator('#offers').inner_text())
            finally:
                browser.close()
