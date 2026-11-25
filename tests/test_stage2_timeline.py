"""Signed HTTP integration: synchronized lead/admin milestone timeline and files."""
import base64
import os
import time
import unittest
from unittest.mock import patch

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB
from tests.test_profile_stage6 import TEST_FERNET_KEY


class Stage2TimelineTests(unittest.TestCase):
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user

    def setUp(self):
        HttpHarness.setUp(self)
        env=patch.dict(os.environ, {"PARTNERS_PROFILE_ENCRYPTION_KEY":TEST_FERNET_KEY})
        env.start()
        self.addCleanup(env.stop)

    def activate(self, user):
        status, payload=self.as_user(
            "/api/register", user, consent=True, privacy_accepted=True,
            terms_accepted=True, adult_confirmed=True)
        self.assertEqual(status,200,payload)

    def test_two_stages_with_private_files_and_admin_timeline(self):
        self.activate(ALICE);self.activate(BOB)
        status,payload=self.as_user(
            "/api/admin/mvp/offer",OWNER,name="Тест два этапа",category="Дебетовая карта",
            target_action="Открыть",payout_rub=1230,hold_days=9,
            lead_stages=["application_sent","meeting_scheduled"])
        self.assertEqual(status,200,payload)
        offer=payload["offer_id"]
        self.assertEqual(self.as_user("/api/mvp/start",ALICE,offer_id=offer)[0],200)
        raw=b"%PDF-1.7\nproof stage one"
        first={"kind":"stage","offer_id":offer,"lead_stage":"application_sent",
               "file":{"name":"stage-one.pdf","data":base64.b64encode(raw).decode()}}
        status,submitted=self.as_user("/api/mvp/submit",ALICE,**first)
        self.assertEqual(status,200,submitted)
        event_id=submitted["event"]["id"]
        self.assertEqual(self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]["stage"],"submitted")
        self.assertEqual(self.as_user("/api/mvp/evidence",BOB,event_id=event_id)[0],404)
        self.assertEqual(self.as_user("/api/mvp/evidence",OWNER,event_id=event_id)[0],403)
        status,own_file=self.as_user("/api/mvp/evidence",ALICE,event_id=event_id)
        self.assertEqual(status,200,own_file)
        self.assertEqual((own_file["name"],own_file["mime"]),("stage-one.pdf","application/pdf"))
        self.assertEqual(base64.b64decode(own_file["data"]),raw)
        status,detail=self.as_user("/api/admin/participant",OWNER,user_id=ALICE)
        self.assertEqual(status,200,detail)
        self.assertEqual(detail["offer_events"][0]["file_name"],"stage-one.pdf")
        self.assertTrue(detail["offer_events"][0]["has_screenshot"])
        self.assertEqual(detail["manual"]["offers"][0]["stage"],"submitted")
        self.assertEqual(self.as_user(
            "/api/admin/mvp/review-event",OWNER,event_id=event_id,decision="approve")[0],200)
        status,events=self.as_user("/api/mvp/my-events",ALICE,offer_id=offer)
        self.assertEqual(status,200,events)
        self.assertEqual(len(events["events"]),1)
        self.assertEqual(events["events"][0]["review_status"],"approved")
        self.assertIsNotNone(events["events"][0]["reviewed_at"])
        self.assertEqual(events["events"][0]["offer_name"],"Тест два этапа")
        overview=self.as_user("/api/mvp/overview",ALICE)[1]
        self.assertEqual(overview["offers"][0]["stage"],"in_progress")
        self.assertEqual(overview["offers"][0]["next_stage"],"meeting_scheduled")
        status,next_event=self.as_user(
            "/api/mvp/submit",ALICE,kind="stage",offer_id=offer,
            lead_stage="meeting_scheduled",
            file={"name":"proof.txt","data":base64.b64encode(b"second step").decode()})
        self.assertEqual(status,200,next_event)
        self.assertEqual(self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]["stage"],"submitted")
        self.assertEqual(self.as_user(
            "/api/admin/mvp/review-event",OWNER,event_id=next_event["event"]["id"],
            decision="approve")[0],200)
        final=self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]
        self.assertEqual(final["stage"],"submitted")
        self.assertIsNone(final["next_stage"])
        self.assertEqual(self.as_user("/api/mvp/my-events",BOB,offer_id=offer)[1]["events"],[])

    def test_staff_scoped_details_without_finance(self):
        self.activate(ALICE);self.activate(BOB)
        staff_id=800761
        now=int(time.time())
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO users(id,internal_id,first_name,role,status,agency_id,registered_at,updated_at) "
                "VALUES(?,?,?,'staff','active',?,?,?)",
                (staff_id,db.allocate_internal_id(conn),"Менеджер",OWNER,now,now))
            conn.execute("UPDATE users SET manager_id=? WHERE id=?", (staff_id,ALICE))
        status,detail=self.as_user("/api/admin/participant",staff_id,user_id=ALICE)
        self.assertEqual(status,200,detail)
        self.assertEqual(detail["manual"]["offers"],[])
        self.assertIn("offer_events",detail)
        self.assertNotIn("finance",detail)
        self.assertNotIn("statistics",detail)
        self.assertEqual(self.as_user("/api/admin/participant",staff_id,user_id=BOB)[0],403)
