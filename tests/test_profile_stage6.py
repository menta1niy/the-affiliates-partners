"""Stage 6: sensitive profile fields, INN checksum and server-side offer gating."""
import os
import time
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB, TEST_ONBOARDING

VALID_INN = "500100732259"
TEST_FERNET_KEY = Fernet.generate_key().decode("ascii")


class ProfileStage6Tests(unittest.TestCase):
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

    def register_active(self, uid, birth_date="2004-10-19"):
        status,_=self.as_user("/api/register",uid,**{**TEST_ONBOARDING,"consent":True,"birth_date":birth_date})
        self.assertEqual(status,200)
        status,_=self.as_user("/api/admin/decision",OWNER,user_id=uid,decision="approve")
        self.assertEqual(status,200)

    def offer(self, category):
        status,result=self.as_user("/api/admin/mvp/offer",OWNER,
            name="Оффер тест",category=category,target_action="Оформить",
            payout_rub=500,hold_days=7,referral_url="https://bank.example.test/go")
        self.assertEqual(status,200,result)
        return result["offer_id"]

    def assign(self, uid, offer_id):
        self.assertEqual(self.as_user("/api/admin/mvp/assignment",OWNER,
            user_id=uid,offer_id=offer_id)[0],200)

    def save_identity(self,uid,**changes):
        payload={"surname":"Иванов","given_name":"Иван","patronymic":"Иванович","inn":VALID_INN}
        payload.update(changes)
        return self.as_user("/api/profile/identity",uid,**payload)

    def test_adult_without_identity_cannot_get_offer_url_and_can_unlock(self):
        self.register_active(ALICE)
        offer=self.offer("Дебетовые карты")
        self.assign(ALICE,offer)
        before=self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]
        self.assertFalse(before["can_apply"])
        self.assertEqual(before["unavailable_reason"],"identity")
        self.assertEqual(before["referral_url"],"")
        self.assertEqual(self.save_identity(ALICE)[0],200)
        session=self.as_user("/api/session",ALICE)[1]
        self.assertTrue(session["identity"]["complete"])
        self.assertEqual(session["identity"]["inn_masked"],"********2259")
        self.assertNotIn("inn",session["identity"])
        after=self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]
        self.assertTrue(after["can_apply"])
        self.assertEqual(after["referral_url"],"https://bank.example.test/go")
        with db.transaction() as conn:
            row=conn.execute("SELECT full_name_encrypted,inn_encrypted FROM participant_identities").fetchone()
            self.assertNotIn("Иванов",row["full_name_encrypted"])
            self.assertNotIn(VALID_INN,row["inn_encrypted"])
            events=conn.execute("SELECT details FROM audit WHERE action='participant_identity_saved'").fetchall()
            self.assertEqual([item["details"] for item in events],["updated"])
        self.assertNotIn("inn",str(self.as_user("/api/admin/users",OWNER)[1]))

    def test_minor_is_always_unavailable_even_after_identity_and_credit_update(self):
        self.register_active(ALICE,birth_date="2010-10-19")
        offer=self.offer("Кредитные карты")
        self.assign(ALICE,offer)
        self.assertEqual(self.save_identity(ALICE)[0],200)
        self.assertEqual(self.as_user("/api/profile/credit-survey",ALICE,
            credit_cards=0,installments=0,loans=0,mortgages=0)[0],200)
        result=self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]
        self.assertEqual(result["unavailable_reason"],"underage")
        self.assertFalse(result["can_apply"])
        self.assertEqual(result["referral_url"],"")
        # Minors may invite friends: their referral link doesn't unlock offers.
        status,referral=self.as_user("/api/invitations/referral",ALICE)
        self.assertEqual(status,200)
        code=referral["code"]
        self.assertEqual(self.webhook_start(993507,BOB,code)[0],200)
        status,new_user=self.as_user("/api/register",BOB,consent=True)
        self.assertEqual(status,200,new_user)
        self.assertEqual(new_user["user"]["referrer_id"],ALICE)

    def test_credit_offer_needs_fresh_survey_and_unauthorized_update_is_denied(self):
        self.register_active(ALICE)
        credit=self.offer("МФО")
        debit=self.offer("Дебетовые карты")
        for offer_id in (credit,debit):
            self.assign(ALICE,offer_id)
        self.assertEqual(self.save_identity(ALICE)[0],200)
        with db.transaction() as conn:
            conn.execute("UPDATE registration_profiles SET credit_updated_at=? WHERE telegram_id=?",
                         (int(time.time())-31*86400,ALICE))
        response=self.as_user("/api/mvp/overview",ALICE)[1]["offers"]
        by_type={item["category"]:item for item in response}
        self.assertFalse(by_type["МФО"]["can_apply"])
        self.assertEqual(by_type["МФО"]["unavailable_reason"],"credit_review")
        self.assertTrue(by_type["Дебетовые карты"]["can_apply"])
        status,result=self.as_user("/api/profile/credit-survey",ALICE,
            credit_cards=2,installments=0,loans=1,mortgages=0)
        self.assertEqual(status,200,result)
        self.assertEqual(result["registration"]["credit_products_total"],3)
        self.assertEqual(result["registration"]["credit_segment"],"medium_count")
        # A fresh survey removes the credit-review hold; stage 7 still requires
        # manager approval before disclosing an MFO link.
        refreshed={item["category"]:item for item in self.as_user("/api/mvp/overview",ALICE)[1]["offers"]}
        self.assertTrue(refreshed["Дебетовые карты"]["can_apply"])
        self.assertNotEqual(refreshed["МФО"]["unavailable_reason"],"credit_review")
        self.assertEqual(self.as_user("/api/profile/credit-survey",BOB,
            credit_cards=0,installments=0,loans=0,mortgages=0)[0],403)

    def test_credit_band_updates_without_inventing_card_counts(self):
        self.register_active(ALICE)
        status,result=self.as_user("/api/profile/credit-survey",ALICE,credit_band="3+")
        self.assertEqual(status,200,result)
        self.assertEqual(result["registration"]["credit_band"],"3+")
        with db.transaction() as conn:
            row=conn.execute("SELECT credit_band,credit_cards,installments,loans,mortgages FROM registration_profiles WHERE telegram_id=?",(ALICE,)).fetchone()
        self.assertEqual(row["credit_band"],"3+")
        self.assertEqual(tuple(row[field] for field in ("credit_cards","installments","loans","mortgages")),(0,0,0,0))

    def test_invalid_inn_missing_key_and_input_guard(self):
        self.register_active(ALICE)
        for changes in (
            {"inn":"500100732258"}, {"inn":"111111111111"},
            {"inn":"123"}, {"inn":123456789012},
            {"surname":"Тест123"}, {"surname":""},
            {"given_name":"<script>"},{"patronymic":"Иванович\nДругой"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.save_identity(ALICE,**changes)[0],400)
        with patch.dict(os.environ,{"PARTNERS_PROFILE_ENCRYPTION_KEY":""}):
            self.assertEqual(self.save_identity(ALICE)[0],503)
        self.assertEqual(self.save_identity(BOB)[0],403)
        self.assertEqual(self.post("/api/profile/identity",{"initData":"invalid",
            "surname":"Иванов","given_name":"Иван","inn":VALID_INN})[0],401)
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM participant_identities").fetchone()[0],0)

    def test_existing_account_can_fill_missing_survey_without_new_id(self):
        db.initialize()
        now=int(time.time())
        with db.transaction() as conn:
            db.ensure_owner(conn,OWNER)
            old_id=db.allocate_internal_id(conn)
            conn.execute("INSERT INTO users(id,internal_id,first_name,role,status,agency_id,"
                         "registered_at,updated_at) VALUES(?,?,?,'lead','active',?,?,?)",
                         (ALICE,old_id,"Старый",OWNER,now,now))
        before=self.as_user("/api/mvp/overview",ALICE)[1]
        self.assertEqual(before["offers"],[])
        self.assertEqual(self.save_identity(ALICE)[0],409)
        status,updated=self.as_user("/api/profile/onboarding",ALICE,
            **{**TEST_ONBOARDING,"consent":True})
        self.assertEqual(status,200,updated)
        self.assertEqual(updated["id_unchanged"],old_id)
        self.assertEqual(self.as_user("/api/session",ALICE)[1]["user"]["internal_id"],old_id)
        self.assertEqual(self.as_user("/api/profile/onboarding",ALICE,
            **{**TEST_ONBOARDING,"consent":True})[0],409)
        self.assertEqual(self.save_identity(ALICE)[0],200)
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM users WHERE id=?",(ALICE,)).fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT count(*) FROM registration_profiles WHERE telegram_id=?",(ALICE,)).fetchone()[0],1)


if __name__=="__main__":
    unittest.main()
