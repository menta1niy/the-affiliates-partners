"""Exercise signed HTTP ingress at CRM's maximum valid instruction size."""
import json
import unittest

from tests.test_crm_sync_http_worker3 import CRMSyncHTTP
from tests import test_registration as h
from server import integration


class LargePublishedInstructionHTTP(CRMSyncHTTP):
    def test_large_valid_event_bad_signature_and_overlimit(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.event({'event_id':'bind:large','type':'lead.bound',
            'crm_lead_id':'crm:large','telegram_id':h.ALICE})[0], 200)
        instruction = {
            'text':'Т' * 12000,
            'images':[{'url':'https://example.org/'+('i'*2000)+str(i),'alt':'image'} for i in range(12)],
            'links':[{'url':'https://example.org/'+('l'*2000)+str(i),'label':'link'} for i in range(24)],
        }
        event = {'event_id':'offers:large','type':'offers.assigned','crm_lead_id':'crm:large',
                 'offers':[{'id':'large-offer','name':'Large','published_instruction':instruction}]}
        size = len(json.dumps(event,ensure_ascii=False).encode('utf-8'))
        self.assertGreater(size, 65536)
        self.assertLess(size, integration.MAX_BODY)
        self.assertEqual(self.event(event,signature='0'*64)[0], 401)
        self.assertEqual(self.as_user('/api/offers',h.ALICE)[1]['offers'],[])
        self.assertEqual(self.event(event)[0],200)
        self.assertEqual(self.as_user('/api/offers',h.ALICE)[1]['offers'][0]['published_instruction'],instruction)
        self.assertEqual(self.as_user('/api/tasks',h.ALICE)[1]['tasks'][0]['published_instruction'],instruction)
        oversized = {**event,'event_id':'offers:over-limit','padding':'x' * integration.MAX_BODY}
        self.assertGreater(len(json.dumps(oversized).encode('utf-8')),integration.MAX_BODY)
        self.assertEqual(self.event(oversized)[0],400)
        self.assertEqual(self.as_user('/api/offers',h.ALICE)[1]['offers'][0]['published_instruction'],instruction)


if __name__ == '__main__':
    unittest.main()
