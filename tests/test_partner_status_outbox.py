"""Admin status decisions persist notifications for the polling bot."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import app
import bot


class StatusOutboxTests(unittest.TestCase):
    def test_notification_is_saved_and_delivered_after_network_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(app, "DB", Path(tmp) / "partners.sqlite3"):
                with patch.object(bot, "send", side_effect=TimeoutError("offline")):
                    app.notify_partner_status(12345, "active")
                    bot.flush_outbox()
                with app.db() as conn:
                    self.assertEqual(conn.execute(
                        "SELECT count(*) FROM bot_outbox").fetchone()[0], 1)
                with patch.object(bot, "send") as delivered:
                    bot.flush_outbox()
                    delivered.assert_called_once()
                    self.assertEqual(delivered.call_args.args[0], 12345)
                with app.db() as conn:
                    self.assertEqual(conn.execute(
                        "SELECT count(*) FROM bot_outbox").fetchone()[0], 0)

    def test_status_notification_rolls_back_with_failed_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(app, "DB", Path(tmp) / "partners.sqlite3"):
                with self.assertRaises(RuntimeError):
                    with app.db() as conn:
                        app.queue_partner_status(conn, 12345, "active")
                        raise RuntimeError("db operation failed")
                with app.db() as conn:
                    if conn.execute("SELECT name FROM sqlite_master WHERE name='bot_outbox'").fetchone():
                        self.assertEqual(conn.execute(
                            "SELECT count(*) FROM bot_outbox").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
