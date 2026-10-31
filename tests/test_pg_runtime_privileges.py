"""Opt-in test against a disposable local PG cluster with role-management rights."""
import os
import unittest
import uuid
from unittest.mock import patch


class RuntimePrivilegeTests(unittest.TestCase):
    def test_runtime_role_dml_only_and_missing_schema_fails(self):
        url = os.getenv("PARTNERS_TEST_PG_URL")
        if not url:
            self.skipTest("PARTNERS_TEST_PG_URL required")
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from server import db

        role = "partners_runtime_test_" + uuid.uuid4().hex[:10]
        with psycopg.connect(url, autocommit=True) as admin:
            if not admin.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0]:
                self.skipTest("disposable cluster superuser required")
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
            try:
                admin.execute(sql.SQL("GRANT USAGE ON SCHEMA partners TO {}").format(sql.Identifier(role)))
                admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA partners TO {}").format(sql.Identifier(role)))
                admin.execute(sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA partners TO {}").format(sql.Identifier(role)))
                runtime_url = make_conninfo(url, user=role)
                with patch.dict(os.environ, {"PARTNERS_DATABASE_URL": runtime_url, "PARTNERS_PG_SCHEMA_READY": "true"}):
                    db._PG_INITIALIZED_URL = None
                    db.initialize()
                    db.initialize()
                with psycopg.connect(runtime_url) as limited:
                    self.assertFalse(limited.execute("SELECT has_schema_privilege(current_user,'partners','CREATE')").fetchone()[0])
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        limited.execute("CREATE TABLE partners.unwanted_runtime_ddl (id integer)")
                with patch.dict(os.environ, {"PARTNERS_DATABASE_URL": runtime_url, "PARTNERS_PG_SCHEMA_READY": "true"}):
                    from unittest.mock import patch as mock_patch
                    with mock_patch("database.postgres.initialize", side_effect=AssertionError("DDL invoked")):
                        db._PG_INITIALIZED_URL = None
                        db.initialize()
            finally:
                db._PG_INITIALIZED_URL = None
                admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))

    def test_unprepared_schema_refused(self):
        url = os.getenv("PARTNERS_TEST_PG_URL")
        if not url:
            self.skipTest("PARTNERS_TEST_PG_URL required")
        from database.postgres import validate_ready
        import psycopg
        from psycopg.conninfo import make_conninfo
        # The cluster's admin database has no prepared Partners schema.
        with self.assertRaises((RuntimeError, psycopg.Error)):
            validate_ready(make_conninfo(url, dbname="postgres"))

    def test_invalid_schema_mode_refuses_ddl(self):
        from server import db
        with patch.dict(os.environ, {"PARTNERS_DATABASE_URL": "postgresql://invalid/none",
                                      "PARTNERS_PG_SCHEMA_READY": "tru"}):
            with self.assertRaisesRegex(RuntimeError, "must be true or false"):
                db.initialize()
