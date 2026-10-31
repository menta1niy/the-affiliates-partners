"""Read-only configuration and shared database preflight. Never emits secrets."""
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from config import load_local_env
load_local_env()
from app import ADMIN_ID, DB


def check():
    # app.db() uses the path resolved when app was imported. Inspect that exact DB.
    expected = Path(DB).resolve()
    report = {
        "db_path": str(expected),
        "db_exists": expected.is_file(),
        "db_parent_exists": expected.parent.is_dir(),
        "db_parent_writable": os.access(expected.parent, os.W_OK),
        "telegram_token_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        "crm_feed_configured": len(os.environ.get("CRM_FEED_TOKEN", "")) >= 32
          and bool(os.environ.get("CRM_WORKSPACE_ID")),
        "app_url_configured": bool(os.environ.get("MINI_APP_URL")),
        "owner_admin_id": ADMIN_ID,
        "owner_access_via_admin_id": True,
        "owner_partner_status": "database-not-created",
    }
    if expected.is_file():
        with closing(sqlite3.connect(f"file:{expected.as_posix()}?mode=ro", uri=True)) as connection:
            report["sqlite_integrity"] = connection.execute("PRAGMA quick_check").fetchone()[0]
            report["partners_table"] = bool(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='partners'"
            ).fetchone())
            if report["partners_table"]:
                columns = {column[1] for column in connection.execute("PRAGMA table_info(partners)")}
                if {"telegram_id", "status"}.issubset(columns):
                    owner = connection.execute(
                        "SELECT status FROM partners WHERE telegram_id=?", (ADMIN_ID,)
                    ).fetchone()
                    report["owner_partner_status"] = owner[0] if owner else "no-row"
                else:
                    report["owner_partner_status"] = "legacy-schema"
            else:
                report["owner_partner_status"] = "table-not-created"
    else:
        report["sqlite_integrity"] = "not-created"
        report["partners_table"] = False
    return report


if __name__ == "__main__":
    try:
        print(json.dumps(check(), ensure_ascii=False, indent=2))
    except (OSError, sqlite3.Error) as error:
        print(json.dumps({"preflight_error": type(error).__name__}))
        sys.exit(1)
