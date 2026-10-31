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
DEPLOYED="$(cat "${PUBLIC}.deployed" 2>/dev/null || true)"
if [ "$REMOTE" = "$DEPLOYED" ] && [ -f "$PUBLIC/index.html" ]; then
  exit 0
fi
git diff --quiet && git diff --cached --quiet || {
  echo "Refusing deploy with modified tracked files" >&2
  exit 1
}
git merge --ff-only "$REMOTE"

# No npm, React, Vite, CRM or database migration.
python3 -m compileall -q server
python3 -m unittest discover -s tests -q
python3 -c 'from server.settings import bot_token,app_url; assert bot_token() and app_url(), "Telegram settings missing"'
test -s web/index.html
test -s web/app.js
test -s web/style.css

# Check the new API on a separate port before restarting the production API.
SERVER_PORT=8799 python3 -m server.api >/dev/null 2>&1 &
PROBE_PID=$!
trap 'kill "$PROBE_PID" 2>/dev/null || true' EXIT
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
trap - EXIT

install -d -m 0755 "$RELEASES"
RELEASE="$RELEASES/${REMOTE:0:12}"
mkdir -p "$RELEASE"
cp -a web/. "$RELEASE/"
find "$RELEASE" -type d -exec chmod 0755 {} +
find "$RELEASE" -type f -exec chmod 0644 {} +

install -m 0644 deployment/the-affiliates-partners-api.service /etc/systemd/system/
install -m 0644 deployment/the-affiliates-partners-deploy.service /etc/systemd/system/
install -m 0644 deployment/the-affiliates-partners-deploy.timer /etc/systemd/system/
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
printf '%s\n' "$REMOTE" > "${PUBLIC}.deployed.next"
mv -f "${PUBLIC}.deployed.next" "${PUBLIC}.deployed"
echo "Partners fresh release: $REMOTE"
