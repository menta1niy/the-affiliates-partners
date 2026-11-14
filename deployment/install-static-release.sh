#!/usr/bin/env bash
# Static-only deployment from a locally built, SHA-256-verified archive.
# Never runs migrations, overwrites secrets, or restarts any API service.
set -euo pipefail
umask 027

ARCHIVE="${1:?Usage: install-static-release.sh release.tar.gz expected-sha256}"
EXPECTED="${2:?Specify the exact SHA-256 from the local build manifest}"
PUBLIC=/var/www/theaffiliates-partners
RELEASES=/var/www/theaffiliates-partners.releases
LOCK=/run/lock/the-affiliates-partners-static.lock

[[ $EUID -eq 0 ]] || { echo "Root required" >&2; exit 1; }
[[ $EXPECTED =~ ^[0-9a-fA-F]{64}$ ]] || { echo "Invalid checksum" >&2; exit 1; }
test -f "$ARCHIVE"
ACTUAL="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
[[ "${ACTUAL,,}" == "${EXPECTED,,}" ]] || { echo "Archive checksum mismatch" >&2; exit 1; }

exec 9>"$LOCK"
flock -n 9 || { echo "Another release is running" >&2; exit 1; }
install -d -m 0755 "$RELEASES"
STAGING="$(mktemp -d "$RELEASES/.stage.XXXXXXXX")"
trap 'rm -rf -- "$STAGING"' EXIT

# Validate names before unpacking so an archive cannot write outside staging.
python3 - "$ARCHIVE" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1], "r:gz") as archive:
    names = [member.name for member in archive]
    if len(names) != len(set(names)):
        raise SystemExit("Duplicate paths in release")
    for member in archive:
        path = member.name
        if not (path == "manifest.json" or path.startswith("web/")):
            raise SystemExit("Unexpected archive root")
        if ".." in path.split("/") or path.startswith("/") or not member.isfile():
            raise SystemExit("Unsafe archive member")
PY
tar -xzf "$ARCHIVE" -C "$STAGING" --no-same-owner --no-same-permissions
python3 - "$STAGING" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text("utf-8"))
files = manifest["files"]
expected = {"index.html", "admin/index.html", "app.js", "admin/admin.js",
            "style.css", "theme-green.css", "telegram-layout.js"}
if not expected.issubset(files):
    raise SystemExit("Required files absent from manifest")
actual = {p.relative_to(root / "web").as_posix() for p in (root / "web").rglob("*") if p.is_file()}
if actual != set(files):
    raise SystemExit("Manifest differs from archive content")
for path, digest in files.items():
    if hashlib.sha256((root / "web" / path).read_bytes()).hexdigest() != digest:
        raise SystemExit("File checksum mismatch")
if "theme-green.css?v=1" not in (root / "web" / "admin" / "index.html").read_text("utf-8"):
    raise SystemExit("Admin is not loading the theme")
if "theme-green.css?v=1" not in (root / "web" / "index.html").read_text("utf-8"):
    raise SystemExit("User app is not loading the theme")
print("VALIDATED_COMMIT", manifest["commit"])
PY

COMMIT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["commit"])' "$STAGING/manifest.json")"
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "Unexpected git SHA" >&2; exit 1; }
RELEASE="$RELEASES/${COMMIT:0:12}"
[[ ! -e "$RELEASE" ]] || { echo "Release already installed; no changes made" >&2; exit 0; }
mv -- "$STAGING/web" "$RELEASE"
chown -R root:www-data "$RELEASE"
find "$RELEASE" -type d -exec chmod 0755 {} +
find "$RELEASE" -type f -exec chmod 0644 {} +

# Preserve existing live files outside the public tree as a rollback copy.
BACKUP="$RELEASES/previous-$(date -u +%Y%m%dT%H%M%SZ)"
test ! -e "$BACKUP"
if [[ -L "$PUBLIC" ]]; then
    PREVIOUS="$(readlink "$PUBLIC")"
    ln -s "$RELEASE" "$PUBLIC.next"
    mv -Tf "$PUBLIC.next" "$PUBLIC"
    echo "PREVIOUS_RELEASE=$PREVIOUS"
elif [[ -d "$PUBLIC" ]]; then
    mv "$PUBLIC" "$BACKUP"
    if ! ln -s "$RELEASE" "$PUBLIC"; then
        mv "$BACKUP" "$PUBLIC"
        exit 1
    fi
    echo "ROLLBACK_COPY=$BACKUP"
else
    ln -s "$RELEASE" "$PUBLIC"
fi
echo "STATIC_RELEASE_ACTIVE=$COMMIT"
