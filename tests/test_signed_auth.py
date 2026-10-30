"""Signed Telegram identity and authorization tests using an isolated database."""
import hashlib
import hmac
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import app


def signed_data(uid, token="test-bot-token", **extra):
    params = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid, "first_name": "Test"}), **extra}
    payload = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


class SignedAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(app, "DB", Path(self.tmp.name) / "test.sqlite3")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.token_patch = patch.object(app, "TOKEN", "test-bot-token")
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)

    def test_signed_user_identity_and_tampering(self):
        data = signed_data(app.ADMIN_ID)
        self.assertEqual(app.verify_init_data(data)["id"], app.ADMIN_ID)
        self.assertIsNone(app.verify_init_data(data.replace(str(app.ADMIN_ID), "123456")))
        self.assertIsNone(app.verify_init_data(data + "&user=another"))
        self.assertIsNone(app.verify_init_data(signed_data(True)))
        self.assertIsNone(app.verify_init_data(signed_data(0)))
        self.assertIsNone(app.verify_init_data(signed_data(app.ADMIN_ID, auth_date=str(int(time.time()) + 120))))

    def test_admin_endpoint_requires_signed_admin_identity(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/api/admin/snapshot"

        def post(data):
            request = urllib.request.Request(url, json.dumps({"initData": data}).encode(),
                                             {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                return error.code, json.load(error)

        self.assertEqual(post("")[0], 401)
        self.assertEqual(post(signed_data(12345))[0], 403)
        status, payload = post(signed_data(app.ADMIN_ID))
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"partners": [], "offers": []})

    def test_admin_auth_does_not_register_or_overwrite_owner_record(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with app.db() as conn:
            conn.execute("INSERT INTO partners VALUES(?,?,?,?,?,?)",
                         (app.ADMIN_ID, "owner", "Owner", "+79991111111", "active", 1))
        url = f"http://127.0.0.1:{server.server_port}/api/auth/telegram"
        request = urllib.request.Request(url, json.dumps({"initData": signed_data(app.ADMIN_ID)}).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.load(response)
        self.assertTrue(result["isAdmin"])
        self.assertEqual(app.partner_for(app.ADMIN_ID), {
            "telegram_id": app.ADMIN_ID, "username": "owner", "name": "Owner",
            "phone": "+79991111111", "status": "active"})

    def test_owner_without_database_row_still_receives_verified_profile(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/api/auth/telegram"
        request = urllib.request.Request(url, json.dumps({"initData": signed_data(app.ADMIN_ID)}).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.load(response)
        self.assertTrue(result["isAdmin"])
        self.assertEqual(result["profile"]["telegram_id"], app.ADMIN_ID)
        self.assertEqual(result["profile"]["status"], "active")
        self.assertIsNone(app.partner_for(app.ADMIN_ID))

    def test_notification_failure_never_raises(self):
        with patch("app.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            app.notify_partner_status(12345, "active")


if __name__ == "__main__":
    unittest.main()
