#!/usr/bin/env bash
# Opt-in, root-only preparation. Does not start/restart units or enable timers.
set -Eeuo pipefail
umask 077
[[ "${1:-}" == '--enable' && "$#" -eq 1 && "$EUID" -eq 0 ]] || {
  echo 'Usage: sudo bash deployment/provision-runtime-user.sh --enable' >&2
  exit 2
}
root=/opt/the-affiliates-partners
user=ta-partners
marker=/etc/the-affiliates-partners/runtime-user-ready
cd "$root" 2>/dev/null || { echo 'Application checkout missing' >&2; exit 1; }
[[ -d "$root" && -f "$root/.env.local" && ! -L "$root/.env.local" ]] || {
  echo 'Expected application checkout and regular .env.local missing' >&2; exit 1;
}
command -v useradd >/dev/null
command -v runuser >/dev/null
command -v install >/dev/null
if ! id "$user" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin "$user"
fi
[[ "$(id -u "$user")" -ne 0 ]] || { echo 'Refusing root runtime identity' >&2; exit 1; }
install -d -o root -g "$user" -m 0750 /etc/the-affiliates-partners
chown root:"$user" "$root/.env.local"
chmod 0640 "$root/.env.local"
install -d -o "$user" -g "$user" -m 0700 "$root/data"
# Files created by legacy root processes must be migrated intentionally.
if [[ -e "$root/data/partners.sqlite3" ]]; then
  for file in "$root/data/partners.sqlite3" "$root/data/partners.sqlite3-wal" "$root/data/partners.sqlite3-shm"; do
    if [[ -e "$file" ]]; then
      [[ -f "$file" && ! -L "$file" ]] || { echo 'Unsafe SQLite file type' >&2; exit 1; }
      chown "$user":"$user" "$file"
      chmod 0600 "$file"
    fi
  done
fi
runuser -u "$user" -- test -r "$root/.env.local"
runuser -u "$user" -- test -w "$root/data"
runuser -u "$user" -- test -r "$root/server/api.py"
runuser -u "$user" -- /usr/bin/python3 -c 'from server.settings import bot_token; assert bot_token(), "Missing bot token"' \
  </dev/null
install -o root -g root -m 0644 /dev/null "$marker"
echo 'Runtime identity ready. Review units then explicitly restart/enable them.'
