"""Opt-in CRM DTO ingestion: no private workspace finance fields or public publish."""
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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import app


class CRMFeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(app, "DB", Path(self.tmp.name) / "test.sqlite3")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def submit(self, body, token=None):
        url = f"http://127.0.0.1:{self.server.server_port}/api/internal/crm/offers"
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-CRM-Feed-Token"] = token
        req = urllib.request.Request(url, json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=4) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_disabled_by_default_and_rejects_bad_credentials(self):
        with patch.dict(os.environ, {"CRM_FEED_TOKEN": "", "CRM_WORKSPACE_ID": ""}):
            self.assertEqual(self.submit({})[0], 503)
        with patch.dict(os.environ, {"CRM_FEED_TOKEN": "a"*40, "CRM_WORKSPACE_ID": "workspace-1"}):
            self.assertEqual(self.submit({})[0], 403)

    def test_verified_workspace_stays_draft_and_discards_private_fields(self):
        workspace = "5b101265-838f-4ed0-a3ee-f57913dfcae7"
        offer_id = "f93fc60c-73bd-4832-8b7c-17c842004066"
        item = {"id": offer_id, "name": "CRM bank product", "offer_type": "Bank",
                "target_action": "Confirmed card", "is_active": True}
        payload = {"workspace_id": workspace, "offers": [item]}
        with patch.dict(os.environ, {"CRM_FEED_TOKEN": "x"*40, "CRM_WORKSPACE_ID": workspace}):
            self.assertEqual(self.submit(payload, "x"*40)[0], 200)
            self.assertEqual(self.submit({**payload, "offers": [{**item, "agency_profit": "999"}]}, "x"*40)[0], 400)
            self.assertEqual(self.submit({**payload, "workspace_id": "another"}, "x"*40)[0], 400)
            self.assertEqual(self.submit(payload, "x"*40)[0], 200)
        with app.db() as conn:
            row = conn.execute("SELECT status,rate,hold FROM offers WHERE id=?", ("crm-" + offer_id,)).fetchone()
        self.assertEqual(row, ("draft", 0, 0))
        self.assertEqual(app.approved_offers(), [])


if __name__ == "__main__":
    unittest.main()
