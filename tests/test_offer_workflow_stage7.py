"""Stage 7 signed HTTP contracts: milestone evidence, staff scopes and MFO gate."""
import base64
import io
import os
import time
import unittest
from unittest.mock import patch

from PIL import Image

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB, TEST_ONBOARDING
from tests.test_profile_stage6 import TEST_FERNET_KEY, VALID_INN


def screenshot():
    buf = io.BytesIO()
    Image.new("RGB", (160, 110), (80, 130, 150)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class Stage7WorkflowTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    owner_invite = HttpHarness.owner_invite
    webhook_start = HttpHarness.webhook_start

    def setUp(self):
        HttpHarness.setUp(self)
        env=patch.dict(os.environ, {
            "PARTNERS_MVP_OPEN_REGISTRATION":"true",
            "PARTNERS_PROFILE_ENCRYPTION_KEY":TEST_FERNET_KEY
        })
        env.start()
        self.addCleanup(env.stop)

    def register_active(self, uid, birth="2000-10-19"):
        status,_=self.as_user("/api/register",uid,**{**TEST_ONBOARDING,"consent":True,"birth_date":birth})
        self.assertEqual(status,200)
        self.assertEqual(self.as_user("/api/admin/decision",OWNER,user_id=uid,decision="approve")[0],200)
        self.assertEqual(self.as_user("/api/profile/identity",uid,
            surname="Иванов",given_name="Иван",patronymic="",inn=VALID_INN)[0],200)

    def offer(self, category="Дебетовые карты", stages=None):
        payload={"name":"Тестовое предложение","category":category,"target_action":"Оформить",
                 "payout_rub":500,"hold_days":7,"referral_url":"https://bank.example.test/go"}
        if stages is not None:
            payload["lead_stages"]=stages
        status,result=self.as_user("/api/admin/mvp/offer",OWNER,**payload)
        self.assertEqual(status,200,result)
        return result["offer_id"]

    def assign(self,uid,offer):
        self.assertEqual(self.as_user("/api/admin/mvp/assignment",OWNER,user_id=uid,offer_id=offer)[0],200)

    def test_stage_evidence_is_encrypted_and_only_staff_can_review(self):
        self.register_active(ALICE)
        self.register_active(BOB)
        offer=self.offer(stages=["application_sent","meeting_scheduled"])
        self.assign(ALICE,offer)
        status,submitted=self.as_user("/api/mvp/submit",ALICE,kind="stage",offer_id=offer,
            lead_stage="application_sent",proof_url="https://example.test/receipt",screenshot=screenshot())
        self.assertEqual(status,200,submitted)
        event_id=submitted["event"]["id"]
        self.assertEqual(submitted["event"]["review_status"],"pending")
        with db.transaction() as conn:
            row=conn.execute("SELECT evidence_data,review_status FROM manual_offer_events WHERE id=?",(event_id,)).fetchone()
            self.assertEqual(row["review_status"],"pending")
            self.assertNotIn(b"RIFF",bytes(row["evidence_data"]))
            self.assertTrue(bytes(row["evidence_data"]).startswith(b"gAAAAA"))
            self.assertEqual(conn.execute("SELECT stage FROM manual_assignments WHERE telegram_id=?",(ALICE,)).fetchone()["stage"],"assigned")
        self.assertEqual(self.as_user("/api/admin/mvp/evidence",ALICE,event_id=event_id)[0],403)
        status,evidence=self.as_user("/api/admin/mvp/evidence",OWNER,event_id=event_id)
        self.assertEqual(status,200,evidence)
        self.assertTrue(base64.b64decode(evidence["data"]).startswith(b"RIFF"))
        self.assertEqual(self.as_user("/api/admin/mvp/review-event",BOB,event_id=event_id,decision="approve")[0],403)
        status,queue=self.as_user("/api/admin/mvp/events",OWNER)
        self.assertEqual(status,200)
        self.assertEqual(len(queue["events"]),1)
        self.assertEqual(queue["events"][0]["proof_url"],"https://example.test/receipt")
        self.assertTrue(queue["events"][0]["has_screenshot"])
        self.assertEqual(self.as_user("/api/mvp/my-events",BOB)[1]["events"],[])
        self.assertEqual(self.as_user("/api/mvp/my-events",ALICE)[1]["events"][0]["id"],event_id)
        self.assertEqual(self.as_user("/api/admin/mvp/review-event",OWNER,event_id=event_id,decision="approve")[0],200)
        self.assertEqual(self.as_user("/api/admin/mvp/review-event",OWNER,event_id=event_id,decision="approve")[0],409)
        view=self.as_user("/api/mvp/overview",ALICE)[1]
        self.assertEqual(view["offers"][0]["stage"],"submitted")
        self.assertEqual(view["offers"][0]["latest_event"]["review_status"],"approved")
        self.assertEqual(view["statistics"]["completed"],0)
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,kind="stage",offer_id=offer,
            lead_stage="application_sent",proof_url="https://example.test/repeat")[0],409)
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,kind="stage",offer_id=offer,
            lead_stage="meeting_scheduled",proof_url="https://example.test/next")[0],200)

    def test_mfo_request_is_required_before_link_or_stage(self):
        self.register_active(ALICE)
        offer=self.offer(category="МФО")
        self.assign(ALICE,offer)
        initial=self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]
        self.assertEqual(initial["unavailable_reason"],"mfo_request")
        self.assertFalse(initial["can_apply"])
        self.assertEqual(initial["referral_url"],"")
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,kind="stage",offer_id=offer,
            lead_stage="application_sent",proof_url="https://example.test/receipt")[0],403)
        status,request=self.as_user("/api/mvp/submit",ALICE,kind="mfo_request",offer_id=offer)
        self.assertEqual(status,200,request)
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,kind="mfo_request",offer_id=offer)[0],409)
        self.assertEqual(self.as_user("/api/admin/mvp/review-event",OWNER,
            event_id=request["event"]["id"],decision="approve")[0],200)
        granted=self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]
        self.assertTrue(granted["can_apply"])
        self.assertTrue(granted["mfo_approved"])
        self.assertEqual(granted["referral_url"],"https://bank.example.test/go")
        self.assertEqual(granted["stage"],"in_progress")
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,kind="stage",offer_id=offer,
            lead_stage="application_sent",proof_url="https://example.test/receipt")[0],200)

    def test_rejected_mfo_request_can_be_submitted_again(self):
        self.register_active(ALICE)
        offer=self.offer(category="МФО")
        self.assign(ALICE,offer)
        first=self.as_user("/api/mvp/submit",ALICE,kind="mfo_request",offer_id=offer)[1]["event"]["id"]
        self.assertEqual(self.as_user("/api/admin/mvp/review-event",OWNER,
            event_id=first,decision="reject",note="Не обнаружена заявка")[0],200)
        view=self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]
        self.assertFalse(view["mfo_approved"])
        self.assertEqual(view["latest_event"]["review_note"],"Не обнаружена заявка")
        second=self.as_user("/api/mvp/submit",ALICE,kind="mfo_request",offer_id=offer)[1]["event"]["id"]
        self.assertNotEqual(first,second)

    def test_stage_requires_assigned_active_adult_and_allowed_stage(self):
        self.register_active(ALICE)
        self.register_active(BOB,birth="2010-10-19")
        offer=self.offer(stages=["application_sent"])
        self.assign(ALICE,offer)
        self.assign(BOB,offer)
        base={"kind":"stage","offer_id":offer,"lead_stage":"application_sent"}
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,**base)[0],400)
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,**{**base,"lead_stage":"credited","proof_url":"https://x.test"})[0],400)
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,**{**base,"lead_stage":"meeting_scheduled","proof_url":"https://x.test"})[0],400)
        self.assertEqual(self.as_user("/api/mvp/submit",BOB,**{**base,"proof_url":"https://x.test"})[0],403)
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,**{**base,"proof_url":"javascript:alert(1)"})[0],400)
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,**{**base,"proof_url":1})[0],400)
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,**{**base,"screenshot":"data:image/svg+xml;base64,PHN2Zz4="})[0],400)
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,**{**base,"proof_url":"https://x.test"})[0],200)
        self.assertEqual(self.as_user("/api/mvp/submit",ALICE,**{**base,"proof_url":"https://x.test"})[0],409)
        self.assertEqual(self.as_user("/api/admin/mvp/events",ALICE)[0],403)
        self.assertEqual(self.as_user("/api/mvp/my-events",BOB)[1]["events"],[])
        self.assertEqual(self.post("/api/mvp/submit",{"initData":"invalid",**base})[0],401)

    def test_staff_reviews_only_assigned_leads_without_bank_payment_permission(self):
        self.register_active(ALICE)
        self.register_active(BOB)
        offer=self.offer()
        self.assign(ALICE,offer)
        self.assign(BOB,offer)
        staff_id, other_staff = 900701, 900702
        now=int(time.time())
        with db.transaction() as conn:
            for worker_id in (staff_id,other_staff):
                conn.execute("INSERT INTO users(id,internal_id,first_name,role,status,agency_id,"
                             "registered_at,updated_at) VALUES(?,?,?,'staff','active',?,?,?)",
                             (worker_id,db.allocate_internal_id(conn),"Менеджер",OWNER,now,now))
            conn.execute("UPDATE users SET manager_id=? WHERE id=?", (staff_id,ALICE))
            conn.execute("UPDATE users SET manager_id=? WHERE id=?", (other_staff,BOB))
        event=self.as_user("/api/mvp/submit",ALICE,kind="stage",offer_id=offer,
                           lead_stage="application_sent",proof_url="https://example.test/proof")[1]["event"]["id"]
        self.assertEqual(self.as_user("/api/admin/mvp/events",staff_id)[1]["events"][0]["id"],event)
        self.assertEqual(self.as_user("/api/admin/mvp/events",other_staff)[1]["events"],[])
        self.assertEqual(self.as_user("/api/admin/mvp/review-event",other_staff,
            event_id=event,decision="approve")[0],403)
        self.assertEqual(self.as_user("/api/admin/mvp/review-event",staff_id,
            event_id=event,decision="approve")[0],200)
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT stage FROM manual_assignments WHERE telegram_id=?",
                                          (ALICE,)).fetchone()["stage"],"submitted")


if __name__=="__main__":
    unittest.main()
