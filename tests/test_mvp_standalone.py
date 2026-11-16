"""MVP works without CRM workspace, including signed HTTP and tenant RBAC."""
import os
import unittest
from unittest.mock import patch

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB, init_data


class StandaloneMvpTests(HttpHarness):
    def setUp(self):
        super().setUp()
        self.patch_open = patch.dict(os.environ, {"PARTNERS_MVP_OPEN_REGISTRATION": "true"})
        self.patch_open.start()
        self.addCleanup(self.patch_open.stop)

    def create_offer(self, **changes):
        payload={"name":"Карта Test", "category":"Дебетовые карты",
                 "target_action":"Оформить и активировать", "payout_rub":700,
                 "hold_days":14, "instructions":"Оформите карту",
                 "referral_url":"https://bank.example.test/apply"}
        payload.update(changes)
        status, result = self.as_user('/api/admin/mvp/offer', OWNER, **payload)
        self.assertEqual(status, 200, result)
        return result['offer_id']

    def register_open_user(self, uid=ALICE):
        status, session = self.as_user('/api/session', uid)
        self.assertEqual(status, 200)
        self.assertTrue(session['open_registration'])
        status, user = self.as_user('/api/register', uid, consent=True)
        self.assertEqual(status, 200, user)
        self.assertEqual(user['status'], 'pending')
        self.assertEqual(self.as_user('/api/admin/decision', OWNER, user_id=uid, decision='approve')[0],200)

    def test_owner_creates_assigns_updates_and_lead_sees_only_own_offers(self):
        self.register_open_user(ALICE)
        self.register_open_user(BOB)
        offer = self.create_offer()
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,
            user_id=ALICE, offer_id=offer, stage='in_progress', note='Начал оформление')[0], 200)
        status, view = self.as_user('/api/mvp/overview', ALICE)
        self.assertEqual(status, 200)
        self.assertEqual(view['statistics']['in_progress'], 1)
        self.assertEqual(view['offers'][0]['payout_rub'], 700)
        self.assertEqual(view['offers'][0]['hold_days'], 14)
        self.assertEqual(view['offers'][0]['category'], 'Дебетовые карты')
        self.assertEqual(self.as_user('/api/mvp/overview', BOB)[1]['offers'], [])
        self.assertEqual(self.as_user('/api/admin/mvp/catalog', ALICE)[0], 403)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', ALICE,user_id=BOB,offer_id=offer)[0],403)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,user_id=ALICE,offer_id=offer,stage='completed',note='Проверено администратором')[0],200)
        self.assertEqual(self.as_user('/api/mvp/overview', ALICE)[1]['statistics']['completed'],1)
        self.assertEqual(self.as_user('/api/admin/participant',OWNER,user_id=ALICE)[1]['manual']['offers'][0]['stage'],'completed')
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,user_id=ALICE,offer_id=offer,enabled=False,note='')[0],200)
        self.assertEqual(self.as_user('/api/mvp/overview', ALICE)[1]['offers'], [])

    def test_open_registration_requires_signed_initdata_and_consent(self):
        self.assertEqual(self.post('/api/register',{'initData':'invalid','consent':True})[0],401)
        self.assertEqual(self.as_user('/api/register',ALICE,consent=False)[0],400)
        self.assertEqual(self.as_user('/api/mvp/overview',ALICE)[1]['offers'],[])
        self.assertEqual(self.as_user('/api/register',ALICE,consent=True)[0],200)
        with db.transaction() as conn:
            user=db.get_user(conn, ALICE)
            self.assertEqual(user['agency_id'],OWNER)
            self.assertEqual(user['source'],None)
            self.assertEqual(conn.execute('SELECT count(*) FROM crm_registration_outbox').fetchone()[0],0)

    def test_offer_input_validation_and_tenant_isolation(self):
        offer=self.create_offer()
        for data in ({'payout_rub':-1},{'hold_days':366},{'name':''},
                     {'referral_url':'https://login:secret@bank.test/'},
                     {'referral_url':'javascript:alert(1)'},{'referral_url':'https://bank.test\\evil'}):
            with self.subTest(data=data):
                payload={'name':'Card','category':'Card','target_action':'Do',
                         'payout_rub':10,'hold_days':0,**data}
                self.assertEqual(self.as_user('/api/admin/mvp/offer',OWNER,**payload)[0],400)
        self.register_open_user(ALICE)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,user_id=ALICE,offer_id=offer,stage='paid',note='')[0],400)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,user_id=ALICE,offer_id=offer,stage='assigned',note='')[0],200)

    def test_malformed_assignment_stage_is_client_error_not_server_failure(self):
        self.register_open_user(ALICE)
        offer = self.create_offer()
        for malformed in ([], {}, None, 10):
            with self.subTest(stage=malformed):
                status, response = self.as_user('/api/admin/mvp/assignment', OWNER,
                    user_id=ALICE, offer_id=offer, stage=malformed)
                self.assertEqual(status, 400, response)


if __name__=='__main__':
    unittest.main()
