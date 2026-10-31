"""Tests require no real Telegram token, user accounts or database."""
import hashlib
import hmac
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from server.auth import verify_init_data
from server.api import Handler
from server import bot

TOKEN = "test-token-for-hmac"
OWNER = 1234567


def signed(user=None, now=None):
    now = int(now if now is not None else time.time())
    user = user or {"id": OWNER, "first_name": "Тест", "username": "test"}
    payload = {"auth_date": str(now), "user": json.dumps(user, ensure_ascii=False, separators=(",", ":"))}
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    payload["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


class TelegramAuthTests(unittest.TestCase):
    def test_accepts_signed_identity(self):
        self.assertEqual(verify_init_data(signed(), TOKEN)["id"], OWNER)

    def test_rejects_tampered_and_unsigned_identity(self):
        payload = signed()
        self.assertIsNone(verify_init_data(payload.replace("test", "admin"), TOKEN))
        self.assertIsNone(verify_init_data(payload, "other-token"))

    def test_rejects_stale_future_and_duplicate_keys(self):
        now = int(time.time())
        self.assertIsNone(verify_init_data(signed(now=now - 90000), TOKEN, now))
        self.assertIsNone(verify_init_data(signed(now=now + 100), TOKEN, now))
        self.assertIsNone(verify_init_data(signed() + "&auth_date=1", TOKEN))

    def test_rejects_malformed_user(self):
        self.assertIsNone(verify_init_data(signed(user={"id": True}), TOKEN))


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, path, payload, headers=None):
        req = Request(self.base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as err:
            return err.code, json.load(err)

    def test_health_and_session(self):
        with urlopen(self.base + "/api/health") as response:
            self.assertEqual(json.load(response)["service"], "the-affiliates-partners-v2")
        with patch("server.api.bot_token", return_value=TOKEN), patch("server.api.admin_id", return_value=OWNER):
            status, body = self.call("/api/session", {"initData": signed()})
            self.assertEqual((status, body["role"]), (200, "owner"))
            self.assertEqual(body["user"]["id"], OWNER)

    def test_rejects_bad_signature(self):
        with patch("server.api.bot_token", return_value=TOKEN):
            self.assertEqual(self.call("/api/session", {"initData": "not-signed"})[0], 401)

    def test_webhook_requires_secret(self):
        update = {"update_id": 10, "message": {"from": {"id": 42}, "chat": {"id": 42, "type": "private"}, "text": "/start"}}
        with patch("server.api.webhook_secret", return_value="secret-header"), patch.object(bot, "app_url", return_value="https://example.org/partners/"):
            self.assertEqual(self.call("/api/telegram/webhook", update)[0], 403)
            status, body = self.call("/api/telegram/webhook", update, {"X-Telegram-Bot-Api-Secret-Token": "secret-header"})
            self.assertEqual(status, 200)
            self.assertEqual(body["method"], "sendMessage")
            self.assertEqual(body["chat_id"], 42)
            self.assertIn("web_app", body["reply_markup"]["inline_keyboard"][0][0])


class BotTests(unittest.TestCase):
    def test_private_start_sends_app_button(self):
        with patch.object(bot, "app_url", return_value="https://example.org/partners/"):
            response = bot.response_for({"message": {"from": {"id": 42}, "chat": {"id": 42, "type": "private"}, "text": "/start"}})
        self.assertEqual(response["method"], "sendMessage")
        self.assertEqual(response["chat_id"], 42)
        self.assertIn("web_app", response["reply_markup"]["inline_keyboard"][0][0])

    def test_ignore_group_messages(self):
        response = bot.response_for({"message": {"from": {"id": 42}, "chat": {"id": -4, "type": "group"}, "text": "/start"}})
        self.assertIsNone(response)


if __name__ == "__main__":
    unittest.main()
