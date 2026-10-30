"""Exercise additive migrations against disposable historical SQLite schemas."""
import importlib
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
app = importlib.import_module("app")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "historical.sqlite3"
        self.override = patch.object(app, "DB", self.db_path)
        self.override.start()

    def tearDown(self):
        self.override.stop()
        self.tmp.cleanup()

    def test_legacy_rows_are_preserved_and_new_columns_are_usable(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TABLE partners (telegram_id INTEGER PRIMARY KEY, username TEXT)")
            conn.executemany("INSERT INTO partners VALUES (?, ?)", [(11, "older"), (22, "second")])
            conn.execute("CREATE TABLE offers (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO offers VALUES ('old-offer', 'Original')")
            conn.commit()

        for _ in range(3):  # Repeated calls and process-like reconnects are idempotent.
            with app.db() as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(partners)")}
                self.assertEqual(columns, {"telegram_id", "username", "name", "phone", "status", "created_at"})
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM partners").fetchone()[0], 2)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='idx_partners_phone'").fetchone()[0], 1)

        self.assertEqual(app.partner_for(11), {
            "telegram_id": 11, "username": "older", "name": "", "phone": "", "status": "pending"})
        snapshot = app.admin_snapshot()
        self.assertEqual(snapshot["offers"][0]["name"], "Original")
        self.assertEqual(snapshot["offers"][0]["updated_at"], 0)
        with app.db() as conn:
            conn.execute("UPDATE partners SET phone=?,status=? WHERE telegram_id=11", ("+79990000000", "active"))
            conn.execute("UPDATE offers SET status='approved' WHERE id='old-offer'")
        self.assertEqual(app.approved_offers()[0]["id"], "old-offer")
        self.assertEqual(app.partner_for(11)["phone"], "+79990000000")

    def test_partial_schema_preserves_populated_columns_and_duplicate_phones(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TABLE partners (telegram_id INTEGER PRIMARY KEY, phone TEXT, status TEXT)")
            conn.executemany("INSERT INTO partners VALUES (?, ?, ?)", [
                (100, "+79991112233", "active"), (101, "+79991112233", "rejected")])
            conn.execute("CREATE TABLE offers (id TEXT PRIMARY KEY, rate INTEGER, status TEXT)")
            conn.execute("INSERT INTO offers VALUES ('legacy', 1234, 'approved')")
            conn.commit()
        with app.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM partners WHERE phone='+79991112233'").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT rate,status FROM offers WHERE id='legacy'").fetchone(), (1234, "approved"))
        self.assertEqual(app.partner_for(100)["status"], "active")
        self.assertEqual(app.approved_offers()[0]["rate"], 1234)


if __name__ == "__main__":
    unittest.main()
