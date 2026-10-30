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

    def test_polling_cursor_only_advances_after_success(self):
        update = {"update_id": 42, "message": self.message(text="/start")}
        with patch.object(bot, "handle", side_effect=RuntimeError("temporary")):
            with self.assertRaises(RuntimeError):
                bot.process_update(update, None)
        with app.db() as con:
            self.assertIsNone(con.execute(
                "SELECT name FROM sqlite_master WHERE name='bot_cursor'").fetchone())
        self.assertEqual(bot.process_update(update, None), 43)
        with app.db() as con:
            self.assertEqual(con.execute(
                "SELECT next_update_id FROM bot_cursor WHERE name='polling'").fetchone()[0], 43)
        before = len(self.sent)
        self.assertEqual(bot.process_update(update, 43), 43)
        self.assertEqual(len(self.sent), before)

    def test_failed_admin_alert_is_durable_and_retried(self):
        original = bot.send
        with patch.object(bot, "send", side_effect=TimeoutError("telegram unavailable")):
            bot.notify_admin(12345)
        with app.db() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM bot_outbox").fetchone()[0], 1)
        bot.flush_outbox()
        with app.db() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM bot_outbox").fetchone()[0], 0)
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 1)

    def test_contact_and_outbox_rollback_together_on_queue_failure(self):
        with patch.object(bot, "queue_admin_notification", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.contact()
        with app.db() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM partners WHERE telegram_id=12345").fetchone())
        self.contact()
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 1)

    def test_crash_after_registration_commit_retains_exactly_one_alert(self):
        with patch.object(bot, "flush_outbox", side_effect=RuntimeError("process interrupted")):
            with self.assertRaises(RuntimeError):
                self.contact()
        self.assertEqual(self.status(), "pending")
        with app.db() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM bot_outbox").fetchone()[0], 1)
        self.contact()
        bot.flush_outbox()
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 1)

    def test_retry_and_outbox_rollback_together_on_queue_failure(self):
        self.contact()
        with app.db() as con:
            con.execute("UPDATE partners SET status='rejected' WHERE telegram_id=12345")
        with patch.object(bot, "queue_admin_notification", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                bot.handle(self.message(text="/retry"))
        self.assertEqual(self.status(), "rejected")
        bot.handle(self.message(text="/retry"))
        self.assertEqual(self.status(), "pending")
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 2)

    def test_retry_crash_after_commit_is_idempotent(self):
        self.contact()
        with app.db() as con:
            con.execute("UPDATE partners SET status='rejected' WHERE telegram_id=12345")
        with patch.object(bot, "flush_outbox", side_effect=RuntimeError("process interrupted")):
            with self.assertRaises(RuntimeError):
                bot.handle(self.message(text="/retry"))
        bot.handle(self.message(text="/retry"))
        bot.flush_outbox()
        self.assertEqual(self.status(), "pending")
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 2)

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
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 2)
        self.assertIn("Повторная заявка", next(text for cid, text, *_ in reversed(self.sent) if cid == bot.ADMIN_ID))
        bot.handle(self.message(text="/retry"))
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 2)

    def test_retry_without_phone_requires_verified_contact_and_second_retry(self):
        with app.db() as con:
            con.execute("INSERT INTO partners(telegram_id,username,name,created_at,status) VALUES(?,?,?,?,?)",
                        (12345, "partner", "Партнёр", 123, "rejected"))
        bot.handle(self.message(text="/retry"))
        self.assertEqual(self.status(), "rejected")
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 0)
        self.contact()
        self.assertEqual(self.status(), "rejected")
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 0)
        bot.handle(self.message(text="/retry"))
        self.assertEqual(self.status(), "pending")
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 1)
        self.contact()
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 1)

    def test_duplicate_retry_is_idempotent(self):
        self.contact()
        with app.db() as con:
            con.execute("UPDATE partners SET status='rejected' WHERE telegram_id=12345")
        retry = self.message(text="/retry")
        bot.handle(retry)
        bot.handle(retry)
        self.assertEqual(self.status(), "pending")
        self.assertEqual(sum(cid == bot.ADMIN_ID for cid, *_ in self.sent), 2)

    def test_admin_notification_failure_does_not_undo_registration(self):
        original_send = bot.send
        def failing_admin_send(cid, text, markup=None):
            if cid == bot.ADMIN_ID:
                raise TimeoutError("offline")
            return original_send(cid, text, markup)
        with patch.object(bot, "send", side_effect=failing_admin_send):
            self.contact()
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

    def test_admin_start_shows_web_app_without_contact(self):
        admin_message = {"from": {"id": bot.ADMIN_ID},
                         "chat": {"id": bot.ADMIN_ID, "type": "private"}, "text": "/start"}
        with patch.object(bot, "APP_URL", "https://example.org/partners"):
            bot.handle(admin_message)
        self.assertIn("web_app", repr(self.sent[-1]))
        self.assertIsNone(app.partner_for(bot.ADMIN_ID))
        bot.handle({**admin_message, "contact": {"user_id": bot.ADMIN_ID, "phone_number": "+79991111111"}})
        self.assertIsNone(app.partner_for(bot.ADMIN_ID))

    def test_mismatched_private_chat_is_ignored(self):
        bot.handle({**self.message(text="/start"), "chat": {"id": 999, "type": "private"}})
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
