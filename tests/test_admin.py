"""Isolated database tests; never read or modify production partner data."""
import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
app = importlib.import_module("app")


class AdminDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dbfile = Path(self.tmp.name) / "test.sqlite3"
        self.db_patch = patch.object(app, "DB", self.dbfile)
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_empty_snapshot_and_only_approved_offers_visible(self):
        snapshot = app.admin_snapshot()
        self.assertEqual(snapshot["partners"], [])
        self.assertEqual(snapshot["offers"], [])
        self.assertEqual(snapshot["operations"]["notificationsQueued"], 0)
        with app.db() as conn:
            conn.execute("INSERT INTO offers VALUES(?,?,?,?,?,?,?,?,?)",
                         ("offer-1", "Test", "МФО", 1000, "Цель", 7, "Описание", "draft", 1))
            conn.execute("INSERT INTO offers VALUES(?,?,?,?,?,?,?,?,?)",
                         ("offer-2", "Approved", "МФО", 2000, "Цель", 3, "Описание", "approved", 1))
        self.assertEqual(len(app.admin_snapshot()["offers"]), 2)
        self.assertEqual([x["id"] for x in app.approved_offers()], ["offer-2"])

    def test_partner_status_kept_in_database(self):
        with app.db() as conn:
            conn.execute("INSERT INTO partners VALUES(?,?,?,?,?,?)",
                         (123456, "example", "Partner", "+1000000", "pending", 100))
            conn.execute("UPDATE partners SET status='active' WHERE telegram_id=?", (123456,))
        self.assertEqual(app.partner_for(123456)["status"], "active")


if __name__ == "__main__":
    unittest.main()
