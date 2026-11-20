"""Stage 8 exact-ruble accounting, reservation and manual payout lifecycle."""
import os
import time
import unittest
from unittest.mock import patch

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB, TEST_ONBOARDING
from tests.test_profile_stage6 import TEST_FERNET_KEY, VALID_INN


class Stage8FinanceTests(unittest.TestCase):
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

    def ready(self, uid):
        status,_=self.as_user("/api/register",uid,**{**TEST_ONBOARDING,"consent":True})
        self.assertEqual(status,200)
        self.assertEqual(self.as_user("/api/admin/decision",OWNER,user_id=uid,decision="approve")[0],200)
        self.assertEqual(self.as_user("/api/profile/identity",uid,
            surname="Иванов",given_name="Иван",inn=VALID_INN)[0],200)

    def offer(self,uid):
        status,record=self.as_user("/api/admin/mvp/offer",OWNER,name="Карта",
            category="Дебетовые карты",target_action="Оформить",payout_rub=1000,hold_days=7)
        self.assertEqual(status,200,record)
        offer_id=record["offer_id"]
        self.assertEqual(self.as_user("/api/admin/mvp/assignment",OWNER,
                                     user_id=uid,offer_id=offer_id)[0],200)
        return offer_id

    def credit(self,uid,offer,amount,ref):
        return self.as_user("/api/admin/finance/accrue",OWNER,user_id=uid,
                            offer_id=offer,amount_rub=amount,source_reference=ref)

    def test_balance_reservation_refund_and_paid_are_exact(self):
        self.ready(ALICE)
        offer=self.offer(ALICE)
        self.assertEqual(self.as_user("/api/finance/overview",ALICE)[1]["balances"],
            {"accrued_rub":0,"paid_rub":0,"reserved_rub":0,"available_rub":0})
        self.assertEqual(self.as_user("/api/finance/withdraw",ALICE,amount_rub=1)[0],409)
        self.assertEqual(self.credit(ALICE,offer,1200,"bank.accrual.20261120")[0],200)
        self.assertEqual(self.credit(ALICE,offer,1200,"bank.accrual.20261120")[0],409)
        self.assertEqual(self.as_user("/api/finance/overview",ALICE)[1]["balances"]["available_rub"],1200)
        status,first=self.as_user("/api/finance/withdraw",ALICE,amount_rub=700)
        self.assertEqual(status,200,first)
        first_id=first["withdrawal"]["id"]
        self.assertEqual(first["balances"]["reserved_rub"],700)
        self.assertEqual(first["balances"]["available_rub"],500)
        self.assertEqual(self.as_user("/api/finance/withdraw",ALICE,amount_rub=501)[0],409)
        status,second=self.as_user("/api/finance/withdraw",ALICE,amount_rub=500)
        self.assertEqual(status,200,second)
        self.assertEqual(second["balances"]["available_rub"],0)
        self.assertEqual(self.as_user("/api/admin/finance/decision",OWNER,
            withdrawal_id=first_id,decision="paid",payment_reference="bank.paid.1")[0],409)
        confirmed=self.as_user("/api/admin/finance/decision",OWNER,
            withdrawal_id=first_id,decision="confirm")
        self.assertEqual(confirmed[0],200)
        self.assertEqual(confirmed[1]["balances"]["reserved_rub"],1200)
        self.assertEqual(self.as_user("/api/admin/finance/decision",OWNER,
            withdrawal_id=first_id,decision="confirm")[0],409)
        paid=self.as_user("/api/admin/finance/decision",OWNER,
            withdrawal_id=first_id,decision="paid",payment_reference="bank.paid.1")
        self.assertEqual(paid[0],200)
        self.assertEqual(paid[1]["balances"],
                         {"accrued_rub":1200,"paid_rub":700,"reserved_rub":500,"available_rub":0})
        self.assertEqual(self.as_user("/api/admin/finance/decision",OWNER,
            withdrawal_id=first_id,decision="paid",payment_reference="bank.paid.1")[0],409)
        rejected=self.as_user("/api/admin/finance/decision",OWNER,
            withdrawal_id=second["withdrawal"]["id"],decision="reject",note="Нет оснований")
        self.assertEqual(rejected[0],200)
        self.assertEqual(rejected[1]["balances"],
                         {"accrued_rub":1200,"paid_rub":700,"reserved_rub":0,"available_rub":500})
        self.assertEqual(self.as_user("/api/finance/overview",ALICE)[1]["withdrawals"][0]["status"],"rejected")
        self.assertEqual(self.as_user("/api/admin/finance/withdrawals",OWNER,status="all")[1]["withdrawals"][0]["status"],"rejected")

    def test_manual_assignment_or_lead_stage_does_not_create_money(self):
        self.ready(ALICE)
        offer=self.offer(ALICE)
        self.assertEqual(self.as_user("/api/admin/mvp/assignment",OWNER,
            user_id=ALICE,offer_id=offer,stage="completed")[0],200)
        self.assertEqual(self.as_user("/api/finance/overview",ALICE)[1]["balances"]["accrued_rub"],0)
        self.assertEqual(self.as_user("/api/finance/withdraw",ALICE,amount_rub=1000)[0],409)

    def test_ids_sources_and_financial_roles_are_guarded(self):
        self.ready(ALICE)
        self.ready(BOB)
        offer=self.offer(ALICE)
        self.assertEqual(self.as_user("/api/admin/finance/accrue",BOB,
            user_id=ALICE,offer_id=offer,amount_rub=999,source_reference="fake.aa")[0],403)
        self.assertEqual(self.as_user("/api/finance/overview",BOB)[1]["balances"]["available_rub"],0)
        for invalid in (True,1.5,0,-1,"100",10_000_001):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.credit(ALICE,offer,invalid,"abc.def.1")[0],400)
        self.assertEqual(self.credit(ALICE,offer,300,"a")[0],400)
        self.assertEqual(self.credit(ALICE,offer,300,"abc.def.2")[0],200)
        self.assertEqual(self.as_user("/api/admin/finance/accrue",OWNER,user_id=BOB,
            offer_id=offer,amount_rub=300,source_reference="abc.def.3")[0],409)
        self.assertEqual(self.as_user("/api/finance/withdraw",BOB,amount_rub=1)[0],409)
        self.assertEqual(self.post("/api/finance/withdraw",{"initData":"invalid","amount_rub":1})[0],401)
        self.assertEqual(self.as_user("/api/admin/finance/withdrawals",ALICE)[0],403)
        self.assertEqual(self.as_user("/api/admin/finance/decision",ALICE,
            withdrawal_id="wd_"+"a"*24,decision="confirm")[0],403)

    def test_manager_can_view_own_requests_but_cannot_accrue_or_pay(self):
        self.ready(ALICE)
        self.ready(BOB)
        offer=self.offer(ALICE)
        manager,other_manager=900810,900811
        now=int(time.time())
        with db.transaction() as conn:
            for person in (manager,other_manager):
                conn.execute("INSERT INTO users(id,internal_id,first_name,role,status,agency_id,"
                             "registered_at,updated_at) VALUES(?,?,?,'staff','active',?,?,?)",
                             (person,db.allocate_internal_id(conn),"Менеджер",OWNER,now,now))
            conn.execute("UPDATE users SET manager_id=? WHERE id=?", (manager,ALICE))
            conn.execute("UPDATE users SET manager_id=? WHERE id=?", (other_manager,BOB))
        self.assertEqual(self.credit(ALICE,offer,200,"manager.scope.1")[0],200)
        status,data=self.as_user("/api/finance/withdraw",ALICE,amount_rub=100)
        self.assertEqual(status,200,data)
        withdraw_id=data["withdrawal"]["id"]
        own=self.as_user("/api/admin/finance/withdrawals",manager)[1]["withdrawals"]
        self.assertEqual([item["id"] for item in own],[withdraw_id])
        self.assertEqual(self.as_user("/api/admin/finance/withdrawals",other_manager)[1]["withdrawals"],[])
        self.assertEqual(self.as_user("/api/admin/finance/accrue",manager,
            user_id=ALICE,offer_id=offer,amount_rub=50,source_reference="manager.scope.2")[0],403)
        self.assertEqual(self.as_user("/api/admin/finance/decision",manager,
            withdrawal_id=withdraw_id,decision="confirm")[0],403)
        self.assertEqual(self.as_user("/api/admin/finance/decision",other_manager,
            withdrawal_id=withdraw_id,decision="reject",note="Нет оснований")[0],403)

    def test_payment_reference_must_be_unique_across_withdrawals(self):
        self.ready(ALICE)
        offer=self.offer(ALICE)
        self.assertEqual(self.credit(ALICE,offer,200,"payment.ref.accrual")[0],200)
        first=self.as_user("/api/finance/withdraw",ALICE,amount_rub=100)[1]["withdrawal"]["id"]
        second=self.as_user("/api/finance/withdraw",ALICE,amount_rub=100)[1]["withdrawal"]["id"]
        for withdraw_id in (first,second):
            self.assertEqual(self.as_user("/api/admin/finance/decision",OWNER,
                withdrawal_id=withdraw_id,decision="confirm")[0],200)
        self.assertEqual(self.as_user("/api/admin/finance/decision",OWNER,
            withdrawal_id=first,decision="paid",payment_reference="bank.pay.123")[0],200)
        self.assertEqual(self.as_user("/api/admin/finance/decision",OWNER,
            withdrawal_id=second,decision="paid",payment_reference="bank.pay.123")[0],409)
        self.assertEqual(self.as_user("/api/admin/finance/decision",OWNER,
            withdrawal_id=second,decision="paid",payment_reference="bank.pay.124")[0],200)
        result=self.as_user("/api/finance/overview",ALICE)[1]
        self.assertEqual(result["balances"],{"accrued_rub":200,"paid_rub":200,"reserved_rub":0,"available_rub":0})


if __name__=="__main__":
    unittest.main()
