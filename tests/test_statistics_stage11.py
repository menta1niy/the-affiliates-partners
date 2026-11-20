"""Stage 11: potential offer rates are distinct from verified withdrawals."""
import unittest

from tests.test_finance_stage8 import Stage8FinanceTests
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB


class Stage11StatisticsTests(unittest.TestCase):
    setUp = Stage8FinanceTests.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    ready = Stage8FinanceTests.ready
    offer = Stage8FinanceTests.offer
    credit = Stage8FinanceTests.credit
    def test_statistics_distinguish_stages_and_verified_money(self):
        self.ready(ALICE)
        offer1 = self.offer(ALICE)
        offer2 = self.offer(ALICE)
        offer3 = self.offer(ALICE)
        offer4 = self.offer(ALICE)
        # Created offers have distinct IDs; update only the assigned stage.
        for offer, stage in ((offer2, "in_progress"), (offer3, "submitted"), (offer4, "completed")):
            self.assertEqual(self.as_user("/api/admin/mvp/assignment", OWNER,
                                         user_id=ALICE, offer_id=offer, stage=stage)[0], 200)
        status, initial = self.as_user("/api/statistics/overview", ALICE)
        self.assertEqual(status, 200, initial)
        self.assertEqual(initial["potential"], {
            "not_started_rub": 1000, "in_work_rub": 2000, "hold_rub": 1000})
        self.assertEqual(initial["verified"]["available_rub"], 0)
        self.assertEqual(initial["stages"]["completed"], 1)
        self.assertEqual(initial["assigned_count"], 4)
        self.assertEqual(self.credit(ALICE, offer4, 700, "stage11.accrue.1")[0], 200)
        _, credited = self.as_user("/api/statistics/overview", ALICE)
        self.assertEqual(credited["potential"]["hold_rub"], 0)
        self.assertEqual(credited["verified"]["available_rub"], 700)
        self.assertEqual(credited["verified"]["paid_rub"], 0)
        withdrawal = self.as_user("/api/finance/withdraw", ALICE, amount_rub=400)[1]["withdrawal"]["id"]
        _, reserved = self.as_user("/api/statistics/overview", ALICE)
        self.assertEqual(reserved["verified"]["reserved_rub"], 400)
        self.assertEqual(reserved["verified"]["available_rub"], 300)
        self.assertEqual(self.as_user("/api/admin/finance/decision", OWNER,
                         withdrawal_id=withdrawal, decision="confirm")[0], 200)
        self.assertEqual(self.as_user("/api/admin/finance/decision", OWNER,
                         withdrawal_id=withdrawal, decision="paid", payment_reference="stage11.payment.1")[0], 200)
        _, paid = self.as_user("/api/statistics/overview", ALICE)
        self.assertEqual(paid["verified"]["paid_rub"], 400)
        self.assertEqual(paid["verified"]["reserved_rub"], 0)
        self.assertEqual(paid["verified"]["available_rub"], 300)
        self.assertEqual(paid["potential"]["in_work_rub"], 2000)

    def test_statistics_is_only_visible_to_authenticated_participant(self):
        self.ready(ALICE)
        self.ready(BOB)
        self.offer(ALICE)
        self.assertEqual(self.as_user("/api/statistics/overview", OWNER)[0], 403)
        self.assertEqual(self.as_user("/api/statistics/overview", BOB)[1]["assigned_count"], 0)
        self.assertEqual(self.as_user("/api/statistics/overview", ALICE,
                                      user_id=BOB)[1]["assigned_count"], 1)
        self.assertEqual(self.post("/api/statistics/overview", {"initData":"bad"})[0], 401)
