"""Focused HTTP regressions for release critical behavior."""
import sqlite3
import unittest
import json
from io import BytesIO
from unittest.mock import patch

from server import db
from tests import test_registration as helpers
OWNER, ALICE, BOB = helpers.OWNER, helpers.ALICE, helpers.BOB
from tools import dispatch_notifications


class ReleaseContracts(unittest.TestCase):
    setUp = helpers.HttpHarness.setUp
    stop_server = helpers.HttpHarness.stop_server
    post = helpers.HttpHarness.post
    as_user = helpers.HttpHarness.as_user
    owner_invite = helpers.HttpHarness.owner_invite
    register = helpers.HttpHarness.register
    webhook_start = helpers.HttpHarness.webhook_start

    def test_role_status_access(self):
        self.assertEqual(self.as_user('/api/admin/dashboard', ALICE)[0], 403)
        self.assertEqual(self.as_user('/api/invitations/referral', ALICE)[0], 403)
        self.assertEqual(self.register(ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', ALICE, user_id=ALICE, decision='active')[0], 403)
        self.assertEqual(self.as_user('/api/admin/decision', OWNER, user_id=ALICE, decision='active')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', OWNER, user_id=ALICE, role='referrer')[0], 200)
        self.assertEqual(self.as_user('/api/invitations/referral', ALICE)[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', OWNER, user_id=ALICE, decision='blocked')[0], 200)
        self.assertEqual(self.as_user('/api/invitations/referral', ALICE)[0], 403)

    def test_atomic_decision_rollback_when_outbox_fails(self):
        self.assertEqual(self.register(ALICE, self.owner_invite())[0], 200)
        with patch.object(db, 'enqueue', side_effect=sqlite3.OperationalError('synthetic')):
            status, body = self.as_user('/api/admin/decision', OWNER, user_id=ALICE, decision='active')
        self.assertEqual(status, 503, body)
        self.assertEqual(self.as_user('/api/session', ALICE)[1]['status'], 'pending')
        with sqlite3.connect(self.db_path) as connection:
            count = connection.execute("SELECT count(*) FROM audit WHERE action='decision_active' AND target_id=?", (ALICE,)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_repeated_first_start_and_one_use(self):
        first, second = self.owner_invite(), self.owner_invite()
        self.assertEqual(self.webhook_start(93001, ALICE, first)[0], 200)
        self.assertEqual(self.webhook_start(93002, ALICE, second)[0], 200)
        self.assertEqual(self.register(ALICE, second)[0], 409)
        self.assertEqual(self.as_user('/api/register', ALICE, consent=True)[0], 200)
        self.assertEqual(self.register(BOB, first)[0], 400)
        self.assertEqual(self.register(BOB, second)[0], 200)

    def test_signed_start_param_first_source_without_webhook(self):
        """Signed direct Mini App launch must capture immutable first valid source."""
        self.assertEqual(self.register(ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', OWNER, user_id=ALICE, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', OWNER, user_id=ALICE, role='referrer')[0], 200)
        status, referral = self.as_user('/api/invitations/referral', ALICE)
        self.assertEqual(status, 200, referral)
        ref_code = referral['invite_code']
        conflicting = self.owner_invite()

        signed_ref = helpers.init_data(BOB, start_param=ref_code)
        signed_other = helpers.init_data(BOB, start_param=conflicting)
        self.assertEqual(self.post('/api/session', {'initData': signed_ref})[0], 200)
        status, rejected = self.post('/api/register', {'initData': signed_ref, 'invite_code': conflicting, 'consent': True})
        self.assertEqual(status, 409, rejected)
        self.assertEqual(self.post('/api/session', {'initData': signed_other})[0], 200)
        status, registered = self.post('/api/register', {'initData': signed_other, 'consent': True})
        self.assertEqual(status, 200, registered)
        self.assertEqual(registered['user']['source'], 'referral')
        self.assertEqual(registered['user']['referrer_id'], ALICE)

        # Invalid *signed* start_param must not poison attribution for a new user.
        invalid = helpers.init_data(helpers.CAROL, start_param='ref_not_real1234')
        self.assertEqual(self.post('/api/session', {'initData': invalid})[0], 200)
        status, no_source = self.post('/api/register', {'initData': invalid, 'consent': True})
        self.assertEqual(status, 400, no_source)
        valid = helpers.init_data(helpers.CAROL, start_param=ref_code)
        self.assertEqual(self.post('/api/register', {'initData': valid, 'consent': True})[0], 200)

    def test_notification_telegram_http_mock_and_dedup(self):
        self.assertEqual(self.register(ALICE, self.owner_invite())[0], 200)

        def respond(request, timeout):
            self.assertEqual(timeout, 8)
            self.assertIn('/sendMessage', request.full_url)
            self.assertEqual(json.loads(request.data)['chat_id'], OWNER)
            return BytesIO(b'{"ok":true}')

        with patch.object(dispatch_notifications, 'bot_token', return_value='fake-token'), patch.object(dispatch_notifications.urllib.request, 'urlopen', side_effect=respond) as sender:
            self.assertEqual(dispatch_notifications.dispatch(), 0)
            self.assertEqual(dispatch_notifications.dispatch(), 0)
        sender.assert_called_once()
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM notifications_outbox WHERE sent_at IS NOT NULL').fetchone()[0], 1)

    def test_owner_audited_source_correction_preserves_manager(self):
        """Owner can correct attribution to an eligible active referrer without reassigning staff."""
        self.assertEqual(self.register(ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', OWNER, user_id=ALICE, decision='active')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', OWNER, user_id=ALICE, role='referrer')[0], 200)
        self.assertEqual(self.register(BOB, self.owner_invite())[0], 200)
        before = self.as_user('/api/session', BOB)[1]['user']
        self.assertEqual(before['source'], 'agency')
        self.assertEqual(before['manager_id'], OWNER)
        self.assertIsNone(before['referrer_id'])
        self.assertEqual(self.as_user('/api/admin/attribution', BOB, user_id=BOB, source='referral', referrer_id=ALICE, reason='verified')[0], 403)
        status, result = self.as_user('/api/admin/attribution', OWNER, user_id=BOB, source='referral', referrer_id=ALICE, reason='verified')
        self.assertEqual(status, 200, result)
        self.assertTrue(result['changed'])
        self.assertEqual(result['user']['manager_id'], OWNER)
        self.assertEqual(result['user']['source'], 'referral')
        self.assertEqual(result['user']['referrer_id'], ALICE)
        self.assertEqual(result['user']['agency_id'], self.as_user('/api/session', ALICE)[1]['user']['agency_id'])
        persisted = self.as_user('/api/session', BOB)[1]['user']
        self.assertEqual(persisted['manager_id'], before['manager_id'])
        self.assertEqual(persisted['referrer_id'], ALICE)
        self.assertEqual(persisted['source'], 'referral')
        audit = self.as_user('/api/admin/audit', OWNER)[1]['events']
        self.assertTrue(any(event['action'] == 'attribution_correction' and event['actor_id'] == OWNER and event['target_id'] == BOB and 'verified' in event['details'] for event in audit))
