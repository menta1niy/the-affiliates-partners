#!/usr/bin/env bash
# Independent Partners-only deployment. Never touches the main CRM site.
set -euo pipefail
umask 077

ROOT=/opt/the-affiliates-partners
PUBLIC=/var/www/theaffiliates-partners
RELEASES=/var/www/theaffiliates-partners.releases
LOCK=/run/lock/the-affiliates-partners-deploy.lock

exec 9>"$LOCK"
flock -n 9 || exit 0
cd "$ROOT"

if [ "$(git branch --show-current)" != "main" ]; then
  echo "Refusing to deploy non-main branch" >&2
  exit 1
fi
test -f .env.local || { echo "Missing private .env.local" >&2; exit 1; }
git fetch --quiet origin main
REMOTE="$(git rev-parse FETCH_HEAD)"
CURRENT="$(git rev-parse HEAD)"
DEPLOYED="$(cat "${PUBLIC}.deployed" 2>/dev/null || true)"
if [ "$REMOTE" = "$DEPLOYED" ] && [ -f "$PUBLIC/index.html" ]; then
  exit 0
fi
git diff --quiet && git diff --cached --quiet || {
  echo "Refusing deploy with modified tracked files" >&2
  exit 1
}
PREVIOUS_RELEASE="$(readlink "$PUBLIC" 2>/dev/null || true)"
committed=false
restore_on_failure() {
  result=$?
  if [ -n "${PROBE_PID:-}" ]; then
    kill "$PROBE_PID" 2>/dev/null || true
  fi
  if [ "$result" -ne 0 ] && [ "$committed" != true ]; then
    echo "Partners deployment failed; restoring previous application source and static release" >&2
    if [ -n "$PREVIOUS_RELEASE" ]; then
      ln -s "$PREVIOUS_RELEASE" "${PUBLIC}.rollback"
      mv -Tf "${PUBLIC}.rollback" "$PUBLIC"
    fi
    git reset --hard "$CURRENT" >/dev/null
    systemctl restart the-affiliates-partners-api.service || true
  fi
}
trap restore_on_failure EXIT

# Preserve a transactionally consistent copy of the new live database before
# any new server code touches its schema. Never expose the backup over HTTP.
install -d -m 0700 "$ROOT/.database-backups"
# PostgreSQL cutover must be explicitly approved after a tested SQLite export,
# restore rehearsal and backward-compatible schema review. A source rollback
# cannot reverse committed PostgreSQL DDL or recover overwritten user rows.
python3 - "$ROOT" "${REMOTE:0:12}" <<'PY'
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

