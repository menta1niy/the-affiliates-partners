#!/usr/bin/env python3
"""Audit static release inputs locally without creating a deployable archive.

Draft legal pages are expected during preparation. This command reports their
release gate as blocked and never writes an approval record or release artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# The existing build utility imports its sibling by top-level name.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_static_release import REQUIRED
from check_legal_release import validate as validate_legal_release


ROOT = Path(__file__).resolve().parents[1]


def audit(root: Path, *, tracked: set[str]) -> dict:
    source = root / "web"
    files: dict[str, str] = {}
    errors: list[str] = []
    for directory, dirs, names in os.walk(source, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            if path.is_symlink():
                errors.append(f"symlink forbidden: {path.relative_to(source).as_posix()}")
        for name in names:
            path = Path(directory) / name
            rel = path.relative_to(source).as_posix()
            if path.is_symlink() or not path.is_file():
                continue
            if rel.startswith(".") or "/." in rel or rel.endswith(".env"):
                errors.append(f"private/hidden asset forbidden: {rel}")
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    missing = sorted(REQUIRED - files.keys())
    if missing:
        errors.append("required assets missing: " + ", ".join(missing))
    if "owner-preview.js" in files:
        errors.append("demo preview asset forbidden: owner-preview.js")
    unexpected = sorted(files.keys() - tracked)
    absent = sorted(tracked - files.keys())
    if unexpected:
        errors.append("untracked assets: " + ", ".join(unexpected))
    if absent:
        errors.append("tracked assets missing: " + ", ".join(absent))
    try:
        legal_version = validate_legal_release(root)
        legal_gate = "open"
        legal_reason = ""
    except (ValueError, OSError, json.JSONDecodeError) as error:
        legal_version = None
        legal_gate = "blocked"
        legal_reason = str(error)
    return {
        "asset_integrity": "pass" if not errors else "fail",
        "asset_errors": errors,
        "files": len(files),
        "source_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
        "legal_gate": legal_gate,
        "legal_reason": legal_reason,
        "legal_version": legal_version,
        "release_ready": not errors and legal_gate == "open",
        "publishing_performed": False,
    }


def main() -> int:
    tracked = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--", "web"], text=True
    ).splitlines()
    result = audit(ROOT, tracked={p.removeprefix("web/") for p in tracked})
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    # A blocked legal gate is an expected draft state: the result makes it explicit.
    return 1 if result["asset_integrity"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
