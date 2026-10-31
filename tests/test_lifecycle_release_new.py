"""New post-8e699b5 HTTP lifecycle checks; isolated database per test."""
import sqlite3
import unittest
from contextlib import closing

from tests import test_registration as h


class ReleaseLifecycle(unittest.TestCase):
    setUp = h.HttpHarness.setUp
    stop_server = h.HttpHarness.stop_server
    post = h.HttpHarness.post
    as_user = h.HttpHarness.as_user
    owner_invite = h.HttpHarness.owner_invite
    register = h.HttpHarness.register
    webhook_start = h.HttpHarness.webhook_start

    def outbox(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(
                'SELECT event_key,chat_id,text,attempts,sent_at FROM notifications_outbox ORDER BY id'
            ).fetchall()

    def test_rejected_blocked_recovery_and_idempotent_outbox_after_restart(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE,
                                      decision='reject', reason='Document mismatch')[0], 200)
        for route in ('/api/invitations/referral', '/api/admin/invitations'):
            self.assertEqual(self.as_user(route, h.ALICE)[0], 403)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE,
                                      decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE,
                                      role='referrer')[0], 200)
        self.assertEqual(self.as_user('/api/invitations/referral', h.ALICE)[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE,
                                      decision='block', reason='Policy review')[0], 200)
        self.assertEqual(self.as_user('/api/invitations/referral', h.ALICE)[0], 403)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE,
                                      decision='approve')[0], 200)
        before = self.outbox()
        self.assertEqual(len(before), 5)  # registration and four distinct status changes
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE,
                                      decision='approve')[0], 200)
        self.assertEqual(self.outbox(), before)
        self.stop_server()
        from http.server import ThreadingHTTPServer
        from server.api import Handler
        import threading
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.assertEqual(self.outbox(), before)
        self.assertEqual(self.as_user('/api/session', h.ALICE)[1]['status'], 'active')

    def test_issuer_assignee_separation_and_malicious_unattested_code(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE,
                                      decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE,
                                      role='staff')[0], 200)
        genuine = self.owner_invite(assignee_id=h.ALICE)
        forged = self.owner_invite()
        # Client text cannot bootstrap or replace an authenticated first source.
        self.assertEqual(self.as_user('/api/register', h.BOB, invite_code=forged, consent=True)[0], 400)
        self.assertEqual(self.webhook_start(866110, h.BOB, 'ag_fake-evil-invite')[0], 200)
        self.assertEqual(self.webhook_start(866111, h.BOB, genuine)[0], 200)
        self.assertEqual(self.as_user('/api/register', h.BOB, invite_code=forged, consent=True)[0], 409)
        status, result = self.as_user('/api/register', h.BOB, consent=True)
        self.assertEqual(status, 200, result)
        profile = result['user']
        self.assertEqual((profile['introduced_by_id'], profile['agency_id'], profile['manager_id']),
                         (h.OWNER, h.OWNER, h.ALICE))
        self.assertEqual(self.as_user('/api/admin/decision', h.ALICE, user_id=h.BOB,
                                      decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.ALICE, user_id=h.OWNER,
                                      decision='block', reason='malicious')[0], 403)

    def test_demoted_agency_issuer_invalidates_captured_source_without_side_effects(self):
        # ALICE creates the invite while staff; OWNER remains the active assignee.
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE,
                                      decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE,
                                      role='staff')[0], 200)
        status, issued = self.as_user('/api/admin/invitations', h.ALICE)
        self.assertEqual(status, 200, issued)
        stale_code = issued['invite_code']
        # Staff may only issue invitations assigned to themselves through HTTP.
        # Build the independent active-OWNER-assignee state directly in the
        # isolated fixture to distinguish issuer demotion from assignee status.
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute('UPDATE invitations SET assignee_id=? WHERE code=?',
                         (h.OWNER, stale_code))
            conn.commit()
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute(
                'SELECT issuer_id,assignee_id FROM invitations WHERE code=?',
                (stale_code,)
            ).fetchone(), (h.ALICE, h.OWNER))
        status, dashboard = self.as_user('/api/admin/dashboard', h.OWNER)
        self.assertEqual(status, 200, dashboard)
        invitation = next(item for item in dashboard['invites'] if item['code'] == stale_code)
        self.assertEqual((invitation['active'], invitation['usable']), (1, True))
        self.assertEqual(self.webhook_start(867001, h.BOB, stale_code)[0], 200)
        # Demotion changes issuer eligibility, not their active status or assignee eligibility.
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE,
                                      role='lead')[0], 200)
        self.assertEqual(self.as_user('/api/session', h.ALICE)[1]['status'], 'active')
        status, dashboard = self.as_user('/api/admin/dashboard', h.OWNER)
        self.assertEqual(status, 200, dashboard)
        invitation = next(item for item in dashboard['invites'] if item['code'] == stale_code)
        self.assertEqual((invitation['active'], invitation['usable']), (1, False))
        audit_before = self._count('audit')
        outbox_before = self.outbox()
        status, failure = self.as_user('/api/register', h.BOB, consent=True)
        self.assertEqual(status, 409, failure)
        self.assertEqual(self._count('users', 'WHERE id=?', (h.BOB,)), 0)
        self.assertEqual(self._count('audit'), audit_before)
        self.assertEqual(self.outbox(), outbox_before)
        # New eligible source replaces the now-invalid pending start.
        replacement = self.owner_invite()
        self.assertEqual(self.webhook_start(867002, h.BOB, replacement)[0], 200)
        status, registered = self.as_user('/api/register', h.BOB, consent=True)
        self.assertEqual(status, 200, registered)
        self.assertEqual(registered['user']['introduced_by_id'], h.OWNER)
        self.assertEqual(registered['user']['agency_id'], h.OWNER)
        self.assertEqual(self._count('users', 'WHERE id=?', (h.BOB,)), 1)

    def _count(self, table, where='', params=()):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(f'SELECT count(*) FROM {table} {where}', params).fetchone()[0]
