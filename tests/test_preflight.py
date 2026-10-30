"""Read-only startup diagnostics never mutate an existing Partners DB."""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import preflight


class PreflightTests(unittest.TestCase):
    def test_existing_database_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            db_file = Path(temp) / "partners.sqlite3"
            with closing(sqlite3.connect(db_file)) as connection:
                connection.execute("CREATE TABLE partners (telegram_id INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO partners VALUES(123)")
                connection.commit()
            before = db_file.read_bytes()
            with patch.dict("os.environ", {"PARTNERS_DB_PATH": str(db_file)}):
                result = preflight.check()
            self.assertEqual(result["sqlite_integrity"], "ok")
            self.assertTrue(result["partners_table"])
            self.assertEqual(db_file.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
