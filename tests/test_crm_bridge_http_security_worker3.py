"""Independent HTTP boundary coverage; isolated test DB, no production services."""
import json
import time
import unittest
from unittest.mock import patch

from server import db, integration
from tests import test_registration as h

KEY = "worker3-isolated-integration-secret-123456789"


class CRMBridgeHTTPSecurity(unittest.TestCase):
    setUp = h.HttpHarness.setUp
    stop_server = h.HttpHarness.stop_server
    post = h.HttpHarness.post
    as_user = h.HttpHarness.as_user

    def signed(self, event, *, when=None, key=KEY, signature=None, event_header=None):
        now = int(time.time()) if when is None else when
        # Match the shared HTTP harness's exact transmitted JSON bytes.
        raw = json.dumps(event, ensure_ascii=False).encode('utf-8')
        headers = {
            'X-TA-Timestamp': str(now),
            'X-TA-Signature': signature or integration.signature(raw, now, key),
            'X-TA-Event-ID': event_header or event['event_id'],
        }
        return self.post('/api/integration/crm/events', event, headers=headers)

    def test_http_rejects_forgery_expiry_and_event_id_mismatch_before_storage(self):
        event = {'event_id': 'worker3:1', 'type': 'offer.updated', 'offer_id': 'private-1'}
        with patch.dict('os.environ', {'PARTNERS_CRM_SHARED_SECRET': KEY}), patch.object(
            db, 'receive_crm_event', create=True, return_value={'accepted': True}
        ) as receive:
            now = int(time.time())
            self.assertEqual(self.signed(event, signature='0' * 64)[0], 401)
            self.assertEqual(self.signed(event, when=now - 301)[0], 401)
            self.assertEqual(self.signed(event, when=now + 301)[0], 401)
            self.assertEqual(self.signed(event, event_header='different-event-id')[0], 401)
            self.assertEqual(self.signed(event, key='wrong-secret-12345678901234567890123')[0], 401)
            receive.assert_not_called()
            self.assertEqual(self.signed(event)[0], 200)
            receive.assert_called_once_with(event)

    def test_signed_offers_requires_telegram_identity_and_storage_scope(self):
        self.assertEqual(self.post('/api/offers', {'initData': 'forged'})[0], 401)
        with patch.object(db, 'list_assigned_offers', create=True,
                          side_effect=lambda actor, owner: [{'id': 'only-' + str(actor)}]) as listing:
            for uid in (h.ALICE, h.BOB):
                status, result = self.as_user('/api/offers', uid)
                self.assertEqual(status, 200, result)
                self.assertEqual(result['offers'], [{'id': 'only-' + str(uid)}])
            self.assertEqual(listing.call_count, 2)
            self.assertEqual([call.args[0] for call in listing.call_args_list], [h.ALICE, h.BOB])
