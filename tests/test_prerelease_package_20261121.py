"""Local packaging audit must detect tampering and retain the draft legal block."""

import tempfile
import unittest
from pathlib import Path

from tools.prerelease_static_dry_run import audit
from tools.build_static_release import REQUIRED


class PrereleasePackageTests(unittest.TestCase):
    def test_legacy_autodeploy_is_disabled_before_any_side_effect(self):
        script = (Path(__file__).resolve().parents[1] / "deployment" / "deploy.sh").read_text(encoding="utf-8")
        prefix = script.split("ROOT=/opt/the-affiliates-partners", 1)[0]
        self.assertIn("Legacy auto-deploy is disabled", prefix)
        self.assertIn("\nexit 1\n", prefix)
        self.assertNotIn("git fetch", prefix)

    def test_missing_and_extra_assets_fail_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "web").mkdir()
            (root / "web" / "stray.js").write_text("console.log(1)")
            result = audit(root, tracked={"index.html"})
            self.assertEqual(result["asset_integrity"], "fail")
            self.assertIn("untracked assets: stray.js", result["asset_errors"])
            self.assertIn("tracked assets missing: index.html", result["asset_errors"])
            self.assertEqual(result["legal_gate"], "blocked")
            self.assertFalse(result["release_ready"])
            self.assertFalse(result["publishing_performed"])

    def test_draft_gate_is_blocked_even_when_all_assets_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in REQUIRED:
                path = root / "web" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("DRAFT", encoding="utf-8")
            tracked = set(REQUIRED)
            result = audit(root, tracked=tracked)
            self.assertEqual(result["asset_integrity"], "pass")
            self.assertEqual(result["legal_gate"], "blocked")
            self.assertFalse(result["release_ready"])
            self.assertFalse(result["publishing_performed"])


if __name__ == "__main__":
    unittest.main()
