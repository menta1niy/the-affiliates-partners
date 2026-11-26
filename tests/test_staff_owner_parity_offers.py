"""Owner, admin and staff share operational permissions across all participants."""
import base64
import time
import unittest

from server import db
from tests.test_registration import HttpHarness, OWNER


class StaffOwnerParityOffersTests(unittest.TestCase):
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    stop_server = HttpHarness.stop_server

    def setUp(self):
        HttpHarness.setUp(self)
        self.staff, self.admin, self.lead, self.other_lead = 891001, 891002, 891003, 891004
        db.initialize()
        now = int(time.time())
        with db.transaction() as conn:
            db.ensure_owner(conn, OWNER)
            for agency_id in (999101, 999102, 999103):
                conn.execute("INSERT INTO users(id,first_name,role,status,agency_id,registered_at,updated_at) "
                             "VALUES(?,'Agency','staff','active',?,?,?)",
                             (agency_id, OWNER, now, now))
            for uid, role, agency, manager in [
                (self.staff, "staff", 999101, None),
                (self.admin, "admin", 999102, None),
                (self.lead, "lead", 999103, None),
                (self.other_lead, "lead", OWNER, OWNER),
            ]:
                conn.execute("INSERT INTO users(id,first_name,role,status,agency_id,manager_id,"
                             "registered_at,updated_at) VALUES(?,'Tester',?,'active',?,?,?,?)",
                             (uid, role, agency, manager, now, now))

    def offer(self, actor=OWNER, category="Дебетовая карта"):
        status, body = self.as_user("/api/admin/mvp/offer", actor, name="QA offer",
            category=category, target_action="Оформить", payout_rub=950, hold_days=7,
            referral_url="https://example.test/offer", lead_stages=["application_sent", "product_received"])
        self.assertEqual(status, 200, body)
        return body["offer_id"]

    def test_catalog_crud_assign_bulk_and_global_candidates(self):
        for actor in (OWNER, self.admin, self.staff):
            with self.subTest(actor=actor):
                offer = self.offer(actor)
                code, page = self.as_user("/api/admin/mvp/catalog", actor)
                self.assertEqual(code, 200, page)
                self.assertIn(offer, [item["id"] for item in page["offers"]])
                self.assertEqual(self.as_user("/api/admin/mvp/offer", actor, offer_id=offer,
                    name="Edited", category="Дебетовая карта", target_action="Оформить",
                    payout_rub=950, hold_days=7)[0], 200)
                code, candidates = self.as_user("/api/admin/mvp/assignment-candidates", actor)
                self.assertEqual(code, 200, candidates)
                self.assertTrue({self.lead, self.other_lead}.issubset(
                    {row["id"] for row in candidates["users"]}))
                self.assertEqual(self.as_user("/api/admin/mvp/assignment", actor,
                    user_id=self.lead, offer_id=offer)[0], 200)
                code, result = self.as_user("/api/admin/mvp/bulk-assignment", actor,
                    mode="offer_to_leads", offer_id=offer, user_ids=[self.other_lead])
                self.assertEqual(code, 200, result)
                self.assertEqual(result["created"], 1)
                self.assertEqual(self.as_user("/api/admin/mvp/offer/delete", actor,
                    offer_id=offer)[0], 200)

    def test_review_optional_proof_global_evidence_and_stage_progression(self):
        offer = self.offer()
        self.assertEqual(self.as_user("/api/mvp/start", self.lead, offer_id=offer)[0], 200)
        raw = b"PK\x03\x04proof data"
        code, reported = self.as_user("/api/mvp/submit", self.lead,
            offer_id=offer, kind="stage", lead_stage="product_received",
            file={"name": "proof.custom", "data": base64.b64encode(raw).decode()})
        self.assertEqual(code, 200, reported)
        event_id = reported["event"]["id"]
        self.assertEqual(self.as_user("/api/mvp/submit", self.lead, offer_id=offer,
            kind="stage", lead_stage="application_sent")[0], 409)
        for actor in (OWNER, self.admin, self.staff):
            code, queue = self.as_user("/api/admin/mvp/events", actor)
            self.assertEqual(code, 200, queue)
            self.assertIn(event_id, [row["id"] for row in queue["events"]])
            code, proof = self.as_user("/api/admin/mvp/evidence", actor, event_id=event_id)
            self.assertEqual(code, 200, proof)
            self.assertEqual(base64.b64decode(proof["data"]), raw)
        self.assertEqual(self.as_user("/api/admin/mvp/evidence", self.other_lead,
            event_id=event_id)[0], 403)
        self.assertEqual(self.as_user("/api/mvp/evidence", self.other_lead,
            event_id=event_id)[0], 404)
        self.assertEqual(self.as_user("/api/admin/mvp/review-event", self.staff,
            event_id=event_id, decision="approve")[0], 200)
        self.assertEqual(self.as_user("/api/admin/mvp/review-event", self.admin,
            event_id=event_id, decision="approve")[0], 409)
        code, second = self.as_user("/api/mvp/submit", self.lead, offer_id=offer,
            kind="stage", lead_stage="application_sent")
        self.assertEqual(code, 200, second)
        self.assertEqual(self.as_user("/api/admin/mvp/review-event", self.admin,
            event_id=second["event"]["id"], decision="approve")[0], 200)
        code, overview = self.as_user("/api/mvp/overview", self.lead)
        self.assertEqual(code, 200, overview)
        self.assertEqual(next(item for item in overview["offers"] if item["id"] == offer)["stage"],
                         "submitted")

    def test_mfo_request_is_still_mandatory_and_reviewable_by_staff(self):
        offer = self.offer(category="МФО")
        self.assertEqual(self.as_user("/api/mvp/start", self.lead, offer_id=offer)[0], 409)
        self.assertEqual(self.as_user("/api/mvp/submit", self.lead,
            kind="stage", offer_id=offer, lead_stage="application_sent")[0], 403)
        code, request = self.as_user("/api/mvp/submit", self.lead,
            kind="mfo_request", offer_id=offer)
        self.assertEqual(code, 200, request)
        self.assertEqual(self.as_user("/api/admin/mvp/review-event", self.staff,
            event_id=request["event"]["id"], decision="approve")[0], 200)
        self.assertEqual(self.as_user("/api/mvp/submit", self.lead,
            kind="stage", offer_id=offer, lead_stage="product_received")[0], 200)
