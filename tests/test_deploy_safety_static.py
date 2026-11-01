"""Prevent deployment probes from accidentally initializing live PostgreSQL."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DeploySafetyTests(unittest.TestCase):
    def test_preflight_overrides_private_database_config(self):
        script = (ROOT / "deployment/deploy.sh").read_text()
        self.assertIn('PARTNERS_DATABASE_URL= PARTNERS_REQUIRE_POSTGRES=false PARTNERS_PG_SCHEMA_READY=false', script)
        self.assertIn('PARTNERS_DB_PATH="$PREFLIGHT_DB/probe.sqlite3"', script)
        self.assertIn('PREFLIGHT_DB="$(mktemp -d)"', script)
        self.assertIn('rm -rf -- "$PREFLIGHT_DB"', script)

    def test_restore_proof_is_mandatory_and_disposable(self):
        deploy = (ROOT / "deployment/deploy.sh").read_text()
        proof = (ROOT / "deployment/verify-pg-backup.sh").read_text()
        self.assertIn('"verify-pg-backup.sh"', deploy)
        self.assertIn('pg_restore --exit-on-error', proof)
        self.assertIn('createdb -T template0', proof)
        self.assertIn('dropdb --if-exists', proof)
        self.assertIn('schemaname=\'partners\'', proof)
        self.assertNotIn('PARTNERS_DATABASE_URL', proof)
        self.assertIn('SELECT count(*) FROM partners.$table', proof)
        self.assertIn('source_database', proof)

    def test_empty_environment_overrides_local_config(self):
        from unittest.mock import patch
        from tempfile import TemporaryDirectory
        import os
        from server import settings, db
        with TemporaryDirectory() as folder:
            path = Path(folder) / '.env.local'
            path.write_text('PARTNERS_DATABASE_URL=postgresql://invalid/live\n')
            with patch.object(settings, 'ROOT', Path(folder)), patch.dict(os.environ, {
                'PARTNERS_DATABASE_URL': '', 'PARTNERS_REQUIRE_POSTGRES': 'false',
                'PARTNERS_PG_SCHEMA_READY': 'false', 'PARTNERS_DB_PATH': str(Path(folder) / 'probe.sqlite3'),
            }):
                settings.load_settings()
                self.assertEqual(db.postgres_url(), '')
                self.assertEqual(os.environ['PARTNERS_REQUIRE_POSTGRES'], 'false')
                self.assertEqual(os.environ['PARTNERS_PG_SCHEMA_READY'], 'false')


if __name__ == "__main__":
    unittest.main()
