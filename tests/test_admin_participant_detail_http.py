"""Real HTTP access boundaries for the read-only admin participant card."""
import json
import unittest

from server import db
from tests.test_admin_agency_scope import AdminAgencyScopeTests


class AdminParticipantDetailHTTP(AdminAgencyScopeTests):
    def test_detail_tenant_and_read_only_snapshot(self):
        with db.transaction() as conn:
            conn.execute("INSERT INTO crm_lead_bindings(crm_lead_id,telegram_id,bound_at) VALUES('synthetic-a',?,123)", (self.lead_a,))
            conn.execute("INSERT INTO crm_assigned_offers(crm_lead_id,offer_id,payload) VALUES('synthetic-a','offer-a',?)", (json.dumps({'id':'offer-a','name':'<img src=x onerror=alert(1)>','lead_reward':'50'}),))
            conn.execute("INSERT INTO crm_participant_states(crm_lead_id,payload,updated_at) VALUES('synthetic-a',?,124)", (json.dumps({'applications':[{'application_id':'app-a','offer_id':'offer-a','stage':'credited'}],'lead_payouts':[{'conversion_id':'conversion-a','offer_id':'offer-a','amount':'50','status':'confirmed','reversed':False}]}),))
            before = conn.execute('SELECT count(*) FROM crm_events').fetchone()[0]
        for actor in (self.admin, self.staff_b, self.other_admin):
            code, body = self.as_user('/api/admin/participant', actor, user_id=self.lead_a)
            if actor == self.admin:
                self.assertEqual(code, 200, body)
                self.assertEqual(body['crm_lead_id'], 'synthetic-a')
                self.assertEqual(body['offers'][0]['name'], '<img src=x onerror=alert(1)>')
                self.assertEqual(body['status']['lead_payouts'][0]['amount'], '50')
                self.assertNotIn('agency_rate', json.dumps(body))
            else:
                self.assertEqual(code, 403, body)
        self.assertEqual(self.as_user('/api/admin/participant', self.admin, user_id=self.lead_b)[0], 403)
        self.assertEqual(self.as_user('/api/admin/participant', self.lead_a, user_id=self.lead_a)[0], 403)
        self.assertEqual(self.as_user('/api/admin/participant', self.admin, user_id='bad')[0], 400)
        with db.transaction() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM crm_events').fetchone()[0], before)
