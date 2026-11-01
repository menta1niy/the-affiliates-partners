"""Monotonic CRM offer snapshots; valid delayed messages cannot resurrect revoked terms."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from server import db


class OfferSnapshotOrderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="snapshot-order-")
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {
            "PARTNERS_DB_PATH": self.directory.name + "/partners.sqlite3",
            "PARTNERS_DATABASE_URL": "",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        db.initialize()
        with db.transaction() as conn:
            now = int(time.time())
            conn.execute("INSERT INTO users(id,first_name,role,status,registered_at,updated_at,consent_at) "
                         "VALUES(?,?,?,?,?,?,?)", (987001, "Test", "lead", "active", now, now, now))
            conn.execute("INSERT INTO crm_lead_bindings(crm_lead_id,telegram_id,bound_at) VALUES(?,?,?)",
                         ("crm-lead-test", 987001, now))

    def send(self, event_id, version, offers):
        payload = {"event_id": event_id, "type": "offers.assigned",
                   "crm_lead_id": "crm-lead-test", "telegram_id": 987001, "offers": offers}
        if version is not None:
            payload["snapshot_version"] = version
        return db.receive_crm_event(payload)

    def shown(self):
        return db.list_assigned_offers(987001, 0)

    def test_delayed_published_snapshot_cannot_restore_old_instructions(self):
        self.assertEqual(self.send("v1", 1, [{"id": "a", "name": "old"}]), {"changed": True})
        self.assertEqual(self.send("v3", 3, [{"id": "a", "name": "new"}]), {"changed": True})
        self.assertEqual(self.send("v2-delayed", 2, [{"id": "a", "name": "stale"}]), {"changed": True})
        self.assertEqual(self.shown()[0]["name"], "new")
        self.assertEqual(self.send("legacy-delayed", None, [{"id": "a", "name": "legacy"}]), {"changed": True})
        self.assertEqual(self.shown()[0]["name"], "new")

    def test_revocation_empty_snapshot_cannot_be_undone(self):
        self.send("published", 10, [{"id": "a", "name": "published"}])
        self.send("revoked", 11, [])
        self.send("delayed", 10, [{"id": "a", "name": "published"}])
        self.assertEqual(self.shown(), [])
        self.send("reissued", 12, [{"id": "a", "name": "reissued"}])
        self.assertEqual(self.shown()[0]["name"], "reissued")

    def test_legacy_compatibility_and_reject_malformed(self):
        self.send("legacy-first", None, [{"id": "a", "name": "old"}])
        self.send("legacy-next", None, [{"id": "a", "name": "legacy-updated"}])
        self.assertEqual(self.shown()[0]["name"], "legacy-updated")
        for value in (0, -1, True, "3", 2 ** 63):
            with self.subTest(value=value), self.assertRaises(db.Problem):
                self.send("bad-" + str(value), value, [])
        self.assertEqual(self.shown()[0]["name"], "legacy-updated")
