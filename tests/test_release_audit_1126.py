"""Isolated HTTP regression contracts for the 26 November release audit.

Reuse the registration harness methods without inheriting its test cases.
"""
import os
import unittest
from unittest.mock import patch

from tests import test_registration as h
from server import bot


class ReleaseAudit1126(unittest.TestCase):
    setUp = h.HttpHarness.setUp
    stop_server = h.HttpHarness.stop_server
    post = h.HttpHarness.post
    as_user = h.HttpHarness.as_user
    owner_invite = h.HttpHarness.owner_invite
    register = h.HttpHarness.register
    webhook_start = h.HttpHarness.webhook_start

    def webhook(self, update_id, uid, **message):
        return self.post("/api/telegram/webhook", {
            "update_id": update_id,
            "message": {"from": {"id": uid}, "chat": {"id": uid, "type": "private"}, **message},
        }, headers={"X-Telegram-Bot-Api-Secret-Token": "header-secret"})

    def test_contact_gate_and_bot_menu_never_inline(self):
        with patch.dict(os.environ, {"PARTNERS_REQUIRE_TELEGRAM_CONTACT": "true"}), \
                patch("server.bot.app_url", return_value="https://example.org/partners/"), \
                patch("server.bot.admin_id", return_value=h.OWNER):
            self.assertEqual(self.as_user("/api/register", h.ALICE)[0], 409)
            status, start = self.webhook(111, h.ALICE, text="/start")
            self.assertEqual(status, 200)
            self.assertTrue(start["reply_markup"]["keyboard"][0][0]["request_contact"])
            self.assertNotIn("inline_keyboard", start["reply_markup"])
            status, wrong = self.webhook(112, h.ALICE,
                                         contact={"user_id": h.BOB, "phone_number": "+79990000001"})
            self.assertEqual(status, 200)
            self.assertNotIn("remove_keyboard", wrong.get("reply_markup", {}))
            self.assertEqual(self.as_user("/api/register", h.ALICE)[0], 409)
            status, confirmed = self.webhook(113, h.ALICE,
                                             contact={"user_id": h.ALICE, "phone_number": "+79990000001"})
            self.assertEqual(status, 200)
            self.assertEqual(confirmed["reply_markup"], {"remove_keyboard": True})
            self.assertNotIn("inline_keyboard", confirmed["reply_markup"])
            status, return_visit = self.webhook(114, h.ALICE, text="/start")
            self.assertEqual(status, 200)
            self.assertEqual(return_visit["reply_markup"], {"remove_keyboard": True})
            self.assertIn("Кабинет", return_visit["text"])
            self.assertEqual(self.as_user("/api/session", h.ALICE)[1]["contact_required"], False)
            self.assertEqual(self.webhook(115, h.ALICE, photo=[{"file_id": "dummy"}])[0], 200)
            owner = bot.response_for({"message": {"from": {"id": h.OWNER},
                                          "chat": {"id": h.OWNER, "type": "private"},
                                          "text": "/start"}}, has_contact=False)
            self.assertEqual(owner["reply_markup"], {"remove_keyboard": True})

    def test_signed_six_character_referral_registration_and_webhook_protection(self):
        invite = self.owner_invite()
        self.assertRegex(invite, r"^[A-Z0-9]{6}$")
        # Signed Mini App start_param must be as authoritative as a verified /start.
        signed = h.init_data(h.ALICE, start_param=invite)
        self.assertEqual(self.post("/api/session", {"initData": signed})[0], 200)
        status, registered = self.post("/api/register", {
            "initData": signed, **h.TEST_ONBOARDING,
        })
        self.assertEqual(status, 200, registered)
        self.assertEqual(registered["user"]["agency_id"], h.OWNER)
        self.assertEqual(registered["user"]["status"], "active")
        self.assertEqual(self.post("/api/telegram/webhook", {
            "update_id": 300, "message": {"from": {"id": h.BOB},
            "chat": {"id": h.BOB, "type": "private"}, "text": "/start " + invite},
        }, headers={"X-Telegram-Bot-Api-Secret-Token": "invalid"})[0], 403)
        self.assertEqual(self.post("/api/admin/users", {"initData": "unsigned"})[0], 401)

    def test_published_catalogue_is_available_not_personally_assigned(self):
        status, participant = self.as_user("/api/register", h.ALICE)
        self.assertEqual(status, 200, participant)
        offer_ids = []
        for i in range(3):
            status, response = self.as_user("/api/admin/mvp/offer", h.OWNER,
                name=f"Published {i}", category="bank", target_action="Submit application",
                instructions="Follow instructions", referral_url="https://example.org/start",
                payout_rub=1000 + i, hold_days=7, active=True)
            self.assertEqual(status, 200, response)
            offer_ids.append(response["offer_id"])
        status, overview = self.as_user("/api/mvp/overview", h.ALICE)
        self.assertEqual(status, 200, overview)
        exposed = [x for x in overview["offers"] if x["id"] in offer_ids]
        self.assertEqual(len(exposed), 3)
        self.assertTrue(all(x["is_assigned"] is False for x in exposed))
        status, snapshot = self.as_user("/api/statistics/overview", h.ALICE)
        self.assertEqual(status, 200, snapshot)
        self.assertEqual(snapshot["assigned_count"], 0)
        self.assertEqual(snapshot["stages"]["assigned"], 0)
        self.assertGreaterEqual(snapshot["potential"]["not_started_rub"], 3003)

    def test_lead_cannot_manage_offers_finance_or_other_participant(self):
        status, participant = self.as_user("/api/register", h.ALICE)
        self.assertEqual(status, 200, participant)
        for route, payload in (
            ("/api/admin/users", {}),
            ("/api/admin/mvp/catalog", {}),
            ("/api/admin/finance/withdrawals", {}),
            ("/api/admin/participant", {"user_id": h.BOB}),
            ("/api/admin/mvp/events", {"status": "all"}),
            ("/api/admin/mvp/evidence", {"event_id": "evt_" + "0" * 24}),
        ):
            with self.subTest(route=route):
                status, result = self.as_user(route, h.ALICE, **payload)
                self.assertEqual(status, 403, result)

    def test_trusted_staff_global_access_preserves_owner_and_self_guards(self):
        for uid in (h.ALICE, h.BOB):
            status, registered = self.as_user("/api/register", uid)
            self.assertEqual(status, 200, registered)
        status, promoted = self.as_user("/api/admin/assign", h.OWNER,
                                        user_id=h.ALICE, role="staff")
        self.assertEqual(status, 200, promoted)
        status, page = self.as_user("/api/admin/users", h.ALICE)
        self.assertEqual(status, 200, page)
        self.assertIn(h.BOB, [entry["id"] for entry in page["users"]])
        for path, payload in (
            ("/api/admin/decision", {"user_id": h.OWNER, "decision": "block", "reason": "test"}),
            ("/api/admin/decision", {"user_id": h.ALICE, "decision": "block", "reason": "test"}),
            ("/api/admin/assign", {"user_id": h.OWNER, "role": "lead"}),
            ("/api/admin/assign", {"user_id": h.ALICE, "role": "owner"}),
        ):
            with self.subTest(path=path, payload=payload):
                status, response = self.as_user(path, h.ALICE, **payload)
                self.assertEqual(status, 403, response)
        # Operational owner profile is readable by trusted staff; role/state mutation stays forbidden.
        status, owner_view = self.as_user("/api/admin/participant", h.ALICE, user_id=h.OWNER)
        self.assertEqual(status, 200, owner_view)
        self.assertEqual(owner_view["user"]["role"], "owner")
