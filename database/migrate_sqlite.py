"""Explicit SQLite -> empty staging PostgreSQL copy. Never reads default live DB.

Usage: python -m database.migrate_sqlite --sqlite PATH --postgres-url URL --confirm-empty-target
The source is opened read-only; target must have no existing users/invites/outbox/audit.
"""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from database.postgres import SCHEMA

TABLES = ("users", "invitations", "pending_starts", "telegram_updates",
          "audit", "notifications_outbox", "internal_id_sequence", "crm_events",
          "crm_lead_bindings", "crm_assigned_offers")
USER_REFS = ("agency_id", "referrer_id", "manager_id", "introduced_by_id")


def copy(sqlite_path, target_url):
    import psycopg
    from psycopg import sql
    source = Path(sqlite_path).resolve(strict=True)
    if source.suffix not in (".sqlite3", ".db", ".sqlite"):
        raise ValueError("Explicit SQLite database path required")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        src.row_factory = sqlite3.Row
        with psycopg.connect(target_url) as dst:
            dst.execute("CREATE SCHEMA IF NOT EXISTS partners")
            dst.execute("SET LOCAL search_path TO partners")
            dst.execute(SCHEMA)
            for table in TABLES:
                if dst.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))).fetchone():
                    raise ValueError("Target PostgreSQL must be empty: " + table)
            copied = {}
            for table in TABLES:
                if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    copied[table] = 0
                    continue
                source_columns = {row[1] for row in src.execute("PRAGMA table_info(" + table + ")")}
                target_columns = {r[0] for r in dst.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s",
                    (table,))}
                cols = sorted(source_columns & target_columns)
                records = src.execute("SELECT * FROM " + table).fetchall()
                # User references can point forward, so restore them in a second pass.
                insert_cols = [c for c in cols if not (table == "users" and c in USER_REFS)]
                statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(",").join(map(sql.Identifier, insert_cols)),
                    sql.SQL(",").join(sql.Placeholder() for _ in insert_cols))
                for row in records:
                    dst.execute(statement, tuple(row[c] for c in insert_cols))
                if table == "users":
                    for row in records:
                        present = [c for c in USER_REFS if c in cols and row[c] is not None]
                        if present:
                            dst.execute(sql.SQL("UPDATE users SET {} WHERE id=%s").format(
                                sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(c)) for c in present)),
                                (*[row[c] for c in present], row["id"]))
                copied[table] = len(records)
            for table in ("audit", "notifications_outbox"):
                dst.execute("SELECT setval(pg_get_serial_sequence(%s,'id'),"
                            "GREATEST(COALESCE((SELECT MAX(id) FROM " + table + "),0),1),"
                            "EXISTS(SELECT 1 FROM " + table + "))", (table,))
            dst.execute("UPDATE internal_id_sequence SET next_id=GREATEST(next_id,"
                        "COALESCE((SELECT MAX(internal_id)+1 FROM users),100)) WHERE singleton=1")
            return copied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--postgres-url", required=True)
    parser.add_argument("--confirm-empty-target", action="store_true")
    args = parser.parse_args()
    if not args.confirm_empty_target:
        parser.error("--confirm-empty-target required; destination will be populated")
    print("Copied to staging PostgreSQL:", copy(args.sqlite, args.postgres_url))


if __name__ == "__main__":
    main()