root = Path(sys.argv[1])
release = sys.argv[2]
config = {}
for raw in (root / ".env.local").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    config[key.strip()] = value.strip().strip('"').strip("'")
url = os.environ.get("PARTNERS_DATABASE_URL") or config.get("PARTNERS_DATABASE_URL", "")
if url:
    approval = root / ".pg-cutover-approved"
    if not approval.is_file():
        raise SystemExit("PostgreSQL deploy blocked: private cutover approval and restore rehearsal required")
    backup = root / ".database-backups" / (f"before-{release}-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".pgdump")
    parsed = urlsplit(url)
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname or not parsed.path:
        raise SystemExit("Invalid PostgreSQL URL; refusing deployment")
    env = os.environ.copy()
    env.update(PGHOST=parsed.hostname, PGPORT=str(parsed.port or 5432),
               PGUSER=unquote(parsed.username or ""),
               PGPASSWORD=unquote(parsed.password or ""),
               PGDATABASE=unquote(parsed.path.lstrip("/")))
    try:
        with backup.open("xb") as output:
            subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-acl"],
                           stdout=output, stderr=subprocess.PIPE, env=env, check=True)
        backup.chmod(0o600)
        subprocess.run(["pg_restore", "--list", str(backup)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError):
        backup.unlink(missing_ok=True)
        raise SystemExit("PostgreSQL backup/verification failed; refusing deployment")
    print("Private PostgreSQL archive verified; database rollback remains a separate controlled operation")
PY
python3 - "$ROOT" "${REMOTE:0:12}" <<'PY'
import os
import sqlite3
import sys
from pathlib import Path
root = Path(sys.argv[1])
db = Path(os.environ.get("PARTNERS_DB_PATH") or root / "data" / "partners.sqlite3")
if not db.is_absolute():
    db = root / db
if db.is_file():
    backup = root / ".database-backups" / ("before-" + sys.argv[2] + ".sqlite3")
    with sqlite3.connect(str(db)) as source, sqlite3.connect(str(backup)) as target:
        source.backup(target)
        if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise SystemExit("Database backup integrity failed")
    backup.chmod(0o600)
    print("Partners database backup verified")
else:
    print("No existing Partners registration database; fresh schema will be created")
PY
git merge --ff-only "$REMOTE"

# No npm, React, Vite or CRM deployment changes.
python3 -m compileall -q server
python3 -m unittest discover -s tests -q
python3 -c 'from server.settings import bot_token,app_url; assert bot_token() and app_url(), "Telegram settings missing"'
test -s web/index.html
test -s web/app.js
test -s web/style.css
test -s web/admin/index.html
test -s web/admin/admin.js

# Check the new API on a separate port before restarting the production API.
SERVER_PORT=8799 python3 -m server.api >/dev/null 2>&1 &
PROBE_PID=$!
API_READY=false
for attempt in 1 2 3 4 5 6 7 8; do
  if curl --fail --silent --max-time 2 http://127.0.0.1:8799/api/health >/dev/null; then
    API_READY=true
    break
  fi
  sleep 1
done
if [ "$API_READY" != true ]; then
  echo "Refusing deploy: new API cannot start" >&2
  exit 1
fi
kill "$PROBE_PID" 2>/dev/null || true
wait "$PROBE_PID" 2>/dev/null || true
PROBE_PID=""

install -d -m 0755 "$RELEASES"
RELEASE="$RELEASES/${REMOTE:0:12}"
mkdir -p "$RELEASE"
cp -a web/. "$RELEASE/"
find "$RELEASE" -type d -exec chmod 0755 {} +
find "$RELEASE" -type f -exec chmod 0644 {} +

install -m 0644 deployment/the-affiliates-partners-api.service /etc/systemd/system/
install -m 0644 deployment/the-affiliates-partners-deploy.service /etc/systemd/system/
install -m 0644 deployment/the-affiliates-partners-deploy.timer /etc/systemd/system/
install -m 0644 deployment/the-affiliates-partners-notifications.service /etc/systemd/system/
install -m 0644 deployment/the-affiliates-partners-notifications.timer /etc/systemd/system/
systemctl daemon-reload
systemctl restart the-affiliates-partners-api.service

API_READY=false
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if systemctl is-active --quiet the-affiliates-partners-api.service &&
     curl --fail --silent --max-time 2 http://127.0.0.1:8788/api/health >/dev/null; then
    API_READY=true
    break
  fi
  sleep 1
done
if [ "$API_READY" != true ]; then
  echo "API restart failed; keeping previous public release" >&2
  exit 1
fi

# The new static release is immutable. Switch the symlink only after API readiness.
ln -s "$RELEASE" "${PUBLIC}.next"
mv -Tf "${PUBLIC}.next" "$PUBLIC"
# v2 uses Telegram webhooks, not a competing getUpdates process.
systemctl disable --now the-affiliates-partners-bot.service 2>/dev/null || true
rm -f /etc/systemd/system/the-affiliates-partners-bot.service
systemctl daemon-reload
systemctl enable --now the-affiliates-partners-notifications.timer
printf '%s\n' "$REMOTE" > "${PUBLIC}.deployed.next"
mv -f "${PUBLIC}.deployed.next" "${PUBLIC}.deployed"
committed=true
echo "Partners fresh release: $REMOTE"
