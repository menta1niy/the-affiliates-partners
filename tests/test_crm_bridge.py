"""CRM boundary contracts: signatures, replay window, and transport identity."""
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import patch

from server import integration


KEY = "test-only-long-random-integration-secret-123456789"


class CRMBridgeTests(unittest.TestCase):
    def setUp(self):
        self.event = {"event_id": "crm:123", "type": "offer.updated", "offer_id": "42"}
        self.payload = json.dumps(self.event).encode("utf-8")
        self.now = int(time.time())
        self.digest = integration.signature(self.payload, self.now, KEY)

    def test_signature_contract_and_tamper_detection(self):
        expected = hmac.new(KEY.encode(), str(self.now).encode() + b"\n" + self.payload, hashlib.sha256).hexdigest()
        self.assertEqual(self.digest, expected)
        self.assertEqual(integration.verify(self.payload, str(self.now), expected, KEY, now=self.now,
                                            event_id_header="crm:123"), self.event)
        for body, timestamp, signature, event_id in (
            (self.payload + b" ", str(self.now), expected, "crm:123"),
            (self.payload, str(self.now + 301), expected, "crm:123"),
            (self.payload, str(self.now), "0" * 64, "crm:123"),
            (self.payload, str(self.now), expected, "crm:124"),
        ):
            with self.subTest(body=body, timestamp=timestamp, event_id=event_id):
                with self.assertRaises(integration.BridgeError):
                    integration.verify(body, timestamp, signature, KEY, now=self.now, event_id_header=event_id)

    def test_reject_malformed_and_unconfigured(self):
        for data in (b"[]", b"{}", b"{", b"{}" + b" " * integration.MAX_BODY):
            digest = integration.signature(data, self.now, KEY)
            with self.assertRaises(integration.BridgeError):
                integration.verify(data, str(self.now), digest, KEY, now=self.now)
        with self.assertRaises(integration.BridgeError):
            integration.signature(self.payload, self.now, "short")

    def test_delivery_uses_auth_headers_and_does_not_follow_http(self):
        with self.assertRaises(integration.BridgeError):
            integration.deliver("http://crm.example/events", self.event, key=KEY)
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b'{"accepted":true}'

        with patch.object(integration.urllib.request, "urlopen", return_value=Response()) as mocked:
            self.assertEqual(integration.deliver("https://crm.example/events", self.event, key=KEY), {"accepted": True})
            request = mocked.call_args.args[0]
            self.assertEqual(request.get_header("X-ta-event-id"), self.event["event_id"])
            integration.verify(request.data, request.get_header("X-ta-timestamp"),
                               request.get_header("X-ta-signature"), KEY,
                               event_id_header=request.get_header("X-ta-event-id"))


if __name__ == "__main__":
    unittest.main()
