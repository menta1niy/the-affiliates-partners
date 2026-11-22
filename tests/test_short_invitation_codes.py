"""Invitation code format, collision handling and legacy Telegram entry points."""
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB


class ShortInvitationCodeTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    owner_invite = HttpHarness.owner_invite
    register = HttpHarness.register
    webhook_start = HttpHarness.webhook_start

    def test_username_lookup_uses_cursor_fetchall_on_postgres(self):
        # PostgreSQL's wrapper Cursor is deliberately not iterable.
        cursor = Mock()
        cursor.fetchall.return_value = [{"id": 123, "username": "manager"}]
        conn = Mock()
        conn.execute.return_value = cursor
        people = [{"manager_id": 123, "agency_id": None, "referrer_id": None, "introduced_by_id": None}]
        db.attach_reference_usernames(conn, people)
        cursor.fetchall.assert_called_once_with()
        self.assertEqual(people[0]["manager_username"], "manager")

    def test_new_agency_and_referral_codes_are_six_uppercase_characters(self):
        agency = self.owner_invite()
        self.assertRegex(agency, r"^[A-Z0-9]{6}$")
        self.assertEqual(self.register(ALICE, agency)[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', OWNER, user_id=ALICE, decision='approve')[0], 200)
        status, referral = self.as_user('/api/invitations/referral', ALICE)
        self.assertEqual(status, 200, referral)
        self.assertRegex(referral['code'], r"^[A-Z0-9]{6}$")
        self.assertNotEqual(agency, referral['code'])
        self.assertEqual(self.register(BOB, referral['code'])[0], 200)
        self.assertEqual(self.as_user('/api/invitations/referral', ALICE)[1]['code'], referral['code'])

    def test_collision_retries_and_revoked_codes_are_never_reissued(self):
        with patch('server.db.secrets.choice', side_effect=list('ABC123ABC123XYZ789')):
            first = self.owner_invite()
            second = self.owner_invite()
        self.assertEqual((first, second), ('ABC123', 'XYZ789'))
        self.assertEqual(self.as_user('/api/invitations/revoke', OWNER, code=first)[0], 200)
        with patch('server.db.secrets.choice', side_effect=list('ABC123NEW456')):
            third = self.owner_invite()
        self.assertEqual(third, 'NEW456')

    def test_existing_prefixed_invitation_and_links_remain_valid(self):
        db.session({'id': OWNER, 'first_name': 'Owner', 'last_name': '', 'username': 'owner'}, OWNER)
        with db.transaction() as conn:
            conn.execute("INSERT INTO invitations(code,kind,issuer_id,created_at) VALUES(?,?,?,?)",
                         ('ref_Legacy12345', 'referral', OWNER, 1))
            conn.execute("INSERT INTO invitations(code,kind,issuer_id,assignee_id,created_at) VALUES(?,?,?,?,?)",
                         ('ag_Legacy12345', 'agency', OWNER, OWNER, 1))
        self.assertEqual(self.register(ALICE, 'ref_Legacy12345')[0], 200)
        self.assertEqual(self.register(BOB, 'ag_Legacy12345')[0], 200)
        self.assertTrue(db.CODE_PATTERN.fullmatch('blog_Legacy12345'))


if __name__ == '__main__':
    unittest.main()
