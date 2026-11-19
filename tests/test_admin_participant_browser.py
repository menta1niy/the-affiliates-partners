"""Local real-browser smoke using synthetic signed Telegram initData and HTTP API."""
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from server import db
from server.api import Handler
from tests.test_admin_agency_scope import AdminAgencyScopeTests, OWNER
from tests.test_registration import TOKEN, init_data

ROOT = Path(__file__).resolve().parents[1]


class BrowserHandler(Handler):
    def do_GET(self):
        files = {'/partners/admin/': 'web/admin/index.html', '/partners/admin/admin.js': 'web/admin/admin.js',
                 '/partners/': 'web/index.html', '/partners/app.js': 'web/app.js',
                 '/partners/style.css': 'web/style.css', '/partners/telegram-layout.js': 'web/telegram-layout.js',
                 '/partners/ap-mark.png': 'web/ap-mark.png',
                 '/partners/fonts/unbounded-variable.ttf': 'web/fonts/unbounded-variable.ttf'}
        target = files.get(self.path)
        if not target:
            return super().do_GET()
        data = (ROOT / target).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'font/ttf' if target.endswith('.ttf') else 'image/png' if target.endswith('.png') else 'text/javascript' if target.endswith('.js') else 'text/css' if target.endswith('.css') else 'text/html')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path.startswith('/partners/api/'):
            self.path = self.path.replace('/partners/api/', '/api/', 1)
        return super().do_POST()


class AdminDetailBrowserSmoke(AdminAgencyScopeTests):
    def setUp(self):
        super().setUp()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), BrowserHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        with db.transaction() as conn:
            conn.execute("INSERT INTO crm_lead_bindings(crm_lead_id,telegram_id,bound_at) VALUES('browser-synthetic',?,100)", (self.lead_a,))
            conn.execute('INSERT INTO crm_assigned_offers(crm_lead_id,offer_id,payload) VALUES(?,?,?)', ('browser-synthetic', 'browser-offer', json.dumps({'id':'browser-offer','name':'<img src=x onerror=alert(1)>','lead_reward':'75','instructions':'Synthetic approved instructions'})))
            conn.execute('INSERT INTO crm_participant_states(crm_lead_id,payload,updated_at) VALUES(?,?,?)', ('browser-synthetic',json.dumps({'applications':[{'application_id':'a','offer_id':'browser-offer','stage':'credited'}],'lead_payouts':[{'conversion_id':'c','offer_id':'browser-offer','amount':'75','status':'confirmed','reversed':False}]}),101))

    def test_owner_admin_card_desktop_mobile(self):
        # Browser visits the real static admin document and requests the actual HTTP backend.
        with patch('server.api.bot_token', return_value=TOKEN), patch('server.api.admin_id', return_value=OWNER), sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for actor, width in ((OWNER, 1440), (self.admin, 390)):
                    with self.subTest(actor=actor, width=width):
                        page = browser.new_page(viewport={'width':width,'height':844})
                        errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.goto(self.base + '/partners/admin/#tgWebAppData=' + __import__('urllib.parse',fromlist=['quote']).quote(init_data(actor), safe=''), wait_until='domcontentloaded')
                        page.locator('[data-tab="users"]').click()
                        page.locator('#user-query').fill(str(self.lead_a))
                        page.get_by_role('button', name='Карточка').first.click()
                        dialog = page.locator('#participant-detail')
                        self.assertTrue(dialog.is_visible())
                        dialog.get_by_text('browser-synthetic').wait_for(timeout=5000)
                        self.assertIn('browser-synthetic', dialog.inner_text())
                        self.assertIn('Synthetic approved instructions', dialog.inner_text())
                        self.assertIn('confirmed', dialog.inner_text())
                        self.assertEqual(dialog.locator('img').count(), 0)
                        self.assertFalse(errors, errors)
                        self.assertLessEqual(dialog.evaluate('(e) => e.getBoundingClientRect().right'), width + 1)
                        page.close()
            finally:
                browser.close()

    def test_switching_cards_does_not_show_stale_participant(self):
        with patch('server.api.bot_token', return_value=TOKEN), patch('server.api.admin_id', return_value=OWNER), sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.add_init_script("""
                    const originalFetch = window.fetch.bind(window);
                    window.fetch = async (url, options) => {
                      if (String(url).endsWith('/admin/participant') &&
                          JSON.parse(options.body).user_id === 881031) {
                        await new Promise(resolve => setTimeout(resolve, 650));
                      }
                      return originalFetch(url, options);
                    };
                """)
                url = self.base + '/partners/admin/#tgWebAppData=' + __import__('urllib.parse', fromlist=['quote']).quote(init_data(OWNER), safe='')
                page.goto(url, wait_until='domcontentloaded')
                page.locator('[data-tab="users"]').click()
                first = page.locator('tr').filter(has_text=str(self.lead_a)).get_by_role('button', name='Карточка')
                second = page.locator('tr').filter(has_text=str(self.lead_b)).get_by_role('button', name='Карточка')
                first.click()
                page.locator('#participant-detail').get_by_role('button', name='Закрыть').click()
                second.click()
                dialog = page.locator('#participant-detail')
                dialog.get_by_text('Telegram ID:').wait_for()
                page.wait_for_timeout(850)
                self.assertIn(str(self.lead_b), dialog.inner_text())
                self.assertNotIn(str(self.lead_a), dialog.inner_text())
            finally:
                browser.close()

    def test_server_search_and_paging_cover_older_participants(self):
        with db.transaction() as conn:
            conn.executemany(
                "INSERT INTO users(id,first_name,role,status,agency_id,registered_at,updated_at) "
                "VALUES(?, 'Synthetic', 'lead', 'pending', ?, ?, ?)",
                [(910000 + i, self.a, 900000 + i, 900000 + i) for i in range(205)],
            )
        with patch('server.api.bot_token', return_value=TOKEN), patch('server.api.admin_id', return_value=OWNER), sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 844})
                url = self.base + '/partners/admin/#tgWebAppData=' + __import__('urllib.parse', fromlist=['quote']).quote(init_data(self.admin), safe='')
                page.goto(url, wait_until='domcontentloaded')
                page.locator('[data-tab="users"]').click()
                users = page.locator('#users-list')
                users.get_by_text('Страница 1 · всего', exact=False).wait_for()
                users.get_by_role('button', name='Далее').click()
                users.get_by_text('Страница 2 · всего', exact=False).wait_for()
                page.locator('#user-query').fill('910000')
                users.get_by_text('Страница 1 · всего', exact=False).wait_for()
                self.assertIn('910000', users.inner_text())
                self.assertNotIn('910001', users.inner_text())
                page.locator('#user-query').fill('nonexistent')
                users.get_by_text('Страница 1 · всего 0').wait_for()
                self.assertEqual(users.locator('tbody tr').count(), 0)
            finally:
                browser.close()
