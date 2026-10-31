"""Explicit administrative PostgreSQL schema preparation (never runs on app startup).

Usage: python -m database.prepare_schema --confirm-ddl
Requires PARTNERS_DATABASE_URL with a privileged migration credential.
"""
import argparse
import os

from database.postgres import initialize, validate_ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-ddl", action="store_true")
    args = parser.parse_args()
    if not args.confirm_ddl:
        parser.error("--confirm-ddl is required")
    url = os.environ.get("PARTNERS_DATABASE_URL", "").strip()
    if not url:
        parser.error("PARTNERS_DATABASE_URL is required")
    initialize(url)
    validate_ready(url)
    print("Partners schema prepared and verified")


if __name__ == "__main__":
    main()
