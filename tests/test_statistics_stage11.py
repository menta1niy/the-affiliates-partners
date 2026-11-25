"""Stage 11: potential offer rates are distinct from verified withdrawals."""
import unittest

from tests.test_finance_stage8 import Stage8FinanceTests
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB
from server import db


class Stage11StatisticsTests(unittest.TestCase):
    setUp = Stage8FinanceTests.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    ready = Stage8FinanceTests.ready
    offer = Stage8FinanceTests.offer
    credit = Stage8FinanceTests.credit

    def test_nine_published_offers_are_counted_once_across_buckets(self):
        self.ready(ALICE)
        offers = []
        for number in range(9):
            status, created = self.as_user(
                "/api/admin/mvp/offer", OWNER, name=f"Предложение {number}",
                category="Дебетовые карты", target_action="Оформить",
                payout_rub=1000, hold_days=7)
            self.assertEqual(status, 200, created)
            offers.append(created["offer_id"])

        def snapshot():
            status, result = self.as_user("/api/statistics/overview", ALICE)
            self.assertEqual(status, 200, result)
            return result

        self.assertEqual(snapshot()["potential"], {
            "not_started_rub": 9000, "in_work_rub": 0, "hold_rub": 0})
        self.assertEqual(self.as_user("/api/admin/mvp/assignment", OWNER,
                                     user_id=ALICE, offer_id=offers[0])[0], 200)
        self.assertEqual(snapshot()["potential"]["not_started_rub"], 9000)
        self.assertEqual(self.as_user("/api/admin/mvp/assignment", OWNER,
                                     user_id=ALICE, offer_id=offers[0],
                                     stage="in_progress")[0], 200)
        self.assertEqual(snapshot()["potential"], {
            "not_started_rub": 8000, "in_work_rub": 1000, "hold_rub": 0})
        self.assertEqual(self.as_user("/api/admin/mvp/assignment", OWNER,
                                     user_id=ALICE, offer_id=offers[0],
                                     stage="completed")[0], 200)
        self.assertEqual(snapshot()["potential"], {
            "not_started_rub": 8000, "in_work_rub": 0, "hold_rub": 1000})
        self.assertEqual(self.credit(ALICE, offers[0], 700, "nine.offers.verified")[0], 200)
        self.assertEqual(snapshot()["potential"], {
            "not_started_rub": 8000, "in_work_rub": 0, "hold_rub": 0})
        self.assertEqual(snapshot()["verified"]["available_rub"], 700)
        with db.transaction() as conn:
            conn.execute("UPDATE manual_offers SET active=0 WHERE id=?", (offers[1],))
            conn.execute("UPDATE manual_offers SET deleted_at=1 WHERE id=?", (offers[2],))
        self.assertEqual(snapshot()["potential"]["not_started_rub"], 6000)

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
        withdrawal = self.as_user("/api/finance/withdraw", ALICE, amount_rub=400,payout_phone="+79000000000",payout_bank="Test Bank")[1]["withdrawal"]["id"]
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
        other = self.as_user("/api/statistics/overview", BOB)[1]
        self.assertEqual(other["assigned_count"], 0)
        self.assertEqual(other["potential"]["not_started_rub"], 1000)
        self.assertEqual(self.as_user("/api/statistics/overview", ALICE,
                                      user_id=BOB)[1]["assigned_count"], 1)
        self.assertEqual(self.post("/api/statistics/overview", {"initData":"bad"})[0], 401)
