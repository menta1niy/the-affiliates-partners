"""Stage 5: registration data, permanent identity and scoped notifications."""
import os
import time
import unittest
from datetime import date
from unittest.mock import patch

from server import db
from server.registration import age, credit_segment
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB, CAROL, TEST_ONBOARDING


class OnboardingRegistrationTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    owner_invite = HttpHarness.owner_invite
    webhook_start = HttpHarness.webhook_start

    def setUp(self):
        HttpHarness.setUp(self)
        self.open_registration = patch.dict(os.environ, {"PARTNERS_MVP_OPEN_REGISTRATION": "true"})
        self.open_registration.start()
        self.addCleanup(self.open_registration.stop)

    def test_open_registration_records_id_and_survey_only_once(self):
        initial=self.as_user("/api/session",ALICE)[1]
        self.assertIsNone(initial["registration"])
        form={**TEST_ONBOARDING,"consent":True,
              "credit_cards":2,"installments":1,"loans":1,"mortgages":0,
              "birth_date":"2006-10-19"}
        status,registered=self.as_user("/api/register",ALICE,**form)
        self.assertEqual(status,200,registered)
        user=registered["user"]
        self.assertEqual(user["status"],"pending")
        self.assertRegex(user["display_id"],r"^L-\d{6,}$")
        self.assertNotEqual(str(ALICE),user["display_id"])
        status,session=self.as_user("/api/session",ALICE)
        self.assertEqual(status,200)
        self.assertEqual(session["registration"]["birth_date"],"2006-10-19")
        self.assertEqual(session["registration"]["credit_products_total"],4)
        self.assertEqual(session["registration"]["credit_segment"],"high_count")
        self.assertNotIn("birth_date",self.as_user("/api/admin/users",OWNER)[1]["users"][0])
        with db.transaction() as conn:
            before=conn.execute("SELECT count(*) FROM audit WHERE action='mvp_registration'").fetchone()[0]
            events=conn.execute("SELECT chat_id,text FROM notifications_outbox WHERE event_key LIKE 'registration:%' OR event_key LIKE 'register:%'").fetchall()
            self.assertEqual({row["chat_id"] for row in events},{OWNER,ALICE})
            self.assertTrue(all("L-" in row["text"] for row in events))
        status,again=self.as_user("/api/register",ALICE,**{**form,"birth_date":"2000-01-01"})
        self.assertEqual(status,200)
        self.assertEqual(again["user"]["display_id"],user["display_id"])
        self.assertEqual(self.as_user("/api/session",ALICE)[1]["registration"]["birth_date"],"2006-10-19")
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM audit WHERE action='mvp_registration'").fetchone()[0],before)
            self.assertEqual(conn.execute("SELECT count(*) FROM registration_profiles").fetchone()[0],1)
        self.assertEqual(self.as_user("/api/admin/decision",OWNER,user_id=ALICE,decision="reject",reason="Решение модерации")[0],200)
        rejected=self.as_user("/api/session",ALICE)[1]
        self.assertEqual(rejected["user"]["display_id"],user["display_id"])
        self.assertEqual(rejected["user"]["decision_reason"],"Решение модерации")

    def test_invalid_survey_does_not_allocate_id_or_capture_consent(self):
        baseline={**TEST_ONBOARDING,"consent":True}
        bad=(
            {"birth_date":"2026-02-30"},{"birth_date":"3000-01-01"},
            {"birth_date":"1800-01-01"},{"birth_date":"bad"},
            {"birth_date":None},{"privacy_accepted":False},
            {"terms_accepted":False},{"consent":False},
            {"credit_cards":-1},{"credit_cards":3.5},{"credit_cards":"2"},
            {"installments":51},{"mortgages":None},{"loans":True}
        )
        for change in bad:
            with self.subTest(change=change):
                status,_=self.as_user("/api/register",ALICE,**{**baseline,**change})
                self.assertEqual(status,400)
        with db.transaction() as conn:
            self.assertIsNone(db.get_user(conn,ALICE))
            self.assertEqual(conn.execute("SELECT count(*) FROM registration_profiles").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM notifications_outbox WHERE event_key LIKE 'registration:%'").fetchone()[0],0)

    def test_open_referral_keeps_source_without_crm_outbox(self):
        code=self.owner_invite()
        self.assertEqual(self.webhook_start(991125,ALICE,code)[0],200)
        status,response=self.as_user("/api/register",ALICE,consent=True)
        self.assertEqual(status,200,response)
        self.assertEqual(response["user"]["source"],"agency")
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM crm_registration_outbox").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM registration_profiles").fetchone()[0],1)

    def test_blogger_ad_link_registers_lead_not_blogger_account(self):
        self.assertEqual(self.as_user("/api/session",OWNER)[0],200)
        blogger_uuid="123e4567-e89b-42d3-a456-426614174000"
        self.assertEqual(db.receive_crm_event({
            "event_id":"stage5-blogger-bound",
            "type":"blogger.bound",
            "blogger_uuid":blogger_uuid,
            "channel":"@test_affiliate_campaign",
            "issuer_id":OWNER,
            "active":True,
        })["changed"],True)
        status,invite=self.as_user("/api/admin/invitations/blogger",OWNER,blogger_uuid=blogger_uuid)
        self.assertEqual(status,200,invite)
        self.assertEqual(self.webhook_start(991127,CAROL,invite["code"])[0],200)
        status,created=self.as_user("/api/register",CAROL,consent=True)
        self.assertEqual(status,200,created)
        self.assertEqual(created["user"]["source"],"blogger")
        self.assertEqual(created["user"]["role"],"lead")
        self.assertRegex(created["user"]["display_id"],r"^L-\d{6,}$")
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM crm_registration_outbox").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM registration_profiles WHERE telegram_id=?",(CAROL,)).fetchone()[0],1)

    def test_notifications_only_to_approvers_of_user_agency(self):
        db.initialize()
        now=int(time.time())
        manager,local_admin,foreign_admin=900821,900822,900823
        with db.transaction() as conn:
            db.ensure_owner(conn,OWNER)
            for uid,role,agency in ((manager,"staff",OWNER),(local_admin,"admin",OWNER),
                                    (foreign_admin,"admin",foreign_admin)):
                conn.execute(
                    "INSERT INTO users(id,internal_id,first_name,role,status,agency_id,registered_at,updated_at) "
                    "VALUES(?,?,? ,?,'active',?,?,?)",
                    (uid,db.allocate_internal_id(conn),"Test",role,agency,now,now))
        code=self.as_user("/api/admin/invitations",OWNER,assignee_id=manager)[1]["invite_code"]
        self.assertEqual(self.webhook_start(991126,BOB,code)[0],200)
        status,response=self.as_user("/api/register",BOB,consent=True)
        self.assertEqual(status,200,response)
        with db.transaction() as conn:
            recipients={r["chat_id"] for r in conn.execute(
                "SELECT chat_id FROM notifications_outbox WHERE event_key LIKE 'registration:%' OR event_key LIKE 'register:%'")}
            self.assertEqual(recipients,{OWNER,manager,local_admin,BOB})
            self.assertNotIn(foreign_admin,recipients)

    def test_age_and_credit_category_are_non_predictive(self):
        self.assertEqual(age("2006-10-19",today=date(2026,10,18)),19)
        self.assertEqual(age("2006-10-19",today=date(2026,10,19)),20)
        base={"credit_cards":0,"installments":0,"loans":0,"mortgages":0}
        self.assertEqual(credit_segment(base),"low_count")
        self.assertEqual(credit_segment({**base,"credit_cards":2}),"medium_count")
        self.assertEqual(credit_segment({**base,"loans":4}),"high_count")


if __name__=="__main__":
    unittest.main()
