"""Test real CRM offer field projection without a live PostgreSQL credential."""
import sys
import unittest
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
        with patch.object(crm_publisher.urllib.request, "urlopen") as opener:
            with self.assertRaises(ValueError):
                crm_publisher.publish("http://example.org/feed", "t"*40, uuid4(), [{}])
            with self.assertRaises(ValueError):
                crm_publisher.publish("https://example.org/feed", "short", uuid4(), [{}])
            opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
