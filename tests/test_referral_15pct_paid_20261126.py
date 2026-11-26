"""Paid referral rewards through signed Telegram HTTP and open registration."""
import os
import unittest
from unittest.mock import patch

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB
from tests.test_profile_stage6 import TEST_FERNET_KEY


class ReferralPaidOpenRegistration20261126(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    webhook_start = HttpHarness.webhook_start

    def setUp(self):
        HttpHarness.setUp(self)
        env = patch.dict(os.environ, {'PARTNERS_PROFILE_ENCRYPTION_KEY': TEST_FERNET_KEY})
        env.start()
        self.addCleanup(env.stop)

    def test_15_percent_only_on_paid_with_first_source_protected(self):
        status, referrer = self.as_user('/api/register', ALICE, consent=True, adult_confirmed=True)
        self.assertEqual(status, 200, referrer)
        self.assertIsNone(referrer['user']['source'])
        status, invite = self.as_user('/api/invitations/referral', ALICE)
        self.assertEqual(status, 200, invite)
        code = invite['code']
        self.assertEqual(self.webhook_start(998801, BOB, code)[0], 200)
        status, referred = self.as_user('/api/register', BOB, consent=True, adult_confirmed=True)
        self.assertEqual(status, 200, referred)
        self.assertEqual(referred['user']['source'], 'referral')
        self.assertEqual(referred['user']['referrer_id'], ALICE)
        with db.transaction() as conn:
            self.assertEqual(db.get_user(conn, BOB)['introduced_by_id'], ALICE)

        status, offer = self.as_user('/api/admin/mvp/offer', OWNER,
                                    name='Debit card', category='Cards', target_action='Apply',
                                    payout_rub=101, hold_days=0)
        self.assertEqual(status, 200, offer)
        offer_id = offer['offer_id']
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,
                                     user_id=BOB, offer_id=offer_id)[0], 200)
        self.assertEqual(self.as_user('/api/admin/finance/accrue', OWNER,
                                     user_id=BOB, offer_id=offer_id, amount_rub=101,
                                     source_reference='20261126.referred.credit')[0], 200)
        self.assertEqual(self.as_user('/api/finance/overview', ALICE)[1]['referral']['earned_kopeks'], 0)
        status, withdrawal = self.as_user('/api/finance/withdraw', BOB,
                                          amount_rub=101, payout_phone='+79000000000',
                                          payout_bank='Test Bank')
        self.assertEqual(status, 200, withdrawal)
        wid = withdrawal['withdrawal']['id']
        self.assertEqual(self.as_user('/api/admin/finance/decision', OWNER,
                                     withdrawal_id=wid, decision='confirm')[0], 200)
        self.assertEqual(self.as_user('/api/finance/overview', ALICE)[1]['referral']['earned_kopeks'], 0)
        self.assertEqual(self.as_user('/api/admin/finance/decision', OWNER,
                                     withdrawal_id=wid, decision='paid',
                                     payment_reference='20261126.referral.paid')[0], 200)
        result = self.as_user('/api/finance/overview', ALICE)[1]
        self.assertEqual(result['referral']['earned_kopeks'], 1515)
        self.assertEqual(result['balances']['available_rub'], 15)
        self.assertEqual(result['referral']['invited_count'], 1)
        with db.transaction() as conn:
            reward = conn.execute('SELECT * FROM referral_rewards WHERE withdrawal_id=?', (wid,)).fetchone()
            self.assertIsNotNone(reward)
            self.assertEqual((reward['referrer_id'], reward['referred_id'], reward['amount_kopeks']),
                             (ALICE, BOB, 1515))
        self.assertEqual(self.as_user('/api/admin/finance/decision', OWNER,
                                     withdrawal_id=wid, decision='paid',
                                     payment_reference='20261126.referral.paid')[0], 409)


if __name__ == '__main__':
    unittest.main()
