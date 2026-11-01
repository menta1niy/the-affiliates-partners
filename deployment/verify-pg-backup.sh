#!/usr/bin/env bash
# Restore a Partners-only dump into an isolated database using local postgres.
set -Eeuo pipefail
umask 077
[[ "$#" -eq 1 && -f "$1" && ! -L "$1" && "$EUID" -eq 0 ]] || {
  echo 'Usage (root): verify-pg-backup.sh /private/partners.pgdump' >&2; exit 2;
}
archive="$(realpath -- "$1")"
name="partners_verify_$(date -u +%Y%m%d%H%M%S)_$$"
created=0
cleanup() {
  if [[ "$created" == 1 ]]; then
    runuser -u postgres -- dropdb --if-exists -- "$name" ||
      echo "Manual cleanup needed: $name" >&2
  fi
}
trap cleanup EXIT
pg_restore --list "$archive" >/dev/null
runuser -u postgres -- createdb -T template0 -- "$name"
created=1
runuser -u postgres -- pg_restore --exit-on-error --no-owner --no-acl --dbname "$name" < "$archive"
tables="$(runuser -u postgres -- psql -X -At -d "$name" -c "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname='partners'")"
[[ "$tables" =~ ^[0-9]+$ && "$tables" -ge 10 ]] || {
  echo 'Restore failed: Partners schema tables absent/incomplete' >&2; exit 1;
}
echo "Restored $tables Partners tables into disposable database"
