"""Final acceptance must never imply production approval from local checks."""
import unittest
from unittest.mock import patch

from tools import stage14_acceptance


class Stage14AcceptanceTests(unittest.TestCase):
    def test_report_has_explicit_release_blockers(self):
        result = stage14_acceptance.report()
        self.assertEqual(result["stage"], "14/14")
        self.assertTrue(result["technical_checks"]["legal_guard_present"])
        self.assertTrue(result["technical_checks"]["static_installer_present"])
        self.assertTrue(result["technical_checks"]["rollback_runbook_present"])
        self.assertFalse(result["release_ready"])
        self.assertGreater(len(result["release_blockers"]), 0)

    def test_uncommitted_changes_are_not_accepted(self):
        original = stage14_acceptance.git

        def fake_git(*args):
            return " M web/app.js" if args == ("status", "--porcelain") else original(*args)

        with patch.object(stage14_acceptance, "git", side_effect=fake_git):
            result = stage14_acceptance.report()
        self.assertFalse(result["technical_checks"]["clean_git_worktree"])
        self.assertFalse(result["technical_pass"])


if __name__ == "__main__":
    unittest.main()
