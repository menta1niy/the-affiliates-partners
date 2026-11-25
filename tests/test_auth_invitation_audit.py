"""Real signed Telegram deep-link and open-onboarding regression checks."""
import unittest

from server import db
from server.auth import verify_init_data
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB, TOKEN, TEST_ONBOARDING, init_data


class SignedLinkAuditTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    owner_invite = HttpHarness.owner_invite

    def test_signed_six_character_and_legacy_start_parameters(self):
        for code in ("TJ7VSD", "RI91K2", "ref_abcdefgh123456", "ag_abcdefgh123456", "blog_abcdefgh123456"):
            with self.subTest(code=code):
                verified = verify_init_data(init_data(ALICE, start_param=code), TOKEN)
                self.assertIsNotNone(verified)
                self.assertEqual(verified["start_param"], code)

    def test_valid_signed_deep_link_registers_with_source_and_no_approval(self):
        code = self.owner_invite()
        identity = init_data(ALICE, start_param=code)
        status, session = self.post("/api/session", {"initData": identity})
        self.assertEqual(status, 200, session)
        self.assertEqual(session["status"], "invited")
        status, registered = self.post("/api/register", {"initData": identity, **TEST_ONBOARDING})
        self.assertEqual(status, 200, registered)
        self.assertEqual(registered["user"]["status"], "active")
        self.assertEqual(registered["user"]["source"], "agency")
        self.assertEqual(registered["user"]["introduced_by_id"], OWNER)

    def test_nonexistent_signed_start_parameter_does_not_block_open_registration(self):
        identity = init_data(ALICE, start_param="ZXCVB7")
        status, session = self.post("/api/session", {"initData": identity})
        self.assertEqual(status, 200, session)
        self.assertEqual(session["status"], "invited")
        self.assertNotIn("source_info", session)
        status, registered = self.post("/api/register", {"initData": identity, **TEST_ONBOARDING})
        self.assertEqual(status, 200, registered)
        self.assertEqual(registered["user"]["status"], "active")
        self.assertIsNone(registered["user"]["source"])
        self.assertIsNone(registered["user"]["referrer_id"])

    def test_revoked_signed_link_does_not_trap_new_lead(self):
        code = self.owner_invite()
        self.assertEqual(self.as_user("/api/invitations/revoke", OWNER, code=code)[0], 200)
        identity = init_data(BOB, start_param=code)
        status, registered = self.post("/api/register", {"initData": identity, **TEST_ONBOARDING})
        self.assertEqual(status, 200, registered)
        self.assertEqual(registered["user"]["status"], "active")
        self.assertIsNone(registered["user"]["source"])

    def test_new_registration_notifications_do_not_demand_manual_review(self):
        status, registered = self.as_user("/api/register", ALICE)
        self.assertEqual(status, 200, registered)
        with db.transaction() as conn:
            messages = [row[0] for row in conn.execute(
                "SELECT text FROM notifications_outbox "
                "WHERE event_key LIKE 'registration:%' OR event_key LIKE 'register:%'"
            ).fetchall()]
        self.assertGreaterEqual(len(messages), 2)
        self.assertTrue(any("Доступ к опубликованным офферам открыт" in m for m in messages))
        self.assertTrue(any("активирован автоматически" in m for m in messages))
        self.assertFalse(any("ожидает рассмотрения" in m or "на рассмотрение" in m for m in messages))
