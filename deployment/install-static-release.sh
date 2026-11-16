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
[[ ! -L "$ARCHIVE" ]] || { echo "Archive must be a regular file" >&2; exit 1; }
ACTUAL="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
[[ "${ACTUAL,,}" == "${EXPECTED,,}" ]] || { echo "Archive checksum mismatch" >&2; exit 1; }

exec 9>"$LOCK"
flock -n 9 || { echo "Another release is running" >&2; exit 1; }
install -d -m 0755 "$RELEASES"
STAGING="$(mktemp -d "$RELEASES/.stage.XXXXXXXX")"
trap 'rm -rf -- "$STAGING"' EXIT

# Validate names before unpacking so an archive cannot write outside staging.
python3 - "$ARCHIVE" <<'PY'
import pathlib, sys, tarfile
with tarfile.open(sys.argv[1], "r:gz") as archive:
    members = archive.getmembers()
    names = [member.name for member in members]
    if len(members) > 10000 or sum(member.size for member in members) > 512 * 1024 * 1024:
        raise SystemExit("Release exceeds size or file limits")
    if len(names) != len(set(names)):
        raise SystemExit("Duplicate paths in release")
    if "manifest.json" not in names:
        raise SystemExit("Missing manifest")
    for member in members:
        path = member.name
        if not (path == "manifest.json" or path.startswith("web/")):
            raise SystemExit("Unexpected archive root")
        parts = path.split("/")
        if (path.startswith("/") or any(part in ("", ".", "..") for part in parts)
                or "\\" in path or not member.isfile() or member.size > 128 * 1024 * 1024):
            raise SystemExit("Unsafe archive member")
PY
tar -xzf "$ARCHIVE" -C "$STAGING" --no-same-owner --no-same-permissions
python3 - "$STAGING" <<'PY'
import hashlib, json, pathlib, re, sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text("utf-8"))
files = manifest["files"]
if not isinstance(files, dict) or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("commit", "")):
    raise SystemExit("Invalid release manifest")
expected = {"index.html", "admin/index.html", "app.js", "admin/admin.js",
            "style.css", "telegram-layout.js"}
if not expected.issubset(files):
    raise SystemExit("Required files absent from manifest")
actual = {p.relative_to(root / "web").as_posix() for p in (root / "web").rglob("*") if p.is_file()}
if actual != set(files):
    raise SystemExit("Manifest differs from archive content")
for path, digest in files.items():
    if (not isinstance(path, str) or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or path.startswith("/") or "\\" in path
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise SystemExit("Unsafe manifest file entry")
    if hashlib.sha256((root / "web" / path).read_bytes()).hexdigest() != digest:
        raise SystemExit("File checksum mismatch")
for html in (root / "web" / "index.html", root / "web" / "admin" / "index.html"):
    source = html.read_text("utf-8")
    if 'href="/partners/style.css"' not in source or "theme-green.css" in source:
        raise SystemExit("Mini App must load only the consolidated stylesheet")
if manifest.get("theme") != "monochrome-glass-v1":
    raise SystemExit("Unexpected visual theme identifier")
css = (root / "web" / "style.css").read_text("utf-8")
if "--color-bg: #080909" not in css or "--color-accent: #FFFFFF" not in css:
    raise SystemExit("Monochrome glass design tokens missing")
print("VALIDATED_COMMIT", manifest["commit"])
PY

COMMIT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["commit"])' "$STAGING/manifest.json")"
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "Unexpected git SHA" >&2; exit 1; }
RELEASE="$RELEASES/$COMMIT"
if [[ -e "$RELEASE" || -L "$RELEASE" ]]; then
    if [[ -L "$PUBLIC" && "$(readlink -f "$PUBLIC")" == "$RELEASE" ]]; then
        echo "Release already active; no changes made"
        exit 0
    fi
    echo "Release exists but is not active; refusing to overwrite or skip cutover" >&2
    exit 1
fi
chown -R root:www-data "$STAGING/web"
find "$STAGING/web" -type d -exec chmod 0755 {} +
find "$STAGING/web" -type f -exec chmod 0644 {} +
mv -- "$STAGING/web" "$RELEASE"

# Preserve existing live files outside the public tree as a rollback copy.
BACKUP="$(mktemp -d "$RELEASES/.previous.XXXXXXXX")"
rmdir "$BACKUP"
if [[ -L "$PUBLIC" ]]; then
    PREVIOUS="$(readlink "$PUBLIC")"
    NEXT="$(mktemp "$RELEASES/.link.XXXXXXXX")"
    rm -- "$NEXT"
    ln -s "$RELEASE" "$NEXT"
    mv -Tf -- "$NEXT" "$PUBLIC"
    echo "PREVIOUS_RELEASE=$PREVIOUS"
elif [[ -d "$PUBLIC" ]]; then
    mv "$PUBLIC" "$BACKUP"
    if ! ln -s "$RELEASE" "$PUBLIC"; then
        mv -- "$BACKUP" "$PUBLIC" || echo "URGENT: Restore directory manually from $BACKUP" >&2
        exit 1
    fi
    echo "ROLLBACK_COPY=$BACKUP"
elif [[ -e "$PUBLIC" ]]; then
    echo "Refusing to replace unexpected public path" >&2
    exit 1
else
    ln -s "$RELEASE" "$PUBLIC"
fi
echo "STATIC_RELEASE_ACTIVE=$COMMIT"
