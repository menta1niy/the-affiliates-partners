"""Sequential public IDs without changing Telegram identities or status history."""
import sqlite3
import unittest

from tests import test_registration as h


class InternalIds(unittest.TestCase):
    setUp = h.HttpHarness.setUp
    stop_server = h.HttpHarness.stop_server
    post = h.HttpHarness.post
    as_user = h.HttpHarness.as_user
    owner_invite = h.HttpHarness.owner_invite
    register = h.HttpHarness.register
    webhook_start = h.HttpHarness.webhook_start

    def test_owner_and_every_new_pending_registration_have_stable_order(self):
        self.assertEqual(self.as_user('/api/session', h.OWNER)[1]['user']['internal_id'], 100)
        first = self.register(h.ALICE, self.owner_invite())
        self.assertEqual(first[0], 200)
        self.assertEqual(first[1]['user']['internal_id'], 101)
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[1]['user']['internal_id'], 101)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE,
                                      decision='block', reason='Temporary')[1]['user']['internal_id'], 101)
        second = self.register(h.BOB, self.owner_invite())
        self.assertEqual(second[0], 200)
        self.assertEqual(second[1]['user']['internal_id'], 102)
        self.assertIn(102, [user['internal_id'] for user in self.as_user('/api/admin/dashboard', h.OWNER)[1]['users']])
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(DISTINCT internal_id) FROM users').fetchone()[0], 3)
            self.assertEqual(connection.execute('SELECT next_id FROM internal_id_sequence').fetchone()[0], 103)
        from server import db
        db.initialize()
        self.assertEqual(self.as_user('/api/session', h.ALICE)[1]['user']['internal_id'], 101)
