"""End-to-end owner-selected CRM identity check with isolated SQL and HTTP."""
import json
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


class IdentityBridgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.workspace = str(uuid4())
        self.blogger = str(uuid4())
        self.partner = sqlite3.connect(":memory:")
        self.crm = sqlite3.connect(":memory:")
        self.addCleanup(self.partner.close)
        self.addCleanup(self.crm.close)
        self.partner.execute(
            "CREATE TABLE partners (telegram_id INTEGER PRIMARY KEY, phone TEXT, status TEXT)"
        )
        self.partner.execute(
            "INSERT INTO partners VALUES (77, '+79990000000', 'active')"
        )
        self.crm.execute(
            "CREATE TABLE bloggers (id TEXT, workspace_id TEXT, archived_at TEXT)"
        )
        self.crm.executemany("INSERT INTO bloggers VALUES (?,?,?)", [
            (self.blogger.upper(), self.workspace, None),
            (str(uuid4()), str(uuid4()), None),
            (str(uuid4()), self.workspace, "2026-10-30"),
        ])
        crm_identity.owner_assign(self.partner, 77, self.workspace, self.blogger)
        self.calls = []
        case = self

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, statement, params=None):
                case.calls.append(("sql", str(statement), params))
                if params is None:
                    return None
                rows = case.crm.execute(
                    "SELECT id FROM bloggers WHERE workspace_id=? AND archived_at IS NULL",
                    (params["workspace"],)
                ).fetchall()
                return types.SimpleNamespace(all=lambda: rows)

        class Engine:
            def connect(self):
                return Connection()

            def dispose(self):
                case.calls.append(("dispose",))

        self.sqlalchemy = types.SimpleNamespace(
            create_engine=lambda *args, **kwargs: Engine(), text=str
        )

    def bridge(self, tamper=None):
        def http(request):
            body = json.loads(request.data)
            self.calls.append(("http", request.full_url, body))
            if request.full_url.endswith("/requests"):
                mappings = crm_identity.issue_checks(self.partner, self.workspace)
                if tamper is not None:
                    mappings = tamper(mappings)
                return {"mappings": mappings}
            assert request.full_url.endswith("/identity")
            with self.partner:
                verified = crm_identity.attest(
                    self.partner, self.workspace, body["attestations"], 500
                )
            return {"ok": True, "verified": verified}

        with patch.dict(sys.modules, {"sqlalchemy": self.sqlalchemy}), patch.object(
            crm_publisher, "send_with_retry", side_effect=http
        ):
            return crm_publisher.verify_partner_links(
                "https://partners.example/api/internal/crm/offers",
                "s" * 40, "postgresql://read-only", self.workspace
            )

    def test_existing_scoped_blogger_is_verified_and_recheck_recovers(self):
        self.assertEqual(self.bridge(), 1)
        self.assertEqual(self.partner.execute(
            "SELECT verified FROM crm_partner_links WHERE telegram_id=77"
        ).fetchone()[0], 1)
        self.crm.execute("UPDATE bloggers SET archived_at='2026-10-31' WHERE id=?",
                         (self.blogger.upper(),))
        self.assertEqual(self.bridge(), 0)
        self.assertEqual(self.partner.execute(
            "SELECT verified FROM crm_partner_links WHERE telegram_id=77"
        ).fetchone()[0], 0)
        self.crm.execute("UPDATE bloggers SET archived_at=NULL WHERE id=?",
                         (self.blogger.upper(),))
        self.assertEqual(self.bridge(), 1)
        self.assertEqual(self.partner.execute(
            "SELECT verified FROM crm_partner_links WHERE telegram_id=77"
        ).fetchone()[0], 1)
        self.assertEqual(len([call for call in self.calls if call[0] == "dispose"]), 3)
        self.assertTrue(all("workspace_id=:workspace" in call[1] for call in self.calls
                            if call[0] == "sql" and call[2] is not None))

    def test_invalid_request_rejected_without_database_access_or_attestation(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.bridge(lambda rows: rows + rows)
        self.assertFalse(any(call[0] == "sql" for call in self.calls))
        self.assertFalse(any(call[0] == "http" and call[1].endswith("/identity")
                             for call in self.calls))

    def test_no_pending_requests_skips_database_access(self):
        self.partner.execute("DELETE FROM crm_partner_links")
        self.assertEqual(self.bridge(), 0)
        self.assertFalse(any(call[0] == "sql" for call in self.calls))

    def test_http_failure_does_not_falsely_confirm_identity(self):
        with patch.dict(sys.modules, {"sqlalchemy": self.sqlalchemy}), patch.object(
            crm_publisher, "send_with_retry", side_effect=RuntimeError("offline")
        ):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                crm_publisher.verify_partner_links(
                    "https://partners.example/api/internal/crm/offers",
                    "s" * 40, "postgresql://read-only", self.workspace
                )
        self.assertEqual(self.partner.execute(
            "SELECT verified FROM crm_partner_links WHERE telegram_id=77"
        ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
