"""Local, read-only final acceptance report. Never performs deployment.

Usage: python -m tools.stage14_acceptance [--require-ready]
The report distinguishes completed development from release authorization.
"""
import argparse
import json
import subprocess
from pathlib import Path

from tools.stage13_preflight import inspect


ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def report():
    previous = inspect(ROOT)
    commit = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    dirty = git("status", "--porcelain")
    expected_branch = "feature/green-theme-20261114"
    checks = {
        **previous["technical_checks"],
        "local_branch": branch == expected_branch,
        "clean_git_worktree": not dirty,
        "legal_guard_present": (ROOT / "tools/check_legal_release.py").is_file(),
        "static_installer_present": (ROOT / "deployment/install-static-release.sh").is_file(),
        "postgres_restore_drill_script_present": (ROOT / "deployment/verify-postgres-restore.sh").is_file(),
        "rollback_runbook_present": (ROOT / "docs/FINAL_RELEASE_RUNBOOK_STAGE14.md").is_file(),
    }
    return {
        "stage": "14/14",
        "commit": commit,
        "branch": branch,
        "technical_checks": checks,
        "technical_pass": all(checks.values()),
        "release_ready": all(checks.values()) and previous["release_ready"],
        "release_blockers": previous["release_blockers"],
        "notes": [
            "Full unittest suite and PostgreSQL acceptance are reported separately; this is a source contract check.",
            "No GitHub push, SSH, database connection or deployment is performed.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    result = report()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["technical_pass"] or (args.require_ready and not result["release_ready"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
