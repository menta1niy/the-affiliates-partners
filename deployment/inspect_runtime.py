#!/usr/bin/env python3
"""Read-only Linux production process comparison. Prints no secret values.

Run on the VPS as an authorized operator with access to both /proc environments.
No changes to systemd, SQLite, Telegram, or project files.
"""
import json
import os
import subprocess
from pathlib import Path

SERVICES = (
    "the-affiliates-partners-api.service",
    "the-affiliates-partners-bot.service",
)
KEYS = ("PARTNERS_DB_PATH", "TELEGRAM_BOT_TOKEN", "MINI_APP_URL",
        "CRM_WORKSPACE_ID", "CRM_FEED_TOKEN")


def properties(service):
    result = subprocess.run(
        ["systemctl", "show", service, "--property=MainPID,ActiveState,WorkingDirectory"],
        capture_output=True, text=True, timeout=8, check=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def process_env(pid):
    raw = Path("/proc") / str(pid) / "environ"
    values = {}
    for field in raw.read_bytes().split(b"\0"):
        if b"=" in field:
            key, value = field.split(b"=", 1)
            name = key.decode("utf-8", "replace")
            if name in KEYS:
                values[name] = value
    return values


def effective_env(pid, cwd):
    """Match config.load_local_env: process settings take precedence over .env.local.

    Python's os.environ updates do not reliably appear in /proc/PID/environ on
    Linux. Both services load the local file after process startup.
    """
    values = process_env(pid)
    local_env = cwd / ".env.local"
    if not local_env.is_file():
        return values
    for raw in local_env.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in KEYS:
            values.setdefault(key, value.strip().strip('"').strip("'").encode())
    return values


def inspect():
    units, environments, database_locations = {}, {}, {}
    for service in SERVICES:
        info = properties(service)
        pid = int(info.get("MainPID") or "0")
        if pid <= 0:
            units[service] = {"state": info.get("ActiveState"), "running": False}
            continue
        cwd = Path(info.get("WorkingDirectory") or "/")
        env = effective_env(pid, cwd)
        default_db = cwd / "server" / "partners.sqlite3"
        location = Path(os.fsdecode(env.get("PARTNERS_DB_PATH", b"")) or default_db).resolve()
        metadata = location.stat() if location.is_file() else None
        units[service] = {
            "state": info.get("ActiveState"),
            "running": True,
            "working_directory": str(cwd),
            "db_path": str(location),
            "db_exists": metadata is not None,
            "db_identity": [metadata.st_dev, metadata.st_ino] if metadata else None,
            "telegram_token_present": bool(env.get("TELEGRAM_BOT_TOKEN")),
            "mini_app_url_present": bool(env.get("MINI_APP_URL")),
            "crm_workspace_present": bool(env.get("CRM_WORKSPACE_ID")),
        }
        environments[service] = env
        database_locations[service] = location
    if len(environments) == 2:
        first, second = (environments[name] for name in SERVICES)
        units["comparisons"] = {
            "same_db_path": database_locations[SERVICES[0]] == database_locations[SERVICES[1]],
            "same_db_file": units[SERVICES[0]]["db_identity"] is not None
                and units[SERVICES[0]]["db_identity"] == units[SERVICES[1]]["db_identity"],
            "same_telegram_token": bool(first.get("TELEGRAM_BOT_TOKEN"))
                and first.get("TELEGRAM_BOT_TOKEN") == second.get("TELEGRAM_BOT_TOKEN"),
            "same_mini_app_url": bool(first.get("MINI_APP_URL"))
                and first.get("MINI_APP_URL") == second.get("MINI_APP_URL"),
        }
    return units


if __name__ == "__main__":
    try:
        print(json.dumps(inspect(), ensure_ascii=False, indent=2))
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print(json.dumps({"error_type": type(error).__name__,
                          "message": "Requires authorized read access to running service environments"}))
        raise SystemExit(1)
