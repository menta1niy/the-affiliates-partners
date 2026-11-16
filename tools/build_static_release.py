#!/usr/bin/env python3
"""Build a deterministic, public-only Partners Mini App release from local code.

No database, .env, SSH keys or other private files are included.
Usage: python tools/build_static_release.py [output-directory]
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web"
OUTPUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "dist-static"
REQUIRED = {
    "index.html",
    "admin/index.html",
    "app.js",
    "admin/admin.js",
    "style.css",
    "telegram-layout.js",
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main() -> None:
    if git("status", "--porcelain", "--untracked-files=all", "--", "web"):
        raise SystemExit("Web source has uncommitted changes: commit and validate first")
    commit = git("rev-parse", "HEAD")
    files = []
    for directory, dirs, names in os.walk(SOURCE, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            if path.is_symlink():
                raise SystemExit(f"Symlinks are forbidden in static release: {path}")
        for name in names:
            path = Path(directory) / name
            if not path.is_file():
                raise SystemExit(f"Non-regular asset: {path}")
            files.append(path)
    files.sort()
    paths = {p.relative_to(SOURCE).as_posix() for p in files}
    tracked = set(git("ls-files", "--cached", "--", "web").splitlines())
    tracked = {name.removeprefix("web/") for name in tracked}
    if paths != tracked:
        raise SystemExit("Release assets differ from tracked web files (including ignored files)")
    if not REQUIRED.issubset(paths):
        raise SystemExit("Required Mini App assets are missing")
    if "owner-preview.js" in paths:
        raise SystemExit("Demo preview asset must not be in the release")
    manifest = {
        "commit": commit,
        "theme": "monochrome-glass-v1",
        "files": {
            p.relative_to(SOURCE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
    }
    if any(p.startswith(".") or "/." in p or p.endswith(".env") for p in paths):
        raise SystemExit("Hidden or environment file found in release")
    if OUTPUT == SOURCE or SOURCE in OUTPUT.parents:
        raise SystemExit("Output must be outside the web source")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    archive = OUTPUT / f"partners-web-{commit[:12]}.tar.gz"
    serialized = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    # Files are written with fixed metadata for reproducible release contents.
    with archive.open("wb") as file_out:
        import gzip
        with gzip.GzipFile(fileobj=file_out, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tar:
                for p in files:
                    name = p.relative_to(SOURCE).as_posix()
                    contents = p.read_bytes()
                    info = tarfile.TarInfo("web/" + name)
                    info.size = len(contents)
                    info.mtime = 0
                    info.mode = 0o644
                    tar.addfile(info, io.BytesIO(contents))
                info = tarfile.TarInfo("manifest.json")
                info.size = len(serialized)
                info.mtime = 0
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(serialized))
    (OUTPUT / f"{archive.name}.sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n",
        encoding="ascii",
    )
    print(f"release={archive}")
    print(f"commit={commit}")
    print(f"files={len(files)}")


if __name__ == "__main__":
    main()
