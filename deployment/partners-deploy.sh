#!/usr/bin/env bash
set -euo pipefail

# Independent of /opt/the-affiliates and the-affiliates-deploy.timer.
ROOT=/opt/the-affiliates-partners
TARGET=/var/www/theaffiliates-partners
LOCK=/run/lock/the-affiliates-partners-deploy.lock
exec 9>"$LOCK"
flock -n 9 || exit 0
cd "$ROOT"
umask 077
BRANCH=$(git symbolic-ref --quiet --short HEAD || true)
if [ "$BRANCH" != "main" ]; then
  echo "Refusing automatic deploy from branch: ${BRANCH:-detached}" >&2
  exit 1
fi

git fetch --quiet origin main
REMOTE=$(git rev-parse FETCH_HEAD)
CURRENT=$(git rev-parse HEAD)
MARKER="${TARGET}.deployed"
DEPLOYED=$(cat "$MARKER" 2>/dev/null || true)
if [ "$REMOTE" = "$DEPLOYED" ] && [ -f "$TARGET/index.html" ]; then exit 0; fi

git diff --quiet && git diff --cached --quiet || { echo 'Local changes: refusing deploy' >&2; exit 1; }
git merge --ff-only "$REMOTE"
API_CHANGED=false
BOT_CHANGED=false
SERVICE_CHANGED=false
if [ -z "$DEPLOYED" ]; then
  API_CHANGED=true
  BOT_CHANGED=true
else
  if git diff --name-only "$DEPLOYED" "$REMOTE" -- server | grep -q .; then API_CHANGED=true; BOT_CHANGED=true; fi
  if git diff --name-only "$DEPLOYED" "$REMOTE" -- deployment/*.service | grep -q .; then SERVICE_CHANGED=true; fi
fi
python3 -m py_compile server/app.py server/bot.py server/config.py
python3 -m unittest discover -s tests -q
npm ci --no-audit --no-fund --silent
npm run build
test -s dist/index.html
grep -q '/partners/assets/' dist/index.html

if [ "$API_CHANGED" = true ] || [ "$BOT_CHANGED" = true ]; then
  mkdir -p "$ROOT/.database-backups"
  # Resolve the same configured DB path as bot and API; never assume the
  # default repository path if PARTNERS_DB_PATH is configured.
  python3 - "$REMOTE" "$ROOT/.database-backups" <<'PY'
import sys
from pathlib import Path
from sqlite3 import connect
sys.path.insert(0, str(Path.cwd() / "server"))
from app import DB
if not DB.is_file():
    raise SystemExit("Refusing to restart: configured Partners database is missing")
destination = Path(sys.argv[2]) / ("before-" + sys.argv[1][:12] + ".sqlite3")
with connect(DB) as source, connect(destination) as backup:
    source.backup(backup)
    if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise SystemExit("Refusing to restart: backup integrity failed")
PY
fi

mkdir -p "${TARGET}.releases"
RELEASE="${TARGET}.releases/${REMOTE:0:12}"
mkdir -p "$RELEASE"
cp -a dist/. "$RELEASE/"
PREVIOUS_RELEASE=""
if [ -L "$TARGET" ]; then
  PREVIOUS_RELEASE=$(readlink "$TARGET")
fi
release_committed=false
restore_previous_release() {
  code=$?
  if [ "$code" -ne 0 ] && [ "$release_committed" = false ] && [ -n "$PREVIOUS_RELEASE" ]; then
    echo 'Release verification failed; restoring previous Mini App symlink' >&2
    ln -s "$PREVIOUS_RELEASE" "${TARGET}.rollback"
    mv -Tf "${TARGET}.rollback" "$TARGET"
    # Git and the database have not been reverted. Rebooting services here
    # would not restore the prior server code, so stop rather than pretending.
  fi
}
trap restore_previous_release EXIT
if [ -L "$TARGET" ]; then
  ln -s "$RELEASE" "${TARGET}.next"
  mv -Tf "${TARGET}.next" "$TARGET"
elif [ ! -e "$TARGET" ]; then
  ln -s "$RELEASE" "$TARGET"
else
  echo 'Target exists and is not a symlink: refusing deploy' >&2
  exit 1
fi
if [ "$SERVICE_CHANGED" = true ]; then
  cp deployment/the-affiliates-partners-api.service deployment/the-affiliates-partners-bot.service /etc/systemd/system/
  systemctl daemon-reload
  API_CHANGED=true
  BOT_CHANGED=true
fi
if [ "$API_CHANGED" = true ]; then
  systemctl restart the-affiliates-partners-api.service
  systemctl is-active --quiet the-affiliates-partners-api.service
  curl --fail --silent --max-time 8 http://127.0.0.1:8788/api/health >/dev/null
fi
if [ "$BOT_CHANGED" = true ]; then
  systemctl restart the-affiliates-partners-bot.service
  systemctl is-active --quiet the-affiliates-partners-bot.service
fi
printf '%s\n' "$REMOTE" > "${MARKER}.next"
mv -f "${MARKER}.next" "$MARKER"
release_committed=true
echo "Mini App released at $REMOTE"
