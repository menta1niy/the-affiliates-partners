"""Real localhost Partners HTTP identity bridge; CRM SQL is isolated and read-only."""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import app
import crm_publisher


class IdentityHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "partners.sqlite"
        self.workspace = str(uuid4())
        self.blogger = str(uuid4())
        self.other = str(uuid4())
        self.token = "isolated-service-key-" + "x" * 40
        self.env = patch.dict(os.environ, {
            "CRM_FEED_TOKEN": self.token, "CRM_WORKSPACE_ID": self.workspace,
            "PARTNERS_DB_PATH": str(self.db_path),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db_patch = patch.object(app, "DB", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        with app.db() as conn:
            conn.execute("INSERT INTO partners(telegram_id,phone,status,created_at) VALUES (77,?, 'active',0)",
                         ("+79990000000",))
            app.owner_assign(conn, 77, self.workspace, self.blogger)
        self.crm = sqlite3.connect(":memory:")
        self.addCleanup(self.crm.close)
        self.crm.execute("CREATE TABLE bloggers(id TEXT, workspace_id TEXT, archived_at TEXT)")
        self.crm.executemany("INSERT INTO bloggers VALUES (?,?,?)", [
            (self.blogger.upper(), self.workspace, None),
            (self.other, str(uuid4()), None),
            (str(uuid4()), self.workspace, "2026-10-30"),
        ])
        self.sql_calls = []
        case = self

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, statement, params=None):
                sql = str(statement)
                case.sql_calls.append((sql, params))
                if params is None:
                    if sql != "SET TRANSACTION READ ONLY":
                        raise AssertionError("Unexpected transaction command")
                    return None
                if ("SELECT id FROM bloggers" not in sql
                        or "workspace_id=:workspace" not in sql
                        or "archived_at IS NULL" not in sql
                        or set(params) != {"workspace"}):
                    raise AssertionError("Unexpected CRM query")
                rows = case.crm.execute(
                    "SELECT id FROM bloggers WHERE workspace_id=? AND archived_at IS NULL",
                    (params["workspace"],)
                ).fetchall()
                return types.SimpleNamespace(all=lambda: rows)

        class Engine:
            def connect(self):
                return Connection()

            def dispose(self):
                pass

        self.fake_sqlalchemy = types.SimpleNamespace(
            create_engine=lambda *_args, **_kwargs: Engine(), text=str)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown_server)
        self.root = f"http://127.0.0.1:{self.server.server_port}/api/internal/crm"

    def shutdown_server(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request(self, path, body, token=None):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-CRM-Feed-Token"] = token
        request = urllib.request.Request(
            self.root + path, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def rows(self):
        with app.db() as conn:
            return conn.execute(
                "SELECT telegram_id,blogger_id,verified,confirmed_at,check_version "
                "FROM crm_partner_links ORDER BY telegram_id").fetchall()

    def bridge(self):
        # Only the localhost wire-test transport bypasses the publisher HTTPS
        # scheme validation. The actual urllib HTTP requests remain unmocked.
        original_parse = urlparse
        def local_parse(value):
            return original_parse("https://" + value[7:] if value.startswith(self.root) else value)
        with patch.dict(sys.modules, {"sqlalchemy": self.fake_sqlalchemy}), patch.object(
            crm_publisher, "urlparse", side_effect=local_parse
        ):
            return crm_publisher.verify_partner_links(
                self.root + "/offers", self.token, "postgresql://read-only", self.workspace)

    def test_real_http_positive_negative_recheck_and_restart_persistence(self):
        self.assertEqual(self.bridge(), 1)
        self.assertEqual(self.rows()[0][2], 1)
        self.assertGreater(self.rows()[0][3], 0)
        self.crm.execute("UPDATE bloggers SET archived_at='now' WHERE id=?",
                         (self.blogger.upper(),))
        self.assertEqual(self.bridge(), 0)
        self.assertEqual(self.rows()[0][2:4], (0, 0))
        self.shutdown_server()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.root = f"http://127.0.0.1:{self.server.server_port}/api/internal/crm"
        self.assertEqual(self.rows()[0][2:4], (0, 0))
        self.crm.execute("UPDATE bloggers SET archived_at=NULL WHERE id=?",
                         (self.blogger.upper(),))
        self.assertEqual(self.bridge(), 1)
        self.assertEqual(self.rows()[0][2], 1)
        self.assertEqual(len([item for item in self.sql_calls if item[1] is not None]), 3)

    def test_token_enforcement_stale_replay_and_mapping_conflict(self):
        body = {"workspace_id": self.workspace}
        self.assertEqual(self.request("/identity/requests", body)[0], 403)
        self.assertEqual(self.request("/identity/requests", body, "wrong" * 10)[0], 403)
        self.assertEqual(self.rows()[0][2], 0)
        status, first = self.request("/identity/requests", body, self.token)
        self.assertEqual(status, 200)
        old = {**first["mappings"][0], "exists": True}
        status, second = self.request("/identity/requests", body, self.token)
        self.assertEqual(status, 200)
        current = {**second["mappings"][0], "exists": False}
        self.assertNotEqual(old["check_version"], current["check_version"])
        payload = lambda rows: {"workspace_id": self.workspace, "attestations": rows}
        self.assertEqual(self.request("/identity", payload([old]), self.token),
                         (200, {"ok": True, "verified": 0}))
        self.assertEqual(self.request("/identity", payload([current]), self.token),
                         (200, {"ok": True, "verified": 0}))
        self.assertEqual(self.request("/identity", payload([old]), self.token)[1]["verified"], 0)
        self.assertEqual(self.rows()[0][2:4], (0, 0))
        with app.db() as conn:
            conn.execute("INSERT INTO partners(telegram_id,phone,status,created_at) VALUES (88,'+79990000001','active',0)")
            with self.assertRaises(sqlite3.IntegrityError):
                app.owner_assign(conn, 88, self.workspace, self.blogger)
        self.assertEqual(len(self.rows()), 1)

    def test_public_http_rejected_by_publisher_before_request(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            crm_publisher.verify_partner_links(
                self.root + "/offers", self.token, "postgresql://read-only", self.workspace)


if __name__ == "__main__":
    unittest.main()
