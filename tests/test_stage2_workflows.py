"""End-to-end API workflows against an isolated SQLite DB, no Telegram requests."""
import json
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
from test_signed_auth import signed_data


class Stage2Workflows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = patch.object(app, "DB", Path(self.tmp.name) / "partners.sqlite3")
        self.database.start()
        self.addCleanup(self.database.stop)
        self.token = patch.object(app, "TOKEN", "test-bot-token")
        self.token.start()
        self.addCleanup(self.token.stop)
        self.notify = patch.object(app, "notify_partner_status")
        self.notify.start()
        self.addCleanup(self.notify.stop)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def post(self, route, uid, **values):
        payload = {"initData": signed_data(uid), **values}
        url = f"http://127.0.0.1:{self.http.server_port}{route}"
        req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as res:
                return res.status, json.load(res)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_first_login_relogin_and_phone_preservation(self):
        code, data = self.post("/api/auth/telegram", 28491)
        self.assertEqual(code, 200)
        self.assertEqual(data["profile"]["status"], "pending")
        with app.db() as conn:
            conn.execute("UPDATE partners SET phone=? WHERE telegram_id=?", ("+79990000000", 28491))
        for _ in range(2):
            code, data = self.post("/api/auth/telegram", 28491)
            self.assertEqual(code, 200)
            self.assertEqual(data["profile"]["phone"], "+79990000000")
        with app.db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM partners WHERE telegram_id=?", (28491,)).fetchone()[0], 1)

    def test_owner_approves_registration_and_offer_without_privilege_escalation(self):
        partner = 28491
        self.post("/api/auth/telegram", partner)
        with app.db() as conn:
            conn.execute("UPDATE partners SET phone=? WHERE telegram_id=?", ("+79990000000", partner))
        route = "/api/admin/partners/status"
        self.assertEqual(self.post(route, partner, telegram_id=partner, status="active")[0], 403)
        self.assertEqual(self.post(route, app.ADMIN_ID, telegram_id=partner, status="active")[0], 200)
        self.assertEqual(self.post("/api/auth/telegram", partner)[1]["profile"]["status"], "active")
        self.assertEqual(self.post(route, app.ADMIN_ID, telegram_id=app.ADMIN_ID, status="rejected")[0], 400)

        offer = {"id": "test-offer", "name": "Offer", "type": "Bank", "rate": 1000,
                 "goal": "Confirmed", "hold": 7, "description": "Test only", "status": "draft"}
        self.assertEqual(self.post("/api/admin/offers/save", partner, offer=offer)[0], 403)
        self.assertEqual(self.post("/api/admin/offers/save", app.ADMIN_ID, offer=offer)[0], 200)
        self.assertEqual(self.post("/api/offers", partner)[1]["offers"], [])
        self.assertEqual(self.post("/api/admin/offers/status", app.ADMIN_ID, id="test-offer", status="approved")[0], 200)
        self.assertEqual([x["id"] for x in self.post("/api/offers", partner)[1]["offers"]], ["test-offer"])
        self.assertEqual(self.post("/api/admin/offers/status", app.ADMIN_ID, id="test-offer", status="paused")[0], 200)
        self.assertEqual(self.post("/api/offers", partner)[1]["offers"], [])

    def test_approval_requires_verified_contact(self):
        uid = 28491
        self.post("/api/auth/telegram", uid)
        code, body = self.post("/api/admin/partners/status", app.ADMIN_ID, telegram_id=uid, status="active")
        self.assertEqual(code, 400)
        self.assertEqual(self.post("/api/auth/telegram", uid)[1]["profile"]["status"], "pending")

    def test_partner_isolation_and_closed_financial_fields(self):
        first, second = 28491, 28492
        for uid in (first, second):
            self.post("/api/auth/telegram", uid)
        with app.db() as conn:
            conn.execute("UPDATE partners SET phone='+79990000001',status='active' WHERE telegram_id=?", (first,))
            conn.execute("UPDATE partners SET phone='+79990000002',status='pending' WHERE telegram_id=?", (second,))
        self.assertEqual(self.post("/api/admin/snapshot", first)[0], 403)
        self.assertEqual(self.post("/api/offers", second)[0], 403)
        status, identity = self.post("/api/auth/telegram", first)
        self.assertEqual(status, 200)
        self.assertEqual(identity["profile"]["telegram_id"], first)
        self.assertNotIn(str(second), json.dumps(identity))
        self.assertFalse(identity["isAdmin"])
        status, offers = self.post("/api/offers", first)
        self.assertEqual(status, 200)
        self.assertEqual(offers, {"offers": []})
        for private_field in ("agency_rate", "agency_profit", "blogger_accrual"):
            self.assertNotIn(private_field, json.dumps(identity) + json.dumps(offers))

    def test_rejected_access_and_repeated_approval_are_durable(self):
        partner = 28491
        self.post("/api/auth/telegram", partner)
        with app.db() as conn:
            conn.execute("UPDATE partners SET phone='+79990000001' WHERE telegram_id=?", (partner,))
        endpoint = "/api/admin/partners/status"
        self.assertEqual(self.post(endpoint, app.ADMIN_ID, telegram_id=partner, status="rejected")[0], 200)
        self.assertEqual(self.post("/api/offers", partner)[0], 403)
        for _ in range(2):
            self.assertEqual(self.post(endpoint, app.ADMIN_ID, telegram_id=partner, status="active")[0], 200)
        self.assertEqual(self.post("/api/auth/telegram", partner)[1]["profile"]["status"], "active")
        self.assertEqual(self.post("/api/offers", partner)[0], 200)


if __name__ == "__main__":
    unittest.main()
