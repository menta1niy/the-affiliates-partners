"""Read-only against production; all writes use the isolated HTTP harness DB."""
import sqlite3
import unittest
from contextlib import closing

from tests import test_registration as h
from server import db


class NewSecurityBoundaries(unittest.TestCase):
    setUp = h.HttpHarness.setUp
    stop_server = h.HttpHarness.stop_server
    post = h.HttpHarness.post
    as_user = h.HttpHarness.as_user
    owner_invite = h.HttpHarness.owner_invite
    register = h.HttpHarness.register
    webhook_start = h.HttpHarness.webhook_start

    def snapshot(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return tuple(conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                         for table in ('users', 'audit', 'notifications_outbox', 'invitations'))

    def test_unsigned_identity_and_unattested_attribution_cannot_mutate(self):
        db.initialize()
        initial = self.snapshot()
        self.assertEqual(self.post('/api/session', {'initData': 'forged'})[0], 401)
        self.assertEqual(self.post('/api/register', {
            'initData': h.init_data(h.BOB), 'invite_code': 'ag_fake0000000', 'consent': True,
        })[0], 400)
        self.assertEqual(self.post('/api/admin/decision', {
            'initData': h.init_data(h.BOB), 'user_id': h.OWNER, 'decision': 'block',
            'reason': 'forged request',
        })[0], 403)
        self.assertEqual(self.snapshot()[1:], initial[1:])
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertIsNone(conn.execute('SELECT 1 FROM users WHERE id=?', (h.BOB,)).fetchone())

    def test_cross_role_attribution_correction_and_revoke_no_mutations(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE, role='referrer')[0], 200)
        code = self.as_user('/api/invitations/referral', h.ALICE)[1]['invite_code']
        self.assertEqual(self.register(h.BOB, self.owner_invite())[0], 200)
        before = self.snapshot()
        self.assertEqual(self.as_user('/api/admin/attribution', h.ALICE, user_id=h.BOB,
                                      source='referral', referrer_id=h.ALICE, reason='override')[0], 403)
        self.assertEqual(self.as_user('/api/invitations/revoke', h.BOB, code=code)[0], 403)
        self.assertEqual(self.snapshot(), before)
        status, dashboard = self.as_user('/api/admin/dashboard', h.OWNER)
        self.assertEqual(status, 200, dashboard)
        self.assertTrue(any(row['code'] == code and row['active'] == 1 for row in dashboard['invites']))
