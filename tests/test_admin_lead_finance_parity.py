"""The admin lead card must show the exact same money as the lead's ledger."""
import json
import unittest

from server import db
from tests.test_finance_stage8 import Stage8FinanceTests
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB


class AdminLeadFinanceParity(unittest.TestCase):
    setUp = Stage8FinanceTests.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    ready = Stage8FinanceTests.ready
    offer = Stage8FinanceTests.offer
    credit = Stage8FinanceTests.credit

    def test_admin_matches_participant_at_every_money_state(self):
        self.ready(ALICE)
        work = self.offer(ALICE)
        hold = self.offer(ALICE)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,
            user_id=ALICE, offer_id=work, stage='in_progress')[0], 200)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,
            user_id=ALICE, offer_id=hold, stage='completed')[0], 200)

        def parity():
            status, admin = self.as_user('/api/admin/participant', OWNER, user_id=ALICE)
            self.assertEqual(status, 200, admin)
            status, stats = self.as_user('/api/statistics/overview', ALICE)
            self.assertEqual(status, 200, stats)
            status, ledger = self.as_user('/api/finance/overview', ALICE)
            self.assertEqual(status, 200, ledger)
            self.assertEqual(admin['statistics'], stats)
            self.assertEqual(admin['finance']['balances'], ledger['balances'])
            self.assertEqual(admin['finance']['accruals'], ledger['accruals'])
            self.assertEqual(admin['finance']['withdrawals'], ledger['withdrawals'])
            self.assertEqual({o['id']: o['stage'] for o in admin['manual']['offers']},
                             {work: 'in_progress', hold: 'completed'})
            return admin

        initial = parity()
        self.assertEqual(initial['statistics']['potential'],
                         {'not_started_rub': 0, 'in_work_rub': 1000, 'hold_rub': 1000})
        self.assertEqual(initial['finance']['balances']['accrued_rub'], 0)
        self.assertEqual(self.credit(ALICE, hold, 700, 'admin.parity.credit.1')[0], 200)
        credited = parity()
        self.assertEqual(credited['statistics']['potential']['hold_rub'], 0)
        self.assertEqual(credited['finance']['accrual_by_offer'][hold], 700)
        withdrawal = self.as_user('/api/finance/withdraw', ALICE, amount_rub=400)[1]['withdrawal']['id']
        reserved = parity()
        self.assertEqual(reserved['finance']['balances']['reserved_rub'], 400)
        self.assertEqual(reserved['finance']['balances']['paid_rub'], 0)
        self.assertEqual(self.as_user('/api/admin/finance/decision', OWNER,
            withdrawal_id=withdrawal, decision='confirm')[0], 200)
        self.assertEqual(self.as_user('/api/admin/finance/decision', OWNER,
            withdrawal_id=withdrawal, decision='paid',
            payment_reference='admin.parity.payment.1')[0], 200)
        paid = parity()
        self.assertEqual(paid['finance']['balances']['paid_rub'], 400)
        self.assertEqual(paid['finance']['balances']['reserved_rub'], 0)
        self.assertEqual(paid['finance']['balances']['available_rub'], 300)
        self.assertEqual(paid['statistics']['potential']['in_work_rub'], 1000)

    def test_financial_snapshot_is_not_available_to_leads_or_staff(self):
        self.ready(ALICE)
        self.ready(BOB)
        self.offer(ALICE)
        self.assertEqual(self.as_user('/api/admin/participant', BOB, user_id=ALICE)[0], 403)
        with db.transaction() as conn:
            conn.execute("UPDATE users SET role='staff',manager_id=NULL WHERE id=?", (BOB,))
            conn.execute("UPDATE users SET manager_id=? WHERE id=?", (BOB, ALICE))
        status, admin = self.as_user('/api/admin/participant', BOB, user_id=ALICE)
        # Existing /api/admin/participant also fetches admin-only manual
        # assignments; staff remains forbidden from the whole endpoint.
        self.assertEqual(status, 403, admin)
        self.assertNotIn('finance', admin)
        self.assertNotIn('statistics', admin)

    def test_paid_crm_status_alone_does_not_change_ledger_balance(self):
        self.ready(ALICE)
        offer = self.offer(ALICE)
        with db.transaction() as conn:
            conn.execute("INSERT INTO crm_lead_bindings(crm_lead_id,telegram_id,bound_at) "
                         "VALUES('crm-parity',?,123)",(ALICE,))
            conn.execute("INSERT INTO crm_participant_states(crm_lead_id,payload,updated_at) "
                         "VALUES('crm-parity',?,124)",(json.dumps({
                             "applications": [],
                             "lead_payouts": [{"offer_id":offer,"amount":"1000",
                                               "status":"paid","reversed":False}]
                         }),))
        status, card = self.as_user('/api/admin/participant', OWNER, user_id=ALICE)
        self.assertEqual(status, 200, card)
        self.assertEqual(card['status']['lead_payouts'][0]['status'], 'paid')
        self.assertEqual(card['finance']['balances']['accrued_rub'], 0)
        self.assertEqual(card['finance']['balances']['paid_rub'], 0)
        self.assertEqual(self.as_user('/api/finance/overview', ALICE)[1]['balances'],
                         card['finance']['balances'])
