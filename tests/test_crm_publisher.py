"""Test real CRM offer field projection without a live PostgreSQL credential."""
import sys
import unittest
import json
import urllib.error
import io
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import crm_publisher


class PublisherTests(unittest.TestCase):
    def test_projection_excludes_finance_and_requires_workspace(self):
        workspace = uuid4()
        offer = uuid4()
        source = {"id": offer, "workspace_id": workspace, "name": "Card",
                  "offer_type": "debit", "target_action": "Issued",
                  "is_active": True, "agency_rate": "1000",
                  "agency_profit": "999", "blogger_payout": "500"}
        public = crm_publisher.sanitized_offers([source], workspace)
        self.assertEqual(public, [{"id": str(offer), "name": "Card", "offer_type": "debit",
                                   "target_action": "Issued", "is_active": True}])
        with self.assertRaises(ValueError):
            crm_publisher.sanitized_offers([source], uuid4())

    def test_publisher_rejects_insecure_target_before_network(self):
        with patch.object(crm_publisher, "safe_urlopen") as opener:
            with self.assertRaises(ValueError):
                crm_publisher.publish("http://example.org/feed", "t"*40, uuid4(), [{}])
            with self.assertRaises(ValueError):
                crm_publisher.publish("https://example.org/feed", "short", uuid4(), [{}])
            opener.assert_not_called()

    def test_partial_failure_never_finalizes_snapshot(self):
        workspace = uuid4()
        rows = [
            {"id": str(uuid4()), "name": "Card", "offer_type": "debit",
             "target_action": "Issued", "is_active": True}
            for _ in range(110)
        ]
        seen = []

        class Response(io.BytesIO):
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                self.close()

        def service(request, timeout):
            payload = json.loads(request.data)
            seen.append(payload)
            if len(seen) >= 2:
                raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)
            return Response(json.dumps({"ok": True, "state": "pending"}).encode())

        with patch.object(crm_publisher, "safe_urlopen", side_effect=service), patch.object(
            crm_publisher.time, "sleep"
        ):
            with self.assertRaisesRegex(RuntimeError, "retry with same --run-id"):
                crm_publisher.publish("https://example.org/feed", "t"*40, workspace, rows)
        self.assertTrue(seen)
        self.assertTrue(all(request.get("mode") != "finalize" for request in seen))

    def test_retry_same_run_id_recovers_after_failed_batch(self):
        workspace, run_id, offer_id = uuid4(), str(uuid4()), str(uuid4())
        offer = {"id": offer_id, "name": "Verified", "offer_type": "debit",
                 "target_action": "Card", "is_active": True}
        seen, fail = [], [True]

        class Response(io.BytesIO):
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                self.close()

        def service(req, timeout):
            data = json.loads(req.data)
            seen.append(data)
            if data["mode"] == "batch" and fail[0]:
                fail[0] = False
                raise urllib.error.HTTPError(req.full_url, 403, "temporary simulation", {}, None)
            result = {"ok": True, "state": "pending"}
            if data["mode"] == "batch":
                result["received"] = 1
            return Response(json.dumps(result).encode())

        with patch.object(crm_publisher, "safe_urlopen", side_effect=service):
            with self.assertRaisesRegex(RuntimeError, run_id):
                crm_publisher.publish("https://example.org/feed", "t"*40,
                                      workspace, [offer], run_id=run_id)
            self.assertEqual(crm_publisher.publish("https://example.org/feed", "t"*40,
                                                 workspace, [offer], run_id=run_id), 1)
        self.assertEqual({item["run_id"] for item in seen}, {run_id})
        self.assertEqual(seen[-1]["mode"], "commit")

    def test_completed_run_rechecks_digest_without_replaying_batches(self):
        workspace, run_id = uuid4(), str(uuid4())
        offer = {"id": str(uuid4()), "name": "Bank", "offer_type": "debit",
                 "target_action": "Card", "is_active": True}
        seen = []
        class Response(io.BytesIO):
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                self.close()
        def service(req, timeout):
            payload = json.loads(req.data)
            seen.append(payload)
            return Response(json.dumps({"ok": True, "state": "complete"}).encode())
        with patch.object(crm_publisher, "safe_urlopen", side_effect=service):
            self.assertEqual(crm_publisher.publish("https://example.org/feed",
                "t"*40, workspace, [offer], run_id=run_id), 1)
        self.assertEqual([payload["mode"] for payload in seen], ["begin", "commit"])


if __name__ == "__main__":
    unittest.main()
