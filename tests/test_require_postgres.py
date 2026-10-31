"""Post-cutover guard: no accidental SQLite access or creation."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import db


class RequirePostgresTests(unittest.TestCase):
    def test_configuration_matrix_and_no_sqlite_writes_on_missing_url(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "must-not-exist.sqlite3"
            for require in ("", "false", "true", "TRUE", "junk"):
                for ready in ("", "false", "true", "TRUE", "junk"):
                    with self.subTest(require=require, ready=ready):
                        env = {"PARTNERS_DATABASE_URL": "   ",
                               "PARTNERS_REQUIRE_POSTGRES": require,
                               "PARTNERS_PG_SCHEMA_READY": ready,
                               "PARTNERS_DB_PATH": str(path)}
                        with patch.dict(os.environ, env):
                            should_fail = require.lower() not in ("", "false") or ready.lower() not in ("", "false")
                            if should_fail:
                                with self.assertRaises(RuntimeError):
                                    db.postgres_url()
                                with self.assertRaises(RuntimeError):
                                    db.initialize()
                                with self.assertRaises(RuntimeError):
                                    with db.transaction():
                                        pass
                                self.assertFalse(path.exists())
                            else:
                                self.assertEqual(db.postgres_url(), "")

    def test_url_is_retained_without_opening_connection(self):
        for require in ("", "false", "TRUE"):
            for ready in ("", "false", "true"):
                with self.subTest(require=require, ready=ready):
                    with patch.dict(os.environ, {"PARTNERS_DATABASE_URL": " postgresql://synthetic.invalid/db ",
                                              "PARTNERS_REQUIRE_POSTGRES": require,
                                              "PARTNERS_PG_SCHEMA_READY": ready}):
                        self.assertEqual(db.postgres_url(), "postgresql://synthetic.invalid/db")

    def test_legacy_sqlite_fallback_remains_opt_in_free(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite3"
            with patch.dict(os.environ, {"PARTNERS_DATABASE_URL": "", "PARTNERS_DB_PATH": str(path),
                                      "PARTNERS_REQUIRE_POSTGRES": "", "PARTNERS_PG_SCHEMA_READY": ""}):
                db.initialize()
                self.assertTrue(path.is_file())
                with db.transaction() as conn:
                    self.assertIsNotNone(conn.execute("SELECT 1").fetchone())


if __name__ == "__main__":
    unittest.main()
