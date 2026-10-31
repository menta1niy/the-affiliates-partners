"""Check-once CRM identity attestations and the real publisher wire contract."""
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import crm_identity
import crm_publisher


class IdentityRecheckTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.execute("CREATE TABLE partners (telegram_id INTEGER PRIMARY KEY, phone TEXT, status TEXT)")
        self.conn.execute("INSERT INTO partners VALUES (7, '+79990000000', 'active')")
        self.workspace, self.blogger = str(uuid4()), str(uuid4())
        crm_identity.owner_assign(self.conn, 7, self.workspace, self.blogger)

    def test_attestation_is_consumed_and_cannot_replay_a_previous_decision(self):
        first = crm_identity.issue_checks(self.conn, self.workspace)[0]
        self.assertEqual(crm_identity.attest(self.conn, self.workspace, [{**first, "exists": True}], 100), 1)
        self.assertEqual(crm_identity.attest(self.conn, self.workspace, [{**first, "exists": False}], 101), 0)
        self.assertEqual(self.conn.execute("SELECT verified,confirmed_at FROM crm_partner_links").fetchone(), (1, 100))
        second = crm_identity.issue_checks(self.conn, self.workspace)[0]
        self.assertEqual(crm_identity.attest(self.conn, self.workspace, [{**second, "exists": False}], 102), 0)
        self.assertEqual(crm_identity.attest(self.conn, self.workspace, [{**first, "exists": True}], 103), 0)
        self.assertEqual(self.conn.execute("SELECT verified,confirmed_at FROM crm_partner_links").fetchone(), (0, 0))

    def test_failed_multi_attestation_rolls_back_with_transaction(self):
        self.conn.execute("INSERT INTO partners VALUES (8, '+79990000001', 'active')")
        other = str(uuid4())
        crm_identity.owner_assign(self.conn, 8, self.workspace, other)
        checks = crm_identity.issue_checks(self.conn, self.workspace)
        self.conn.commit()
        self.conn.execute("""CREATE TRIGGER block_second BEFORE UPDATE OF verified ON crm_partner_links
            WHEN NEW.telegram_id=8 BEGIN SELECT RAISE(ABORT, 'simulated failure'); END""")
        self.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                crm_identity.attest(self.conn, self.workspace,
                                    [{**check, "exists": True} for check in checks], 100)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM crm_partner_links WHERE verified=1").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM crm_partner_links WHERE check_version<>''").fetchone()[0], 2)

    def test_publisher_echoes_check_version_and_filters_scoped_active_bloggers(self):
        check = crm_identity.issue_checks(self.conn, self.workspace)[0]
        calls = []

        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def execute(self, statement, params=None):
                calls.append((str(statement), params))
                if params:
                    return types.SimpleNamespace(all=lambda: [(self_blogger,)])
                return None

        class FakeEngine:
            def connect(self):
                return FakeConnection()
            def dispose(self):
                pass

        self_blogger = self.blogger
        def service(url, body):
            if url.endswith("/requests"):
                return {"mappings": [check]}
            self.assertEqual(body["attestations"], [{**check, "exists": True}])
            return {"ok": True, "verified": 1}

        def fake_retry(req):
            import json
            return service(req.full_url, json.loads(req.data))

        fake_sqlalchemy = types.SimpleNamespace(create_engine=lambda *_args, **_kwargs: FakeEngine(), text=str)
        with patch.dict(sys.modules, {"sqlalchemy": fake_sqlalchemy}), patch.object(
            crm_publisher, "send_with_retry", side_effect=fake_retry
        ):
            verified = crm_publisher.verify_partner_links(
                "https://example.org/api/internal/crm/offers", "a" * 40, "postgresql://unused", self.workspace)
        self.assertEqual(verified, 1)
        self.assertIn("archived_at IS NULL", calls[1][0])
        self.assertEqual(calls[1][1], {"workspace": self.workspace})


if __name__ == "__main__":
    unittest.main()
