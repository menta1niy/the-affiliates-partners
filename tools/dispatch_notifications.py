"""Retry durable Telegram notifications without blocking registrations.

This command is intentionally independent of the webhook handler. Telegram
messages may be delivered more than once if the network fails after delivery
but before the database acknowledges the send (at-least-once semantics).
"""
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from contextlib import closing

from server.db import database_path, initialize
from server.settings import bot_token


def deliver(chat_id, message, token):
    request = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.load(response)
    return payload.get("ok") is True


def dispatch():
    token = bot_token()
    if not token:
        print("Cannot dispatch: Telegram token not configured")
        return 2
    initialize()
    path = database_path()
    try:
        with closing(sqlite3.connect(str(path), timeout=15)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=15000")
            rows = conn.execute(
                "SELECT id,chat_id,text,attempts FROM notifications_outbox "
                "WHERE sent_at IS NULL AND next_attempt_at<=? ORDER BY id ASC LIMIT 10",
                (int(time.time()),),
            ).fetchall()
            for item in rows:
                conn.execute(
                    "UPDATE notifications_outbox SET attempts=attempts+1 WHERE id=? AND sent_at IS NULL",
                    (item["id"],),
                )
                conn.commit()
                try:
                    if not deliver(item["chat_id"], item["text"], token):
                        raise RuntimeError("Telegram rejected notification")
                except urllib.error.HTTPError as exc:
                    # NEVER log exc.url: it embeds our secret bot token.
                    detail = "HTTP_" + str(exc.code)
                except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
                    detail = type(exc).__name__
                else:
                    detail = ""
                if detail:
                    # Keep retrying indefinitely, but after repeated failures
                    # back off to at most once per hour.
                    delay = min(60 * (2 ** min(item["attempts"], 6)), 3600)
                    conn.execute(
                        "UPDATE notifications_outbox SET last_error=?,next_attempt_at=? WHERE id=?",
                        (detail, int(time.time()) + delay, item["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE notifications_outbox SET sent_at=?,last_error='' WHERE id=?",
                        (int(time.time()), item["id"]),
                    )
                conn.commit()
                print("Notification", item["id"], "delivered" if not detail else detail)
    except sqlite3.OperationalError as exc:
        # This command is also used during provisioning before the table exists.
        print("Outbox unavailable:", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(dispatch())
