"""Durable Telegram outbox dispatch tests; no external network access."""
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from server import db
from tools import dispatch_notifications as dispatcher


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="partners-dispatch-")
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "outbox.sqlite3")
        env = patch.dict(os.environ, {"PARTNERS_DB_PATH": self.path})
        env.start()
        self.addCleanup(env.stop)
        db.initialize()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("INSERT INTO notifications_outbox(event_key,chat_id,text,created_at) VALUES(?,?,?,?)", ("test:1", 42, "Message", 1000))
            conn.commit()

    def row(self):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute("SELECT attempts,sent_at,next_attempt_at,last_error FROM notifications_outbox WHERE event_key='test:1'").fetchone()

    def test_success_is_marked_sent_and_never_sent_twice(self):
        with patch.object(dispatcher, "bot_token", return_value="synthetic"), patch.object(dispatcher, "deliver", return_value=True) as deliver, patch.object(dispatcher.time, "time", return_value=10000):
            self.assertEqual(dispatcher.dispatch(), 0)
            self.assertEqual(dispatcher.dispatch(), 0)
        deliver.assert_called_once_with(42, "Message", "synthetic")
        attempts, sent, retry, error = self.row()
        self.assertEqual(attempts, 1)
        self.assertEqual(sent, 10000)
        self.assertEqual(error, "")

    def test_failed_delivery_backs_off_and_retries_when_due(self):
        with patch.object(dispatcher, "bot_token", return_value="synthetic"), patch.object(dispatcher, "deliver", side_effect=[RuntimeError("unavailable"), True]) as deliver:
            with patch.object(dispatcher.time, "time", return_value=10000):
                self.assertEqual(dispatcher.dispatch(), 0)
                self.assertEqual(dispatcher.dispatch(), 0)
            attempts, sent, retry, error = self.row()
            self.assertEqual((attempts, sent, retry, error), (1, None, 10060, "RuntimeError"))
            self.assertEqual(deliver.call_count, 1)
            with patch.object(dispatcher.time, "time", return_value=10060):
                self.assertEqual(dispatcher.dispatch(), 0)
        self.assertEqual(deliver.call_count, 2)
        attempts, sent, retry, error = self.row()
        self.assertEqual(attempts, 2)
        self.assertEqual(sent, 10060)
        self.assertEqual(error, "")

    def test_failure_from_false_delivery_is_retryable(self):
        with patch.object(dispatcher, "bot_token", return_value="synthetic"), patch.object(dispatcher, "deliver", return_value=False), patch.object(dispatcher.time, "time", return_value=20000):
            self.assertEqual(dispatcher.dispatch(), 0)
        self.assertEqual(self.row(), (1, None, 20060, "RuntimeError"))


if __name__ == "__main__":
    unittest.main()
