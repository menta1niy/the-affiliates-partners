"""Separate owner authorization from read-only CRM existence attestation."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import app
from test_signed_auth import signed_data


class CRMIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(app, "DB", Path(self.tmp.name) / "identity.sqlite3")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.token_patch = patch.object(app, "TOKEN", "test-bot-token")
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)
        self.workspace = str(uuid4())
        self.service_patch = patch.dict(os.environ, {"CRM_FEED_TOKEN": "x"*40,
            "CRM_WORKSPACE_ID": self.workspace})
        self.service_patch.start()
        self.addCleanup(self.service_patch.stop)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        with app.db() as conn:
            conn.execute("""INSERT INTO partners(telegram_id,phone,status,created_at)
                VALUES(12345,'+79990000001','active',1),(12346,'+79990000002','active',1)""")

    def send(self, route, data, owner=None, service=False):
        if owner is not None:
            data = {"initData": signed_data(owner), **data}
        headers = {"Content-Type": "application/json"}
        if service:
            headers["X-CRM-Feed-Token"] = "x"*40
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.http.server_port}{route}",
            json.dumps(data).encode(), headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=4) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_owner_proposes_and_service_attests_without_role_escalation(self):
        blogger = str(uuid4())
        route = "/api/admin/partners/crm-link"
        data = {"telegram_id":12345,"blogger_id":blogger}
        self.assertEqual(self.send(route,data,owner=12345)[0],403)
        self.assertEqual(self.send(route,data,owner=app.ADMIN_ID)[0],200)
        self.assertFalse(self.send("/api/me",{},owner=12345)[1]["profile"]["crmLinked"])
        self.assertEqual(self.send("/api/internal/crm/identity/requests",
            {"workspace_id":self.workspace},service=True)[1]["blogger_ids"],[blogger])
        code,_ = self.send("/api/internal/crm/identity",
            {"workspace_id":self.workspace,"blogger_ids":[blogger]},service=False)
        self.assertEqual(code,403)
        self.assertEqual(self.send("/api/internal/crm/identity",
            {"workspace_id":self.workspace,"blogger_ids":[blogger]},service=True)[0],200)
        linked = self.send("/api/me",{},owner=12345)[1]
        self.assertTrue(linked["profile"]["crmLinked"])
        self.assertFalse(linked["isAdmin"])
        # Repeating the same trusted owner's assertion is idempotent.
        self.assertEqual(self.send(route,data,owner=app.ADMIN_ID)[0],200)
        self.assertTrue(self.send("/api/me",{},owner=12345)[1]["profile"]["crmLinked"])
        self.assertEqual(self.send("/api/admin/snapshot",{},owner=12345)[0],403)
        self.assertEqual(self.send(route,{"telegram_id":12346,"blogger_id":blogger},
            owner=app.ADMIN_ID)[0],400)


if __name__ == "__main__":
    unittest.main()
