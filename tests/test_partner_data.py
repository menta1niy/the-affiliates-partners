"""Authenticated partner-only data availability, without fabricated finance."""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from uuid import uuid4
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import app
from test_signed_auth import signed_data


class PartnerDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(app, "DB", Path(self.temp.name) / "test.sqlite3")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.token_patch = patch.object(app, "TOKEN", "test-bot-token")
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def post(self, endpoint, uid):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.http.server_port}{endpoint}",
            json.dumps({"initData":signed_data(uid)}).encode("utf-8"),
            headers={"Content-Type":"application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_pending_rejected_and_approved_partner_data(self):
        uid = 28491
        self.post("/api/me", uid)
        self.assertEqual(self.post("/api/partner/data", uid)[0], 403)
        self.assertEqual(self.post("/api/links/not-an-offer", uid)[0], 403)
        with app.db() as conn:
            conn.execute("UPDATE partners SET phone=?,status='active' WHERE telegram_id=?",
                         ("+79990000000", uid))
        code, result = self.post("/api/partner/data", uid)
        self.assertEqual(code, 200)
        self.assertEqual(result["tracking"]["available"], False)
        self.assertEqual(result["conversions"]["available"], False)
        self.assertEqual(result["payments"]["available"], False)
        self.assertFalse(result["crmLinked"])
        self.assertEqual(result["crmLinkStatus"], "unlinked")
        with app.db() as conn:
            conn.execute("""INSERT INTO crm_partner_links(
                telegram_id,workspace_id,blogger_id,verified,confirmed_at,mapping_version,check_version)
                VALUES(?,?,?,?,?,?,?)""",
                (uid,str(uuid4()),str(uuid4()),0,0,str(uuid4()),""))
        self.assertEqual(self.post("/api/partner/data",uid)[1]["crmLinkStatus"],"pending")
        with app.db() as conn:
            conn.execute("UPDATE crm_partner_links SET verified=1 WHERE telegram_id=?",(uid,))
        response = self.post("/api/partner/data",uid)[1]
        self.assertEqual(response["crmLinkStatus"],"verified")
        self.assertTrue(response["crmLinked"])
        self.assertFalse(response["tracking"]["available"])
        with app.db() as conn:
            conn.execute("DELETE FROM crm_partner_links WHERE telegram_id=?",(uid,))
        self.assertEqual(self.post("/api/partner/data",uid)[1]["crmLinkStatus"],"unlinked")
        self.assertFalse({"agency_rate","agency_profit","blogger_accrual"} & set(str(result).split()))
        self.assertEqual(self.post("/api/links/not-an-offer", uid)[0], 404)
        with app.db() as conn:
            conn.execute("UPDATE partners SET status='rejected' WHERE telegram_id=?", (uid,))
        self.assertEqual(self.post("/api/partner/data", uid)[0], 403)


if __name__ == "__main__":
    unittest.main()
