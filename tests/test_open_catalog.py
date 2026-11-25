"""Open registration and public catalogue, with isolated participant state."""
import os
import unittest
from unittest.mock import patch

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB


class OpenCatalogueTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    owner_invite = HttpHarness.owner_invite
    webhook_start = HttpHarness.webhook_start

    def register_user(self, uid):
        status, result = self.as_user(
            "/api/register", uid, consent=True, privacy_accepted=True,
            terms_accepted=True, adult_confirmed=True)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["status"], "active")
        return result

    def create_offer(self, category="Дебетовые карты"):
        status, result = self.as_user(
            "/api/admin/mvp/offer", OWNER, name="Открытое предложение",
            category=category, target_action="Оформить карту",
            referral_url="https://example.test/open", payout_rub=1000, hold_days=7)
        self.assertEqual(status, 200, result)
        return result["offer_id"]

    def test_open_registration_and_catalog_without_assignment(self):
        with patch.dict(os.environ, {"PARTNERS_MVP_OPEN_REGISTRATION": "false"}):
            status, session = self.as_user("/api/session", ALICE)
            self.assertEqual(status, 200, session)
            self.assertTrue(session["open_registration"])
            self.register_user(ALICE)
        offer = self.create_offer()
        self.register_user(BOB)
        for uid in (ALICE, BOB):
            status, result = self.as_user("/api/mvp/overview", uid)
            self.assertEqual(status, 200, result)
            item = next(o for o in result["offers"] if o["id"] == offer)
            self.assertTrue(item["can_apply"])
            self.assertFalse(item["is_assigned"])
            self.assertEqual(item["referral_url"], "https://example.test/open")
        status, started = self.as_user("/api/mvp/start", ALICE, offer_id=offer)
        self.assertEqual(status, 200, started)
        self.assertEqual(started["stage"], "in_progress")
        self.assertEqual(self.as_user("/api/mvp/start", ALICE, offer_id=offer)[0], 200)
        status, after = self.as_user("/api/mvp/overview", ALICE)
        self.assertEqual(status, 200, after)
        self.assertTrue(next(o for o in after["offers"] if o["id"] == offer)["is_assigned"])
        status, other = self.as_user("/api/mvp/overview", BOB)
        self.assertEqual(status, 200, other)
        self.assertFalse(next(o for o in other["offers"] if o["id"] == offer)["is_assigned"])
        status, submitted = self.as_user(
            "/api/mvp/submit", BOB, kind="stage", offer_id=offer,
            lead_stage="application_sent", proof_url="https://example.test/proof")
        self.assertEqual(status, 200, submitted)
        self.assertEqual(self.as_user("/api/mvp/my-events", ALICE)[1]["events"], [])
        self.assertEqual(len(self.as_user("/api/mvp/my-events", BOB)[1]["events"]), 1)

    def test_mfo_still_requires_manager_approval(self):
        self.register_user(ALICE)
        offer = self.create_offer("МФО")
        status, view = self.as_user("/api/mvp/overview", ALICE)
        self.assertEqual(status, 200, view)
        item = next(o for o in view["offers"] if o["id"] == offer)
        self.assertTrue(item["requires_request"])
        self.assertFalse(item["can_apply"])
        self.assertEqual(item["unavailable_reason"], "mfo_request")
        self.assertEqual(self.as_user("/api/mvp/start", ALICE, offer_id=offer)[0], 409)
        self.assertEqual(self.as_user(
            "/api/mvp/submit", ALICE, kind="stage", offer_id=offer,
            lead_stage="application_sent", proof_url="https://example.test/proof")[0], 403)
        self.assertEqual(self.as_user(
            "/api/mvp/submit", ALICE, kind="mfo_request", offer_id=offer)[0], 200)

    def test_pending_legacy_user_activates_without_review(self):
        db.initialize()
        with db.transaction() as conn:
            db.ensure_owner(conn, OWNER)
            now = 1764000000
            conn.execute(
                "INSERT INTO users(id,internal_id,first_name,last_name,username,role,status,"
                "agency_id,manager_id,registered_at,updated_at,consent_at) "
                "VALUES(?,?,?,?,?,'lead','pending',?,?,?,?,?)",
                (ALICE, db.allocate_internal_id(conn), "Test", "", "test", OWNER,
                 OWNER, now, now, now))
        status, session = self.as_user("/api/session", ALICE)
        self.assertEqual(status, 200, session)
        self.assertEqual(session["status"], "active")

    def test_blocked_user_does_not_regain_access(self):
        self.register_user(ALICE)
        status, response = self.as_user("/api/admin/decision", OWNER,
                                        user_id=ALICE, decision="block",
                                        reason="QA access restriction")
        self.assertEqual(status, 200, response)
        status, session = self.as_user("/api/session", ALICE)
        self.assertEqual(status, 200, session)
        self.assertEqual(session["status"], "blocked")
        self.assertEqual(self.as_user("/api/mvp/start", ALICE,
                                      offer_id="manual_"+"a"*20)[0], 403)
