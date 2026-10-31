"""Real signed CRM HTTP integration against isolated SQLite; no handler stubs."""
import json
import sqlite3
import time
import unittest
from contextlib import closing
from unittest.mock import patch

from server import integration
from tests import test_registration as h

KEY = "worker3-test-secret-for-local-signed-crm-events"


class CRMSyncHTTP(unittest.TestCase):
    setUp = h.HttpHarness.setUp
    stop_server = h.HttpHarness.stop_server
    post = h.HttpHarness.post
    as_user = h.HttpHarness.as_user
    register = h.HttpHarness.register
    owner_invite = h.HttpHarness.owner_invite
    webhook_start = h.HttpHarness.webhook_start

    def event(self, data, *, signature=None):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        stamp = int(time.time())
        headers = {'X-TA-Event-ID': data['event_id'], 'X-TA-Timestamp': str(stamp),
                   'X-TA-Signature': signature or integration.signature(raw, stamp, KEY)}
        with patch.dict('os.environ', {'PARTNERS_CRM_SHARED_SECRET': KEY}):
            return self.post('/api/integration/crm/events', data, headers=headers)

    def count(self, table):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def test_consent_binding_offers_replay_and_cross_user_scope(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.register(h.BOB, self.owner_invite())[0], 200)
        for who in (h.ALICE, h.BOB):
            self.assertEqual(self.as_user('/api/admin/decision', h.OWNER,
                                          user_id=who, decision='approve')[0], 200)
        bind = {'event_id': 'bind:1', 'type': 'lead.bound', 'crm_lead_id': 'crm:a', 'telegram_id': h.ALICE}
        self.assertEqual(self.event(bind), (200, {'changed': True}))
        self.assertEqual(self.event(bind), (200, {'changed': False}))
        self.assertEqual(self.count('crm_lead_bindings'), 1)
        self.assertEqual(self.event({**bind, 'telegram_id': h.BOB})[0], 409)
        self.assertEqual(self.event({**bind, 'event_id': 'bind:2', 'telegram_id': h.BOB})[0], 409)
        offers = {'event_id': 'offers:1', 'type': 'offers.assigned', 'crm_lead_id': 'crm:a',
                  'offers': [{'id': 'bank-1', 'title': 'Private offer', 'rate': 10000}]}
        self.assertEqual(self.event(offers), (200, {'changed': True}))
        self.assertEqual(self.event(offers), (200, {'changed': False}))
        self.assertEqual(self.count('crm_assigned_offers'), 1)
        self.assertEqual(self.as_user('/api/offers', h.ALICE)[1]['offers'], offers['offers'])
        self.assertEqual(self.as_user('/api/offers', h.BOB)[1]['offers'], [])
        self.assertEqual(self.as_user('/api/offers', h.OWNER)[1]['offers'], [])
        before = (self.count('crm_events'), self.count('crm_assigned_offers'))
        self.assertEqual(self.as_user('/api/integration/crm/events', h.BOB,
                                      **{**offers, 'event_id': 'offers:attack'})[0], 401)
        self.assertEqual(self.event({**offers, 'event_id': 'offers:attack'}, signature='0'*64)[0], 401)
        self.assertEqual((self.count('crm_events'), self.count('crm_assigned_offers')), before)

    def test_unregistered_binding_rejected_and_telegram_financial_payload_ignored(self):
        unregistered = {'event_id': 'bind:no-consent', 'type': 'lead.bound',
                        'crm_lead_id': 'crm:unknown', 'telegram_id': h.BOB}
        self.assertEqual(self.event(unregistered)[0], 409)
        self.assertEqual(self.count('crm_events'), 0)
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.event({'event_id':'bind:valid', 'type':'lead.bound',
                                     'crm_lead_id':'crm:a', 'telegram_id':h.ALICE}), (200, {'changed':True}))
        profile = self.as_user('/api/session', h.ALICE)[1]['user']
        self.assertEqual(self.as_user('/api/register', h.ALICE, consent=True,
                                      agency_rate=999999, blogger_payout=999999,
                                      source='referral', referrer_id=h.BOB)[0], 200)
        self.assertEqual(self.as_user('/api/session', h.ALICE)[1]['user'], profile)
        with closing(sqlite3.connect(self.db_path)) as conn:
            cols = [r[1] for r in conn.execute('PRAGMA table_info(users)')]
            self.assertNotIn('agency_rate', cols)
            self.assertNotIn('blogger_payout', cols)
