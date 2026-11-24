"""Stage 9: payout-triggered referral rewards and separate blogger campaigns."""
import os
import unittest
from unittest.mock import patch

from server import db
from tests import test_finance_stage8 as previous
from tests.test_profile_stage6 import TEST_FERNET_KEY
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB, TEST_ONBOARDING


class Stage9ReferralTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    owner_invite = HttpHarness.owner_invite
    webhook_start = HttpHarness.webhook_start
    ready = previous.Stage8FinanceTests.ready
    offer = previous.Stage8FinanceTests.offer
    credit = previous.Stage8FinanceTests.credit

    def setUp(self):
        HttpHarness.setUp(self)
        env = patch.dict(os.environ, {"PARTNERS_MVP_OPEN_REGISTRATION": "true",
                                   "PARTNERS_PROFILE_ENCRYPTION_KEY": TEST_FERNET_KEY})
        env.start()
        self.addCleanup(env.stop)

    def payout(self, person, offer, amount, key):
        self.assertEqual(self.credit(person, offer, amount, key)[0], 200)
        status, result = self.as_user('/api/finance/withdraw', person, amount_rub=amount,payout_phone="+79000000000",payout_bank="Test Bank")
        self.assertEqual(status, 200, result)
        wid = result['withdrawal']['id']
        self.assertEqual(self.as_user('/api/admin/finance/decision', OWNER,
                         withdrawal_id=wid, decision='confirm')[0], 200)
        status, result = self.as_user('/api/admin/finance/decision', OWNER,
                         withdrawal_id=wid, decision='paid', payment_reference='paid.'+key)
        self.assertEqual(status, 200, result)
        return wid

    def test_referral_only_after_paid_and_exact_15_percent(self):
        self.ready(ALICE)
        status, invite = self.as_user('/api/invitations/referral', ALICE)
        self.assertEqual(status, 200, invite)
        self.assertEqual(self.webhook_start(998001, BOB, invite['code'])[0], 200)
        self.assertEqual(self.as_user('/api/register', BOB, **{**TEST_ONBOARDING, 'consent': True})[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', OWNER, user_id=BOB, decision='approve')[0], 200)
        from tests.test_profile_stage6 import VALID_INN
        self.assertEqual(self.as_user('/api/profile/identity', BOB,
                         surname='Иванов', given_name='Иван', inn=VALID_INN)[0], 200)
        offer = self.offer(BOB)
        self.assertEqual(self.credit(BOB, offer, 101, 'referral.credit.1')[0], 200)
        self.assertEqual(self.as_user('/api/finance/overview', ALICE)[1]['referral']['earned_kopeks'], 0)
        withdraw = self.as_user('/api/finance/withdraw', BOB, amount_rub=101,payout_phone="+79000000000",payout_bank="Test Bank")[1]['withdrawal']['id']
        self.assertEqual(self.as_user('/api/admin/finance/decision', OWNER,
                         withdrawal_id=withdraw, decision='confirm')[0], 200)
        self.assertEqual(self.as_user('/api/finance/overview', ALICE)[1]['referral']['earned_kopeks'], 0)
        self.assertEqual(self.as_user('/api/admin/finance/decision', OWNER,
                         withdrawal_id=withdraw, decision='paid', payment_reference='referral.payment.1')[0], 200)
        info = self.as_user('/api/finance/overview', ALICE)[1]
        self.assertEqual(info['referral']['earned_kopeks'], 1515)
        self.assertEqual(info['balances']['available_rub'], 15)
        self.assertEqual(self.as_user('/api/admin/finance/decision', OWNER,
                         withdrawal_id=withdraw, decision='paid', payment_reference='referral.payment.1')[0], 409)
        with db.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM referral_rewards').fetchone()[0], 1)

    def test_blogger_is_separate_from_referral_and_payment_is_unique(self):
        db.session({'id': OWNER, 'first_name':'Owner', 'last_name':'', 'username':'owner'}, OWNER)
        self.assertEqual(self.as_user('/api/admin/bloggers/create', ALICE, telegram_id=990011,
                         channel='Channel', fixed_rub=100, percent_bps=250)[0], 403)
        status, created = self.as_user('/api/admin/bloggers/create', OWNER, telegram_id=990011,
                                      channel='Channel', fixed_rub=100, percent_bps=250)
        self.assertEqual(status, 200, created)
        self.assertTrue(created['display_id'].startswith('B-'))
        self.assertRegex(created['invite_code'], r'^[A-Z0-9]{6}$')
        self.assertEqual(self.as_user('/api/blogger/overview', 990011)[0], 200)
        self.assertEqual(self.webhook_start(998002, BOB, created['invite_code'])[0], 200)
        self.assertEqual(self.as_user('/api/register', BOB, **{**TEST_ONBOARDING,'consent':True})[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', OWNER, user_id=BOB, decision='approve')[0], 200)
        from tests.test_profile_stage6 import VALID_INN
        self.assertEqual(self.as_user('/api/profile/identity', BOB,
                         surname='Иванов', given_name='Иван', inn=VALID_INN)[0], 200)
        offer = self.offer(BOB)
        self.payout(BOB, offer, 200, 'blogger.credit.1')
        blogger = self.as_user('/api/blogger/overview', 990011)[1]
        self.assertEqual(blogger['earned_kopeks'], 500)
        self.assertEqual(blogger['paid_kopeks'], 0)
        self.assertEqual(self.as_user('/api/finance/overview', 990011)[0], 403)
        self.assertEqual(self.as_user('/api/admin/bloggers/fixed', OWNER,
                         blogger_uuid=created['blogger_uuid'], placement_reference='placement.one')[0], 200)
        self.assertEqual(self.as_user('/api/admin/bloggers/fixed', OWNER,
                         blogger_uuid=created['blogger_uuid'], placement_reference='placement.one')[0], 409)
        blogger = self.as_user('/api/blogger/overview', 990011)[1]
        self.assertEqual(blogger['earned_kopeks'], 10500)
        reward = next(r for r in blogger['rewards'] if r['kind']=='fixed')
        self.assertEqual(self.as_user('/api/admin/bloggers/paid', OWNER,
                         reward_id=reward['id'], payment_reference='blogger.bank.1')[0], 200)
        self.assertEqual(self.as_user('/api/admin/bloggers/paid', OWNER,
                         reward_id=reward['id'], payment_reference='blogger.bank.1')[0], 409)
        self.assertEqual(self.as_user('/api/blogger/overview', 990011)[1]['paid_kopeks'], 10000)


if __name__ == '__main__':
    unittest.main()
