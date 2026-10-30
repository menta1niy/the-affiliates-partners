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
        self.legacy_patch = patch.dict(os.environ, {"CRM_ALLOW_LEGACY_FEED": "1"})
        self.legacy_patch.start()
        self.addCleanup(self.legacy_patch.stop)
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

    def test_real_crm_type_uses_partner_category(self):
        workspace = "5b101265-838f-4ed0-a3ee-f57913dfcae7"
        offer_id = "f93fc60c-73bd-4832-8b7c-17c842004066"
        with patch.dict(os.environ, {"CRM_FEED_TOKEN": "x"*40, "CRM_WORKSPACE_ID": workspace}):
            self.assertEqual(self.submit({"workspace_id": workspace, "offers": [
                {"id": offer_id, "name": "Карта", "offer_type": "debit",
                 "target_action": "Получение карты", "is_active": True}
            ]}, "x"*40)[0], 200)
        with app.db() as conn:
            category = conn.execute("SELECT type FROM offers WHERE id=?", ("crm-"+offer_id,)).fetchone()[0]
        self.assertIn("БАНКИ", category)

    def test_complete_snapshot_pauses_removed_offer_without_deleting_other_data(self):
        workspace = "5b101265-838f-4ed0-a3ee-f57913dfcae7"
        old_id = "f93fc60c-73bd-4832-8b7c-17c842004066"
        kept_id = "7fae3658-c79c-4475-a11e-cc63aca2fa32"
        def offer(uid):
            return {"id": uid, "name": "Active CRM offer", "offer_type": "debit",
                    "target_action": "Card received", "is_active": True}
        with patch.dict(os.environ, {"CRM_FEED_TOKEN": "x"*40, "CRM_WORKSPACE_ID": workspace}):
            self.assertEqual(self.submit({"workspace_id": workspace,
                "offers": [offer(old_id), offer(kept_id)]}, "x"*40)[0], 200)
            with app.db() as conn:
                conn.execute("UPDATE offers SET status='approved' WHERE id IN (?,?)",
                             ("crm-"+old_id, "crm-"+kept_id))
            self.assertEqual(self.submit({"mode": "finalize", "workspace_id": workspace,
                "offer_ids": [kept_id]}, "x"*40)[0], 200)
            # Replays must not silently re-approve a previously paused offer.
            self.assertEqual(self.submit({"workspace_id": workspace,
                "offers": [offer(old_id)]}, "x"*40)[0], 200)
            self.assertEqual(self.submit({"mode": "finalize", "workspace_id": "different",
                "offer_ids": []}, "x"*40)[0], 400)
        with app.db() as conn:
            statuses = dict(conn.execute("SELECT id,status FROM offers"))
        self.assertEqual(statuses["crm-"+old_id], "paused")
        self.assertEqual(statuses["crm-"+kept_id], "approved")

    def test_inactive_upstream_cannot_be_published_by_admin(self):
        from test_signed_auth import signed_data
        workspace = "5b101265-838f-4ed0-a3ee-f57913dfcae7"
        offer_id = "f93fc60c-73bd-4832-8b7c-17c842004066"
        body = {"workspace_id": workspace, "offers": [
            {"id": offer_id, "name": "Inactive", "offer_type": "debit",
             "target_action": "Card", "is_active": False}]}
        with patch.dict(os.environ, {"CRM_FEED_TOKEN": "x"*40, "CRM_WORKSPACE_ID": workspace}):
            self.assertEqual(self.submit(body, "x"*40)[0], 200)
        url = f"http://127.0.0.1:{self.server.server_port}/api/admin/offers/status"
        req = urllib.request.Request(url, json.dumps({
            "initData": signed_data(app.ADMIN_ID), "id": "crm-"+offer_id,
            "status": "approved"}).encode(), {"Content-Type": "application/json"})
        with patch.object(app, "TOKEN", "test-bot-token"):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(req, timeout=4)
        self.assertEqual(raised.exception.code, 409)

    def test_staged_http_snapshot_over_previous_limit(self):
        import hashlib
        from uuid import uuid4
        from crm_feed import normalize_feed
        workspace = "5b101265-838f-4ed0-a3ee-f57913dfcae7"
        items = [{"id": str(uuid4()), "name": f"Offer {i}", "offer_type": "debit",
                  "target_action": "Card", "is_active": True} for i in range(350)]
        run_id = str(uuid4())
        with patch.dict(os.environ, {"CRM_FEED_TOKEN": "x"*40, "CRM_WORKSPACE_ID": workspace}):
            self.assertEqual(self.submit({"mode":"begin","workspace_id":workspace,
                "run_id":run_id,"expected":350}, "x"*40)[0], 200)
            for start in range(0,350,50):
                status,_ = self.submit({"mode":"batch","workspace_id":workspace,
                    "run_id":run_id,"offers":items[start:start+50]}, "x"*40)
                self.assertEqual(status,200)
            prepared = normalize_feed({"workspace_id":workspace,"offers":items[:100]},workspace)
            for start in range(100,350,100):
                prepared += normalize_feed({"workspace_id":workspace,"offers":items[start:start+100]},workspace)
            digest = hashlib.sha256("\n".join(
                json.dumps(list(row),ensure_ascii=False) for row in sorted(prepared)).encode()).hexdigest()
            status, result = self.submit({"mode":"commit","workspace_id":workspace,
                "run_id":run_id,"digest":digest}, "x"*40)
            self.assertEqual(status,200)
            self.assertTrue(result["ok"])
        with app.db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM offers").fetchone()[0],350)

    def test_legacy_protocol_disabled_by_default(self):
        workspace = "5b101265-838f-4ed0-a3ee-f57913dfcae7"
        with patch.dict(os.environ, {"CRM_ALLOW_LEGACY_FEED": "0",
                                     "CRM_FEED_TOKEN": "x"*40, "CRM_WORKSPACE_ID": workspace}):
            status, _ = self.submit({"workspace_id":workspace,"offers":[]}, "x"*40)
            self.assertEqual(status,409)


if __name__ == "__main__":
    unittest.main()
