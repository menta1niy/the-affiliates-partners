import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import db, legacy_registration_backfill


class LegacyBackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"PARTNERS_DB_PATH": str(Path(self.temp.name) / "db.sqlite"),
                                        "PARTNERS_DATABASE_URL": "", "PARTNERS_REQUIRE_POSTGRES": "false",
                                        "PARTNERS_PG_SCHEMA_READY": "false"})
        self.env.start()
        db.initialize()
        with db.transaction() as conn:
            conn.execute("INSERT INTO users(id,first_name,role,status,registered_at,updated_at) "
                         "VALUES(10,'Owner','owner','active',1,1)")
            conn.execute("INSERT INTO users(id,first_name,role,status,registered_at,updated_at) "
                         "VALUES(11,'Referrer','referrer','active',1,1)")

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def add(self, identifier, *, source="referral", referral=11, consent=1, status="active", role="lead", audit=True):
        with db.transaction() as conn:
            conn.execute("INSERT INTO users(id,first_name,role,status,registered_at,updated_at,source,referrer_id,consent_at) "
                         "VALUES(?,?,?,?,1,1,?,?,?)", (identifier, 'Legacy', role, status, source, referral, consent))
            if audit:
                conn.execute("INSERT INTO audit(actor_id,action,target_id,details,created_at) "
                             "VALUES(?,'register',?,'source=referral',1)", (identifier, identifier))

    def count(self):
        with db.transaction() as conn:
            return conn.execute("SELECT count(*) FROM crm_registration_outbox").fetchone()[0]

    def test_valid_referral_preview_and_idempotent_apply(self):
        self.add(25)
        self.assertEqual(legacy_registration_backfill.backfill()["eligible"], 1)
        self.assertEqual(self.count(), 0)
        self.assertEqual(legacy_registration_backfill.backfill(apply=True)["created"], 1)
        self.assertEqual(legacy_registration_backfill.backfill(apply=True)["created"], 0)
        with db.transaction() as conn:
            payload = json.loads(conn.execute("SELECT payload FROM crm_registration_outbox WHERE telegram_id=25").fetchone()[0])
        self.assertEqual((payload["source_type"], payload["source_partner_id"]), ("referrer", "referrer:11"))

    def test_unknown_source_and_missing_audit_are_excluded(self):
        self.add(26, source=None)
        self.add(27, audit=False)
        self.add(28, referral=None)
        self.assertEqual(legacy_registration_backfill.backfill(apply=True)["created"], 0)
        self.assertEqual(self.count(), 0)

    def test_owner_and_existing_outbox_excluded(self):
        self.add(29, role="owner")
        self.add(30)
        with db.transaction() as conn:
            conn.execute("INSERT INTO crm_registration_outbox(telegram_id,payload,created_at) VALUES(30,'{}',1)")
        self.assertEqual(legacy_registration_backfill.backfill(apply=True)["created"], 0)
        self.assertEqual(self.count(), 1)


if __name__ == "__main__":
    unittest.main()
