#!/usr/bin/env bash
# Manual restore drill for a Partners-only pg_dump archive. Does not access the live database.
set -Eeuo pipefail
umask 077

if [[ "$#" -ne 1 || ! -f "$1" || -L "$1" ]]; then
  echo 'Usage: verify-postgres-restore.sh /private/path/partners.pgdump' >&2
  exit 2
fi
if [[ "$EUID" -ne 0 ]]; then
  echo 'Run as root on a trusted PostgreSQL recovery host.' >&2
  exit 2
fi

archive="$(realpath -- "$1")"
scratch="partners_restore_check_$(date -u +%Y%m%d%H%M%S)_$$"
created=0
cleanup() {
  if [[ "$created" -eq 1 ]]; then
    runuser -u postgres -- dropdb --if-exists -- "$scratch" || \
      echo "Manual cleanup required: $scratch" >&2
  fi
}
trap cleanup EXIT

# Refuse archives containing public CRM schema objects or extension/database DDL.
toc="$(mktemp)"
trap 'rm -f -- "$toc"; cleanup' EXIT
pg_restore --list -- "$archive" > "$toc"
python3 - "$toc" <<'PY'
import pathlib, sys
entries = []
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    if line.startswith(';') or not line.strip():
        continue
    fields = line.split(';', 1)[-1].strip().split()
    entries.append(fields)
    if len(fields) < 5 or ('partners' not in fields[2:] and not (len(fields) >= 4 and fields[0] == 'SCHEMA' and fields[1] == '-')):
        raise SystemExit('Archive has objects outside the Partners schema or unknown TOC entries')
if not entries:
    raise SystemExit('Archive is empty')
PY
runuser -u postgres -- createdb -T template0 -- "$scratch"
created=1
runuser -u postgres -- pg_restore --exit-on-error --no-owner --no-acl --dbname "$scratch" < "$archive"
count="$(runuser -u postgres -- psql -X -At -d "$scratch" -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'partners' AND table_type = 'BASE TABLE'")"
if [[ "$count" -lt 10 ]]; then
  echo 'Restored Partners schema has fewer tables than expected' >&2
  exit 1
fi
echo "Restore rehearsal passed: $count Partners tables in disposable database."
