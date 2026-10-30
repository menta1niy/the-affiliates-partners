"""Registration and /start regression checks (no Telegram network requests)."""
import sys
import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import app
import bot


class BotRegistrationTests(unittest.TestCase):
    def tearDown(self):
        # sqlite3 connection context managers commit but do not close handles.
        gc.collect()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(app, "DB", Path(self.tmp.name) / "partners.sqlite3")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        app.db().close()
        self.sent = []
        self.send_patch = patch.object(bot, "send", side_effect=lambda *args: self.sent.append(args))
        self.send_patch.start()
        self.addCleanup(self.send_patch.stop)

    def message(self, **extra):
        return {"from": {"id": 12345, "username": "partner", "first_name": "Партнёр"},
                "chat": {"id": 12345, "type": "private"}, **extra}

    def contact(self):
        bot.handle(self.message(contact={"user_id": 12345, "phone_number": "+79990000000"}))

    def status(self):
        with app.db() as con:
            return con.execute("SELECT status FROM partners WHERE telegram_id=12345").fetchone()[0]

    def test_first_contact_notifies_admin_once(self):
        bot.handle(self.message(text="/start"))
        self.assertIn("request_contact", repr(self.sent[-1]))
        self.contact()
        self.assertEqual(self.status(), "pending")
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 1)
        self.contact()
        bot.handle(self.message(text="/start"))
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 1)
        self.assertIn("рассмотрении", self.sent[-1][1])

    def test_active_user_remains_active_and_gets_web_app(self):
        self.contact()
        with app.db() as con:
            con.execute("UPDATE partners SET status='active' WHERE telegram_id=12345")
        with patch.object(bot, "APP_URL", "https://example.org/partners"):
            self.contact()
            bot.handle(self.message(text="/start"))
        self.assertEqual(self.status(), "active")
        self.assertIn("web_app", repr(self.sent[-1]))

    def test_rejected_user_stays_rejected_until_explicit_retry(self):
        self.contact()
        with app.db() as con:
            con.execute("UPDATE partners SET status='rejected' WHERE telegram_id=12345")
        self.contact()
        bot.handle(self.message(text="/start"))
        self.assertEqual(self.status(), "rejected")
        self.assertIn("/retry", self.sent[-1][1])
        bot.handle(self.message(text="/retry"))
        self.assertEqual(self.status(), "pending")

    def test_forwarded_contact_is_rejected(self):
        bot.handle(self.message(contact={"user_id": 9999, "phone_number": "+79990000000"}))
        with app.db() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM partners WHERE telegram_id=12345").fetchone())
        self.assertIn("собственный контакт", self.sent[-1][1])

    def test_contact_binds_canonical_phone_and_username(self):
        bot.handle(self.message(contact={"user_id": 12345, "phone_number": "8 (999) 000-00-00"}))
        with app.db() as con:
            profile = con.execute(
                "SELECT telegram_id,username,phone,status FROM partners WHERE telegram_id=12345"
            ).fetchone()
        self.assertEqual(profile, (12345, "partner", "+79990000000", "pending"))
        self.assertIn("привязан", self.sent[-2][1])

    def test_phone_cannot_be_shared_between_accounts(self):
        self.contact()
        other = {"from": {"id": 54321, "username": "other", "first_name": "Другой"},
                 "chat": {"id": 54321, "type": "private"},
                 "contact": {"user_id": 54321, "phone_number": "79990000000"}}
        bot.handle(other)
        with app.db() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM partners WHERE telegram_id=54321").fetchone())
        self.assertIn("уже привязан", self.sent[-1][1])


if __name__ == "__main__":
    unittest.main()
