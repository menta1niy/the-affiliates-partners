import unittest
from tests.test_crm_sync_http_worker3 import CRMSyncHTTP
from tests import test_registration as h


class PublishedInstructionHTTP(CRMSyncHTTP):
    def test_rich_instruction_signed_storage_and_scope(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.event({'event_id':'bind:rich','type':'lead.bound',
            'crm_lead_id':'crm:rich','telegram_id':h.ALICE})[0], 200)
        good = {'text':'Read the published steps',
                'images':[{'url':'https://example.org/image.png','alt':'Example'}],
                'links':[{'url':'https://example.org/steps','label':'Steps'}]}
        offer = {'id':'bank-rich','name':'Bank','published_instruction':good,
                 'instruction_draft':'PRIVATE','agency_rate':9000,'blogger_payout':8000}
        event = {'event_id':'offers:rich','type':'offers.assigned',
                 'crm_lead_id':'crm:rich','offers':[offer]}
        self.assertEqual(self.event(event)[0], 200)
        for route, key in (('/api/offers','offers'),('/api/tasks','tasks')):
            visible = self.as_user(route,h.ALICE)[1][key][0]
            self.assertEqual(visible['published_instruction'],good)
            self.assertFalse({'instruction_draft','agency_rate','blogger_payout'} & set(visible))
            self.assertEqual(self.as_user(route,h.BOB)[1][key],[])
        self.assertEqual(self.event({**event,'event_id':'offers:bad-signature'},signature='0'*64)[0],401)
        for index, url in enumerate(('javascript:alert(1)','http://example.org/x',
                                     'https://user:pass@example.org','https://example.org:99999/a',
                                     'https://example.org/a#fragment')):
            invalid = {'event_id':f'offers:invalid:{index}','type':'offers.assigned',
                       'crm_lead_id':'crm:rich','offers':[{**offer,'published_instruction':
                           {**good,'links':[{'url':url,'label':'Bad'}]}}]}
            self.assertEqual(self.event(invalid)[0],400,url)
        for index, payload in enumerate(({**good,'draft':'secret'},
                                         {**good,'text':'x'*12001},
                                         {**good,'images':[{'url':'https://example.org','alt':'ok','private':'secret'}]})):
            self.assertEqual(self.event({'event_id':f'offers:bad-field:{index}',
                'type':'offers.assigned','crm_lead_id':'crm:rich','offers':
                [{**offer,'published_instruction':payload}]})[0],400)

    def test_crm_contract_boundaries_and_literal_markup(self):
        from server.db import Problem, sanitize_published_instruction
        full = {'text':'<script>shown literally</script>' + 'x'*(12000-len('<script>shown literally</script>')),
                'images':[{'url':f'https://example.org:8443/{i}.png','alt':'Image'} for i in range(12)],
                'links':[{'url':f'https://example.org:9443/{i}','label':'Link'} for i in range(24)]}
        self.assertEqual(sanitize_published_instruction(full),full)
        for key in ('images','links'):
            with self.subTest(key=key), self.assertRaises(Problem):
                sanitize_published_instruction({**full,key:full[key]+full[key][:1]})


if __name__ == '__main__':
    unittest.main()
