"""Preflight must be read-only, detect release blockers, and not invent approval."""
import unittest

from tools import stage13_preflight


class Stage13PreflightTests(unittest.TestCase):
    def test_local_technical_contracts(self):
        report = stage13_preflight.inspect()
        self.assertTrue(report["technical_pass"], report["technical_checks"])
        self.assertEqual(len(report["technical_checks"]), 10)
        self.assertTrue(all(report["technical_checks"].values()))

    def test_owner_confirmed_documents_do_not_override_external_release_checks(self):
        report = stage13_preflight.inspect()
        self.assertEqual(report["approved_legal_version"], "partners-legal-v2-2026-11")
        self.assertFalse(report["release_ready"])
        self.assertGreaterEqual(len(report["release_blockers"]), 3)


if __name__ == "__main__":
    unittest.main()
