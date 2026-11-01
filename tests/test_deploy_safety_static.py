"""Prevent deployment probes from accidentally initializing live PostgreSQL."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DeploySafetyTests(unittest.TestCase):
    def test_preflight_overrides_private_database_config(self):
        script = (ROOT / "deployment/deploy.sh").read_text()
        self.assertIn('PARTNERS_DATABASE_URL= PARTNERS_DB_PATH="$PREFLIGHT_DB/probe.sqlite3"', script)
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


if __name__ == "__main__":
    unittest.main()
