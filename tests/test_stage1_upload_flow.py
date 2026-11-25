"""Stage-1 contact, arbitrary evidence, per-user scope and ordered milestones."""
import base64
import os
import unittest
from unittest.mock import patch

from server import db, offer_workflow
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB
from tests.test_profile_stage6 import TEST_FERNET_KEY


class Stage1UploadFlowTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user

    def setUp(self):
        HttpHarness.setUp(self)
        env = patch.dict(os.environ, {"PARTNERS_PROFILE_ENCRYPTION_KEY": TEST_FERNET_KEY})
        env.start()
        self.addCleanup(env.stop)

    def activate(self, uid):
        status, result = self.as_user("/api/register", uid, consent=True, privacy_accepted=True,
                                      terms_accepted=True, adult_confirmed=True)
        self.assertEqual(status, 200, result)

    def create_offer(self):
        status, result = self.as_user(
            "/api/admin/mvp/offer", OWNER, name="Тестовая карта", category="Дебетовая карта",
            target_action="Оформить", payout_rub=800, hold_days=7,
            lead_stages=["application_sent", "meeting_scheduled"])
        self.assertEqual(status, 200, result)
        return result["offer_id"]

    def test_upload_and_order(self):
        self.activate(ALICE)
        self.activate(BOB)
        offer = self.create_offer()
        raw = b"%PDF-1.7\n" + b"evidence content" * 50
        file = {"name": "document.pdf", "data": base64.b64encode(raw).decode("ascii")}
        payload = {"kind": "stage", "offer_id": offer, "lead_stage": "application_sent", "file": file}
        status, response = self.as_user("/api/mvp/submit", ALICE, **{
            **payload, "lead_stage": "meeting_scheduled"})
        self.assertEqual(status, 409, response)
        status, response = self.as_user("/api/mvp/submit", ALICE, **payload)
        self.assertEqual(status, 200, response)
        event_id = response["event"]["id"]
        self.assertEqual(self.as_user("/api/mvp/submit", ALICE, **payload)[0], 409)
        self.assertEqual(self.as_user("/api/admin/mvp/evidence", BOB, event_id=event_id)[0], 403)
        status, data = self.as_user("/api/admin/mvp/evidence", OWNER, event_id=event_id)
        self.assertEqual(status, 200, data)
        self.assertEqual(base64.b64decode(data["data"]), raw)
        self.assertEqual(data["mime"], "application/pdf")
        self.assertEqual(data["name"], "document.pdf")
        status, events = self.as_user("/api/mvp/my-events", ALICE)
        self.assertEqual(status, 200, events)
        self.assertEqual(events["events"][0]["file_name"], "document.pdf")
        self.assertEqual(self.as_user("/api/admin/mvp/review-event", OWNER,
                                      event_id=event_id, decision="approve")[0], 200)
        self.assertEqual(self.as_user("/api/mvp/submit", ALICE, **payload)[0], 409)
        status, response = self.as_user(
            "/api/mvp/submit", ALICE, kind="stage", offer_id=offer,
            lead_stage="meeting_scheduled",
            file={"name": "archive.zip", "data": base64.b64encode(b"PK\x03\x04safe").decode()})
        self.assertEqual(status, 200, response)
        self.assertEqual(self.as_user("/api/mvp/my-events", BOB)[1]["events"], [])

    def test_file_validation_and_limit(self):
        self.assertRaises(db.Problem, offer_workflow._screenshot,
                          {"name": "evil/path", "data": base64.b64encode(b"ok").decode()})
        self.assertRaises(db.Problem, offer_workflow._screenshot,
                          {"name": "oversize.bin", "data": base64.b64encode(b"x" * 10_000_001).decode()})
        raw, meta = offer_workflow._screenshot(
            {"name": "document without extension", "data": base64.b64encode(b"hello").decode()})
        self.assertEqual(raw, b"hello")
        self.assertIn("application/octet-stream", meta)

    def test_contact_gate_and_in_app_phone(self):
        with patch.dict(os.environ, {"PARTNERS_REQUIRE_TELEGRAM_CONTACT": "true"}):
            status, session = self.as_user("/api/session", ALICE)
            self.assertEqual(status, 200, session)
            self.assertTrue(session["contact_required"])
            self.assertEqual(self.as_user(
                "/api/register", ALICE, consent=True, privacy_accepted=True,
                terms_accepted=True, adult_confirmed=True)[0], 409)
            self.assertEqual(self.as_user("/api/mvp/overview", ALICE)[0], 403)
            self.assertTrue(db.record_contact(992211, ALICE,
                {"user_id": ALICE, "phone_number": "+7 (900) 000-00-00"}))
            status, session = self.as_user("/api/session", ALICE)
            self.assertEqual(status, 200, session)
            self.assertEqual(session["phone"], "+79000000000")
            self.assertFalse(session["contact_required"])
            self.activate(ALICE)
