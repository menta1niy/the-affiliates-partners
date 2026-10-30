"""Real local bot handler -> same SQLite -> signed HTTP API -> partner offers."""
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
import bot
from test_signed_auth import signed_data


class BotAPIJourney(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for target, value in ((app, {"DB": Path(self.temp.name) / "partners.sqlite3",
                                    "TOKEN": "test-bot-token"}),):
            self.app_patch = patch.multiple(target, **value)
            self.app_patch.start()
            self.addCleanup(self.app_patch.stop)
        self.bot_send = patch.object(bot, "send")
        self.bot_send.start()
        self.addCleanup(self.bot_send.stop)
        self.status_notify = patch.object(app, "notify_partner_status")
        self.status_notify.start()
        self.addCleanup(self.status_notify.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, uid, extra=None):
        data = {"initData": signed_data(uid), **(extra or {})}
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/api/{path}",
            json.dumps(data).encode(),
            headers={"Content-Type":"application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                return response.status,json.load(response)
        except urllib.error.HTTPError as error:
            return error.code,json.load(error)

    def bot_message(self, **content):
        return {"from":{"id":12345,"first_name":"Test","username":"normal"},
                "chat":{"id":12345,"type":"private"},**content}

    def test_contact_approval_offer_and_repeat_login(self):
        bot.handle(self.bot_message(text="/start"))
        # Signed Mini App login alone cannot prove a user's phone number.
        status, profile = self.post("me",12345)
        self.assertEqual(status,200)
        self.assertEqual(profile["profile"]["phone"],"")
        self.assertEqual(self.post("offers",12345)[0],403)
        bot.handle(self.bot_message(contact={"user_id":44444,"phone_number":"+79991110000"}))
        self.assertEqual(self.post("me",12345)[1]["profile"]["phone"],"")
        bot.handle(self.bot_message(contact={"user_id":12345,"phone_number":"+79991110000"}))
        status, profile = self.post("me",12345)
        self.assertEqual(profile["profile"]["phone"],"+79991110000")
        self.assertEqual(profile["profile"]["status"],"pending")
        self.assertEqual(self.post("admin/partners/status",12345,
            {"telegram_id":12345,"status":"active"})[0],403)
        self.assertEqual(self.post("admin/partners/status",app.ADMIN_ID,
            {"telegram_id":12345,"status":"active"})[0],200)
        self.assertEqual(self.post("me",app.ADMIN_ID)[1]["isAdmin"],True)
        offer = {"id":"local-bank", "name":"Bank","type":"БАНКИ",
                 "rate":100,"goal":"Card confirmed","hold":7,
                 "description":"Verified local test offer","status":"draft"}
        self.assertEqual(self.post("admin/offers/save",app.ADMIN_ID,{"offer":offer})[0],200)
        self.assertEqual(self.post("admin/offers/status",app.ADMIN_ID,
            {"id":"local-bank","status":"approved"})[0],200)
        self.assertEqual([o["id"] for o in self.post("offers",12345)[1]["offers"]],
                         ["local-bank"])
        bot.handle(self.bot_message(text="/start"))
        bot.handle(self.bot_message(text="/start"))
        self.assertEqual(self.post("me",12345)[1]["profile"]["phone"],"+79991110000")
        with app.db() as conn:
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM partners WHERE telegram_id=12345").fetchone()[0],1)


if __name__ == "__main__":
    unittest.main()
