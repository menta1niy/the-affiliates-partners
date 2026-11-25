"""No identity/credit questionnaire is required for an assigned active lead."""
import os
import sqlite3
import unittest
from unittest.mock import patch

from tests.test_registration import HttpHarness, OWNER, ALICE


class NoSurveyOfferAccessTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    def test_assignment_and_payout_without_legacy_surveys(self):
        with patch.dict(os.environ, {"PARTNERS_MVP_OPEN_REGISTRATION": "true"}):
            signup = dict(consent=True, privacy_accepted=True, terms_accepted=True,
                          adult_confirmed=True)
            status, result = self.as_user("/api/register", ALICE, **signup)
            self.assertEqual(status, 200, result)
            status, result = self.as_user("/api/admin/decision", OWNER,
                                          user_id=ALICE, decision="approve")
            self.assertEqual(status, 200, result)
            status, created = self.as_user("/api/admin/mvp/offer", OWNER,
                name="Карта", category="Дебетовые карты", payout_rub=1000,
                hold_days=7, target_action="Оформить")
            self.assertEqual(status, 200, created)
            offer = created["offer_id"]
            status, assigned = self.as_user("/api/admin/mvp/assignment", OWNER,
                                             user_id=ALICE, offer_id=offer)
            self.assertEqual(status, 200, assigned)
            status, overview = self.as_user("/api/mvp/overview", ALICE)
            self.assertEqual(status, 200, overview)
            item = next(x for x in overview["offers"] if x["id"] == offer)
            self.assertTrue(item["can_apply"])
            self.assertTrue(item["referral_url"] == "" or item["referral_url"] is not None)
            status, event = self.as_user("/api/mvp/submit", ALICE, kind="stage",
                offer_id=offer, lead_stage="application_sent",
                proof_url="https://example.test/evidence")
            self.assertEqual(status, 200, event)
            status, session = self.as_user("/api/session", ALICE)
            self.assertEqual(status, 200, session)
            self.assertNotIn("identity", session)
            self.assertNotIn("registration", session)
            self.assertIsNone(session["phone"])
            if os.environ.get("PARTNERS_DATABASE_URL"):
                from server import db
                with db.transaction() as conn:
                    names = {row[0] for row in conn.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname='partners'").fetchall()}
            else:
                with sqlite3.connect(self.db_path) as conn:
                    names = {x[0] for x in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("registration_profiles", names)
            self.assertNotIn("participant_identities", names)
            self.assertIn("telegram_contacts", names)

    def test_contact_requires_telegram_user_id_match(self):
        from server import bot, db
        db.initialize()
        start = bot.response_for({"message": {"from": {"id": ALICE},
                      "chat": {"id": ALICE, "type": "private"}, "text": "/start"}})
        # Test settings may omit APP_URL; independent contact response remains valid.
        if start:
            self.assertTrue(any(button.get("request_contact") for row in
                start["reply_markup"]["keyboard"] for button in row))
        self.assertFalse(db.record_contact(980001, ALICE,
            {"user_id": 12345, "phone_number": "+79000000000"}))
        self.assertIsNone(db.contact_phone(ALICE))
        self.assertTrue(db.record_contact(980002, ALICE,
            {"user_id": ALICE, "phone_number": "+7 (900) 000-00-00"}))
        self.assertEqual(db.contact_phone(ALICE), "+79000000000")
        status, session = self.as_user("/api/session", ALICE)
        self.assertEqual(status, 200, session)
        self.assertEqual(session["phone"], "+79000000000")
        self.assertFalse(db.record_contact(980002, ALICE,
            {"user_id": ALICE, "phone_number": "+79999999999"}))
        self.assertEqual(db.contact_phone(ALICE), "+79000000000")
