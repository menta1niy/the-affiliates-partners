"""Preflight must be read-only, detect release blockers, and not invent approval."""
import unittest

from tools import stage13_preflight


class Stage13PreflightTests(unittest.TestCase):
    def test_local_technical_contracts(self):
        report = stage13_preflight.inspect()
        self.assertTrue(report["technical_pass"], report["technical_checks"])
        self.assertEqual(len(report["technical_checks"]), 10)
        self.assertTrue(all(report["technical_checks"].values()))

    def test_unapproved_documents_block_release(self):
        report = stage13_preflight.inspect()
        self.assertIsNone(report["approved_legal_version"])
        self.assertFalse(report["release_ready"])
        self.assertGreaterEqual(len(report["release_blockers"]), 4)


if __name__ == "__main__":
    unittest.main()
