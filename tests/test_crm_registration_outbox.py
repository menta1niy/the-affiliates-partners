import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import crm_registration, db


class OutboundRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "PARTNERS_DB_PATH": str(Path(self.tmp.name) / "test.sqlite3"),
            "PARTNERS_CRM_BASE_URL": "https://crm.example",
            "PARTNERS_CRM_WORKSPACE_ID": "00000000-0000-4000-8000-000000000001",
            "PARTNERS_CRM_SHARED_SECRET": "s" * 40,
        })
        self.env.start()
        db.initialize()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def create_consent(self):
        with db.transaction() as conn:
            conn.execute("INSERT INTO users(id,internal_id,first_name,role,status,registered_at,updated_at,consent_at,source) "
                         "VALUES(23,123,'Alice','lead','pending',1,1,1,'agency')")
            conn.execute("INSERT INTO crm_registration_outbox(telegram_id,payload,created_at) VALUES(?,?,1)",
                         (23, json.dumps({"name": "Alice", "telegram_user_id": 23, "source_type": "agency",
                                          "source_partner_id": "agency:1", "source_external_id": "partners:lead:23"})))

    def test_retry_then_success_and_signed_binding(self):
        self.create_consent()
        def failed(*args):
            raise ConnectionError("offline")
        self.assertEqual(crm_registration.dispatch_once(sender=failed, now=100)["failed"], 1)
        self.assertEqual(crm_registration.dispatch_once(sender=lambda *args: "crm-23", now=101)["claimed"], 0)
        self.assertEqual(crm_registration.dispatch_once(sender=lambda *args: "crm-23", now=161)["delivered"], 1)
        self.assertEqual(crm_registration.dispatch_once(sender=lambda *args: "unexpected", now=162)["claimed"], 0)
        with self.assertRaises(db.Problem):
            db.receive_crm_event({"event_id": "wrong", "type": "lead.bound", "telegram_id": 23, "crm_lead_id": "other"})
        self.assertEqual(db.receive_crm_event({"event_id": "correct", "type": "lead.bound", "telegram_id": 23, "crm_lead_id": "crm-23"}), {"changed": True})
        self.assertEqual(db.receive_crm_event({"event_id": "correct", "type": "lead.bound", "telegram_id": 23, "crm_lead_id": "crm-23"}), {"changed": False})

    def test_unconsented_cannot_be_bound(self):
        with db.transaction() as conn:
            conn.execute("INSERT INTO users(id,internal_id,first_name,role,status,registered_at,updated_at) "
                         "VALUES(24,124,'Bob','lead','pending',1,1)")
        with self.assertRaises(db.Problem):
            db.receive_crm_event({"event_id": "no-consent", "type": "lead.bound", "telegram_id": 24, "crm_lead_id": "crm-24"})


if __name__ == "__main__":
    unittest.main()
