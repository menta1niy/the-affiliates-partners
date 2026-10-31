"""Opt-in destructive-to-disposable-only PostgreSQL backup and access checks.

Supply PARTNERS_TEST_PG_URL for a synthetic, dedicated database. The test
creates temporary roles and a second database; never point it at production.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid


class PostgreSQLOperationalAcceptance(unittest.TestCase):
    def test_schema_backup_restore_and_least_privilege(self):
        url = os.environ.get("PARTNERS_TEST_PG_URL")
        if not url:
            self.skipTest("PARTNERS_TEST_PG_URL required")
        import psycopg
        from psycopg import sql

        pg_dump = os.environ.get("PG_DUMP_BIN") or shutil.which("pg_dump")
        pg_restore = os.environ.get("PG_RESTORE_BIN") or shutil.which("pg_restore")
        if not pg_dump or not pg_restore:
            self.skipTest("pg_dump and pg_restore required")
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        parsed = conninfo_to_dict(url)
        dbname = parsed.get("dbname")
        if not dbname or "test" not in dbname.lower() and "accept" not in dbname.lower():
            self.fail("Database name must explicitly indicate a disposable test database")
        suffix = uuid.uuid4().hex[:10]
        restored_name = "partners_restore_test_" + suffix
        role_name = "partners_access_test_" + suffix
        admin_url = make_conninfo(url, dbname="postgres")
        restore_url = make_conninfo(url, dbname=restored_name)
        with psycopg.connect(admin_url, autocommit=True) as admin:
            if not admin.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0]:
                self.skipTest("isolated cluster superuser required to create disposable role")
            try:
                admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(restored_name)))
                admin.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role_name)))
                with psycopg.connect(url, autocommit=True) as source:
                    self.assertEqual(source.execute("SHOW server_encoding").fetchone()[0], "UTF8")
                    source.execute("CREATE TABLE IF NOT EXISTS public.crm_privilege_probe (id integer)")
                    source.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
                    source.execute("REVOKE ALL ON SCHEMA partners FROM PUBLIC")
                    source.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(dbname), sql.Identifier(role_name)))
                    source.execute(sql.SQL("GRANT USAGE ON SCHEMA partners TO {}").format(sql.Identifier(role_name)))
                    source.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA partners TO {}").format(sql.Identifier(role_name)))
                    source.execute(sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA partners TO {}").format(sql.Identifier(role_name)))
                    with psycopg.connect(make_conninfo(url, user=role_name, options="-csearch_path=partners")) as limited:
                        self.assertGreaterEqual(limited.execute("SELECT count(*) FROM users").fetchone()[0], 1)
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            limited.execute("SELECT * FROM public.crm_privilege_probe")
                        limited.rollback()
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            limited.execute("CREATE TABLE partners.forbidden_ddl (id int)")
                        limited.rollback()
                with tempfile.TemporaryDirectory() as folder:
                    archive = os.path.join(folder, "synthetic-partners.dump")
                    subprocess.run([pg_dump, "--format=custom", "--schema=partners", "--no-owner", "--no-acl", "--file", archive, url], check=True, capture_output=True)
                    subprocess.run([pg_restore, "--list", archive], check=True, capture_output=True)
                    subprocess.run([pg_restore, "--exit-on-error", "--no-owner", "--no-acl", "--dbname", restore_url, archive], check=True, capture_output=True)
                with psycopg.connect(url) as original, psycopg.connect(restore_url) as restored:
                    tables = [r[0] for r in original.execute("SELECT tablename FROM pg_tables WHERE schemaname='partners'")]
                    self.assertGreaterEqual(len(tables), 10)
                    for table in tables:
                        statement = sql.SQL("SELECT count(*) FROM partners.{}").format(sql.Identifier(table))
                        self.assertEqual(original.execute(statement).fetchone()[0], restored.execute(statement).fetchone()[0], table)
                    self.assertEqual(restored.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename='crm_privilege_probe'").fetchone()[0], 0)
            finally:
                with psycopg.connect(url, autocommit=True) as source:
                    source.execute("DROP TABLE IF EXISTS public.crm_privilege_probe")
                    source.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(restored_name)))
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name)))


if __name__ == "__main__":
    unittest.main()
