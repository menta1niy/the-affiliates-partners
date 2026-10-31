"""Focused invite revocation checks through signed HTTP and temp SQLite."""
import sqlite3
import unittest
from contextlib import closing

from tests import test_registration as h


class RevokeHTTP(unittest.TestCase):
    setUp = h.HttpHarness.setUp
    stop_server = h.HttpHarness.stop_server
    post = h.HttpHarness.post
    as_user = h.HttpHarness.as_user
    owner_invite = h.HttpHarness.owner_invite
    register = h.HttpHarness.register
    webhook_start = h.HttpHarness.webhook_start

    def test_owner_and_issuer_revoke_permissions_idempotency_and_new_source(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE, role='staff')[0], 200)
        old_code = self.as_user('/api/admin/invitations', h.ALICE)[1]['invite_code']
        self.assertEqual(self.webhook_start(981001, h.BOB, old_code)[0], 200)

        def count_audit():
            with closing(sqlite3.connect(self.db_path)) as conn:
                return conn.execute("SELECT count(*) FROM audit WHERE action='invite_revoke'").fetchone()[0]

        def outbox():
            with closing(sqlite3.connect(self.db_path)) as conn:
                return conn.execute('SELECT event_key,chat_id,text FROM notifications_outbox ORDER BY id').fetchall()

        baseline = count_audit()
        notifications = outbox()
        self.assertEqual(self.as_user('/api/invitations/revoke', h.BOB, code=old_code)[0], 403)
        self.assertEqual(count_audit(), baseline)
        status, result = self.as_user('/api/invitations/revoke', h.ALICE, code=old_code)
        self.assertEqual((status, result.get('changed')), (200, True))
        self.assertEqual(self.as_user('/api/invitations/revoke', h.ALICE, code=old_code),
                         (200, {'changed': False}))
        self.assertEqual(count_audit(), baseline + 1)
        self.assertEqual(outbox(), notifications)
        self.assertEqual(self.as_user('/api/register', h.BOB, consent=True)[0], 409)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM users WHERE id=?', (h.BOB,)).fetchone()[0], 0)

        replacement = self.owner_invite()
        self.assertEqual(self.webhook_start(981002, h.BOB, replacement)[0], 200)
        self.assertEqual(self.as_user('/api/register', h.BOB, consent=True)[0], 200)
        owner_code = self.owner_invite()
        self.assertEqual(self.as_user('/api/invitations/revoke', h.ALICE, code=owner_code)[0], 403)
        self.assertEqual(self.as_user('/api/invitations/revoke', h.OWNER, code=owner_code),
                         (200, {'changed': True}))
        self.assertEqual(count_audit(), baseline + 2)
        # The registration event for BOB is the only additional notification.
        self.assertEqual(len(outbox()), len(notifications) + 1)
