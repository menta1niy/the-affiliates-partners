"""Stage 10: first-source link visits and privacy-safe transactional notifications."""
import unittest
import time

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB


class Stage10Notifications(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    as_user = HttpHarness.as_user
    post = HttpHarness.post
    webhook_start = HttpHarness.webhook_start

    def test_referral_visit_only_once_for_first_valid_link(self):
        db.session({'id': OWNER, 'first_name':'Owner', 'last_name':'', 'username':'owner'}, OWNER)
        # Create an active ordinary referrer, without requiring a real Telegram account.
        with db.transaction() as conn:
            now = int(time.time())
            conn.execute("INSERT INTO users(id,internal_id,first_name,role,status,agency_id,registered_at,updated_at) "
                         "VALUES(?,?,?,'lead','active',?,?,?)",
                         (ALICE, db.allocate_internal_id(conn), 'Alice', OWNER, now, now))
        status, invitation = self.as_user('/api/invitations/referral', ALICE)
        self.assertEqual(status, 200, invitation)
        code = invitation['code']
        self.assertEqual(self.webhook_start(995111, BOB, code)[0], 200)
        self.assertEqual(self.webhook_start(995112, BOB, code)[0], 200)
        # First valid source remains immutable, even with another valid link.
        with db.transaction() as conn:
            visits = conn.execute("SELECT chat_id,text FROM notifications_outbox "
                                  "WHERE event_key LIKE 'referral:visit:%'").fetchall()
            self.assertEqual(len(visits), 1)
            self.assertEqual(visits[0]['chat_id'], ALICE)
            self.assertNotIn(str(BOB), visits[0]['text'])
            self.assertEqual(conn.execute('SELECT code FROM pending_starts WHERE telegram_id=?',
                                          (BOB,)).fetchone()['code'], code)

    def test_admin_referral_links_never_emit_ordinary_reward_visit(self):
        db.session({'id': OWNER, 'first_name':'Owner', 'last_name':'', 'username':'owner'}, OWNER)
        invitation = self.as_user('/api/invitations/referral', OWNER)[1]
        self.assertEqual(self.webhook_start(995113, BOB, invitation['code'])[0], 200)
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notifications_outbox "
                                          "WHERE event_key LIKE 'referral:visit:%'").fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
