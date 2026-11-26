"""Owner-equivalent manager finance, blogger and statistics permissions."""
import os
import time
import unittest
from unittest.mock import patch

from server import db, finance
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB
from tests.test_profile_stage6 import TEST_FERNET_KEY


class StaffOwnerParityFinanceTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user

    def setUp(self):
        HttpHarness.setUp(self)
        env = patch.dict(os.environ, {"PARTNERS_DATABASE_URL": "", "PARTNERS_REQUIRE_POSTGRES": "false",
                                   "PARTNERS_PG_SCHEMA_READY": "false",
                                   "PARTNERS_PROFILE_ENCRYPTION_KEY": TEST_FERNET_KEY})
        env.start()
        self.addCleanup(env.stop)
        db.initialize()
        self.staff, self.admin = 993001, 993002
        now = int(time.time())
        with db.transaction() as conn:
            db.ensure_owner(conn, OWNER)
            for uid, role in ((self.staff, 'staff'), (self.admin, 'admin')):
                conn.execute('INSERT INTO users(id,internal_id,first_name,role,status,agency_id,registered_at,updated_at) '
                             "VALUES(?,?,?,?,'active',?,?,?)",
                             (uid, db.allocate_internal_id(conn), 'Manager', role, OWNER, now, now))
            for uid in (ALICE, BOB):
                conn.execute('INSERT INTO users(id,internal_id,first_name,role,status,agency_id,registered_at,updated_at,consent_at) '
                             "VALUES(?,?,?,'lead','active',?,?,?,?)",
                             (uid, db.allocate_internal_id(conn), 'Lead', OWNER, now, now, now))
        offer = self.as_user('/api/admin/mvp/offer', OWNER, name='Debit', category='Cards',
                             target_action='Apply', payout_rub=500, hold_days=0)[1]
        self.offer_id = offer['offer_id']
        for uid in (ALICE, BOB):
            self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,
                                         user_id=uid, offer_id=self.offer_id)[0], 200)

    def test_staff_admin_global_finance_sbp_audit_and_double_payment_protection(self):
        for manager, target, ref in ((self.staff, ALICE, 'manager.accrual.a'),
                                     (self.admin, BOB, 'manager.accrual.b')):
            status, acc = self.as_user('/api/admin/finance/accrue', manager, user_id=target,
                                       offer_id=self.offer_id, amount_rub=500, source_reference=ref)
            self.assertEqual(status, 200, acc)
            self.assertEqual(self.as_user('/api/admin/finance/accrue', manager, user_id=target,
                                         offer_id=self.offer_id, amount_rub=500, source_reference=ref)[0], 409)
        status, withdrawal = self.as_user('/api/finance/withdraw', ALICE, amount_rub=500,
                                          payout_phone='+79000000000', payout_bank='Test Bank')
        self.assertEqual(status, 200, withdrawal)
        wid = withdrawal['withdrawal']['id']
        with db.transaction() as conn:
            encrypted = conn.execute('SELECT payout_details_encrypted FROM finance_withdrawals WHERE id=?', (wid,)).fetchone()[0]
            self.assertNotIn('79000000000', encrypted)
            self.assertNotIn('Test Bank', encrypted)
        for manager in (OWNER, self.staff, self.admin):
            queued = self.as_user('/api/admin/finance/withdrawals', manager, status='all')[1]['withdrawals']
            self.assertIn(wid, [entry['id'] for entry in queued])
            status, details = self.as_user('/api/admin/finance/payout-details', manager, withdrawal_id=wid)
            self.assertEqual(status, 200, details)
            self.assertEqual(details['details']['bank'], 'Test Bank')
        self.assertEqual(self.as_user('/api/admin/finance/payout-details', BOB, withdrawal_id=wid)[0], 403)
        self.assertEqual(self.as_user('/api/admin/finance/decision', self.staff,
                                     withdrawal_id=wid, decision='confirm')[0], 200)
        self.assertEqual(self.as_user('/api/admin/finance/decision', self.admin,
                                     withdrawal_id=wid, decision='paid', payment_reference='manager.payment.a')[0], 200)
        self.assertEqual(self.as_user('/api/admin/finance/decision', OWNER,
                                     withdrawal_id=wid, decision='paid', payment_reference='manager.payment.a')[0], 409)
        self.assertEqual(self.as_user('/api/admin/finance/payout-details', self.staff, withdrawal_id=wid)[0], 409)
        with db.transaction() as conn:
            row = conn.execute('SELECT payout_details_encrypted,payment_reference,reviewed_by FROM finance_withdrawals WHERE id=?', (wid,)).fetchone()
            self.assertEqual(row['payout_details_encrypted'], '')
            self.assertEqual(row['reviewed_by'], self.admin)
            actions = [r['action'] for r in conn.execute('SELECT action FROM audit').fetchall()]
            for required in ('finance_accrual_confirmed', 'finance_payout_details_viewed',
                             'finance_withdrawal_confirmed', 'finance_withdrawal_paid'):
                self.assertIn(required, actions)

    def test_managers_global_blogger_management_duplicates_and_audit(self):
        status, created = self.as_user('/api/admin/bloggers/create', self.staff, telegram_id=993099,
                                       channel='Test channel', fixed_rub=100, percent_bps=100)
        self.assertEqual(status, 200, created)
        self.assertRegex(created['invite_code'], r'^[A-Z0-9]{6}$')
        blogger_uuid = created['blogger_uuid']
        for manager in (OWNER, self.staff, self.admin):
            self.assertIn(blogger_uuid, [x['blogger_uuid'] for x in
                          self.as_user('/api/admin/bloggers/list', manager)[1]['bloggers']])
        self.assertEqual(self.as_user('/api/admin/bloggers/update', self.admin,
                         blogger_uuid=blogger_uuid, fixed_rub=120, percent_bps=250, active=True)[0], 200)
        status, earned = self.as_user('/api/admin/bloggers/fixed', self.staff,
                                      blogger_uuid=blogger_uuid, placement_reference='staff.placement.1')
        self.assertEqual(status, 200, earned)
        self.assertEqual(self.as_user('/api/admin/bloggers/fixed', self.staff,
                         blogger_uuid=blogger_uuid, placement_reference='staff.placement.1')[0], 409)
        status, paid = self.as_user('/api/admin/bloggers/paid', self.admin,
                                    reward_id=earned['reward_id'], payment_reference='blogger.payment.1')
        self.assertEqual(status, 200, paid)
        self.assertEqual(self.as_user('/api/admin/bloggers/paid', self.staff,
                         reward_id=earned['reward_id'], payment_reference='blogger.payment.1')[0], 409)
        with db.transaction() as conn:
            self.assertTrue(db.valid_invitation_source(conn, BOB, created['invite_code']))
            actions = [r['action'] for r in conn.execute('SELECT action FROM audit').fetchall()]
            self.assertIn('blogger_registered', actions)
            self.assertIn('blogger_fixed_earned', actions)
            self.assertIn('blogger_reward_paid', actions)

    def test_statistics_global_manager_target_but_lead_cannot_cross_read(self):
        for operator in (OWNER, self.staff, self.admin):
            status, stats = self.as_user('/api/statistics/overview', operator, user_id=ALICE)
            self.assertEqual(status, 200, stats)
            self.assertIn('verified', stats)
        self.assertEqual(self.as_user('/api/statistics/overview', BOB, user_id=ALICE)[0], 403)
        self.assertEqual(self.post('/api/statistics/overview', {'initData': 'invalid', 'user_id': ALICE})[0], 401)

    def test_rejects_self_accrual_unverified_lead_and_corrupted_fernet(self):
        with db.transaction() as conn:
            with self.assertRaises(db.Problem) as denied:
                finance._target(conn, db.get_user(conn, self.staff), self.staff)
            self.assertEqual(denied.exception.code, 403)
        self.assertEqual(self.as_user('/api/admin/finance/accrue', self.staff,
                         user_id=ALICE, offer_id=self.offer_id, amount_rub=100,
                         source_reference='valid.accrual.test')[0], 200)
        wid = self.as_user('/api/finance/withdraw', ALICE, amount_rub=100,
                           payout_phone='+79000000000', payout_bank='Test Bank')[1]['withdrawal']['id']
        with db.transaction() as conn:
            conn.execute("UPDATE finance_withdrawals SET payout_details_encrypted='corrupted' WHERE id=?", (wid,))
        self.assertEqual(self.as_user('/api/admin/finance/payout-details', self.staff,
                                     withdrawal_id=wid)[0], 503)
        self.assertEqual(self.as_user('/api/admin/finance/payout-details', self.admin,
                                     withdrawal_id=wid)[0], 503)
        self.assertEqual(self.as_user('/api/admin/finance/decision', self.staff,
                                     withdrawal_id=wid, decision='confirm')[0], 200)
        self.assertEqual(self.as_user('/api/admin/finance/decision', self.staff,
                                     withdrawal_id=wid, decision='paid',
                                     payment_reference='real.payment.test')[0], 200)
        with db.transaction() as conn:
            self.assertEqual(conn.execute('SELECT payout_details_encrypted FROM finance_withdrawals '
                                          'WHERE id=?', (wid,)).fetchone()[0], '')

    def test_payment_reference_cannot_pay_two_withdrawals(self):
        self.assertEqual(self.as_user('/api/admin/finance/accrue', OWNER,
                         user_id=ALICE, offer_id=self.offer_id, amount_rub=200,
                         source_reference='test.two.requests')[0], 200)
        ids = []
        for _ in range(2):
            status, result = self.as_user('/api/finance/withdraw', ALICE, amount_rub=100,
                                          payout_phone='+79000000000', payout_bank='Test Bank')
            self.assertEqual(status, 200, result)
            ids.append(result['withdrawal']['id'])
        for wid in ids:
            self.assertEqual(self.as_user('/api/admin/finance/decision', self.staff,
                                         withdrawal_id=wid, decision='confirm')[0], 200)
        self.assertEqual(self.as_user('/api/admin/finance/decision', self.staff,
                         withdrawal_id=ids[0], decision='paid',
                         payment_reference='same.payment.reference')[0], 200)
        self.assertEqual(self.as_user('/api/admin/finance/decision', self.admin,
                         withdrawal_id=ids[1], decision='paid',
                         payment_reference='same.payment.reference')[0], 409)
        self.assertEqual(self.as_user('/api/admin/finance/decision', self.admin,
                         withdrawal_id=ids[1], decision='paid',
                         payment_reference='other.payment.reference')[0], 200)


if __name__ == '__main__':
    unittest.main()
