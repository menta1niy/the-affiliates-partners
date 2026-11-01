"""Participant CRM state is authenticated, idempotent and read-only."""
import unittest

from tests import test_crm_sync_http_worker3 as signed
from tests import test_registration as identities


class ParticipantStatusHTTP(signed.CRMSyncHTTP):
    def test_out_of_order_snapshots_cannot_regress_payment_or_reversal(self):
        self.assertEqual(self.register(identities.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', identities.OWNER,
                                      user_id=identities.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.event({'event_id':'seq:bind','type':'lead.bound',
                                     'crm_lead_id':'crm:seq','telegram_id':identities.ALICE})[0], 200)
        base = {'type':'participant.state','crm_lead_id':'crm:seq',
                'applications':[{'application_id':'a','offer_id':'o','stage':'credited'}],
                'lead_payouts':[{'conversion_id':'c','offer_id':'o','amount':'50','status':'confirmed','reversed':False}]}
        paid = {**base,'event_id':'seq:paid','snapshot_version':2,
                'applications':[{'application_id':'a','offer_id':'o','stage':'paid'}],
                'lead_payouts':[{**base['lead_payouts'][0],'status':'paid'}]}
        stale = {**base,'event_id':'seq:stale','snapshot_version':1}
        self.assertEqual(self.event(paid), (200, {'changed':True}))
        self.assertEqual(self.event(stale), (200, {'changed':False}))
        self.assertEqual(self.as_user('/api/status', identities.ALICE)[1]['lead_payouts'][0]['status'], 'paid')
        reversed_event = {**paid,'event_id':'seq:reversed','snapshot_version':3,
                          'lead_payouts':[{**paid['lead_payouts'][0],'reversed':True}]}
        self.assertEqual(self.event(reversed_event), (200, {'changed':True}))
        self.assertEqual(self.event({**paid,'event_id':'seq:replay'}), (200, {'changed':False}))
        self.assertEqual(self.as_user('/api/status', identities.ALICE)[1]['lead_payouts'][0]['reversed'], True)
        self.assertEqual(self.event({**base,'event_id':'seq:legacy'}), (200, {'changed':False}))
        self.assertEqual(self.event({**base,'event_id':'seq:invalid','snapshot_version':-1})[0],400)

    def test_private_status_and_confirmed_payouts(self):
        self.assertEqual(self.register(identities.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.register(identities.BOB, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', identities.OWNER,
                                      user_id=identities.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.event({'event_id':'status:bind','type':'lead.bound',
                                     'crm_lead_id':'crm:status','telegram_id':identities.ALICE})[0], 200)
        state = {'event_id':'status:1','type':'participant.state','crm_lead_id':'crm:status',
                 'applications':[{'application_id':'application-1','offer_id':'offer-1','stage':'credited'}],
                 'lead_payouts':[{'conversion_id':'conversion-1','offer_id':'offer-1',
                                  'amount':'720.00','status':'confirmed','reversed':False}]}
        self.assertEqual(self.event(state), (200, {'changed': True}))
        self.assertEqual(self.event(state), (200, {'changed': False}))
        status, visible = self.as_user('/api/status', identities.ALICE)
        self.assertEqual(status, 200)
        self.assertEqual(visible['applications'][0]['stage'], 'credited')
        self.assertEqual(visible['lead_payouts'][0]['amount'], '720.00')
        for actor in (identities.BOB, identities.OWNER):
            self.assertEqual(self.as_user('/api/status', actor)[1], {'applications':[], 'lead_payouts':[]})
        self.assertEqual(self.event({**state,'event_id':'status:forged','crm_lead_id':'crm:other'})[0], 409)
        self.assertEqual(self.event({**state,'event_id':'status:invalid','lead_payouts':[
            {**state['lead_payouts'][0],'agency_rate':'99999'}]})[0], 400)
        self.assertEqual(self.as_user('/api/status', identities.ALICE, paid=True,
                                      agency_rate='999999')[1], visible)

        # Subsequent confirmed financial events must replace the participant's
        # snapshot without exposing another user's data or internal rates.
        changed = {**state, 'event_id': 'status:2', 'lead_payouts': [
            {**state['lead_payouts'][0], 'status': 'paid', 'reversed': True}]}
        self.assertEqual(self.event(changed), (200, {'changed': True}))
        status, updated = self.as_user('/api/status', identities.ALICE)
        self.assertEqual(status, 200)
        self.assertEqual(updated['lead_payouts'][0]['status'], 'paid')
        self.assertTrue(updated['lead_payouts'][0]['reversed'])
        self.assertNotIn('agency_rate', str(updated))
        self.assertEqual(self.as_user('/api/status', identities.BOB)[1],
                         {'applications': [], 'lead_payouts': []})


if __name__ == '__main__':
    unittest.main()
