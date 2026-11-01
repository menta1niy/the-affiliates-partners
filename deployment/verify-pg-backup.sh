#!/usr/bin/env bash
# Restore a Partners-only dump into an isolated database using local postgres.
set -Eeuo pipefail
umask 077
[[ "$#" -eq 2 && -f "$1" && ! -L "$1" && "$EUID" -eq 0 && "$2" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || {
  echo 'Usage (root): verify-pg-backup.sh /private/partners.pgdump source_database' >&2; exit 2;
}
archive="$(realpath -- "$1")"
source_db="$2"
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
# Compare the restored backup to the current source as a diagnostic. The dump
# uses an MVCC snapshot, so writes after it started may change live counts.
# Never fail solely on a difference caused by concurrent production activity.
for table in users invitations crm_registration_outbox crm_assigned_offers participant_task_reports; do
  restored="$(runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -At -d "$name" -c "SELECT count(*) FROM partners.$table")"
  source="$(runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -At -d "$source_db" -c "SELECT count(*) FROM partners.$table")"
  [[ "$restored" =~ ^[0-9]+$ && "$source" =~ ^[0-9]+$ ]] || {
    echo "Invalid row count: $table" >&2; exit 1;
  }
  if [[ "$restored" != "$source" ]]; then
    echo "WARNING: $table rows restored=$restored live-now=$source; investigate concurrent writes" >&2
  fi
done
