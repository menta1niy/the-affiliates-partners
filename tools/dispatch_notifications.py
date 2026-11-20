"""Retry durable Telegram notifications without blocking registrations.

This command is intentionally independent of the webhook handler. Telegram
messages may be delivered more than once if the network fails after delivery
but before the database acknowledges the send (at-least-once semantics).
"""
import json
import sys
import time
import urllib.error
import urllib.request

from server import db
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
    try:
        db.initialize()
        processed = set()
        for _ in range(10):
            # Claim in a short transaction, not while performing network I/O.
            # db.transaction serializes claims for SQLite and PostgreSQL alike.
            with db.transaction() as conn:
                now = int(time.time())
                params = (now, *sorted(processed))
                exclusion = (" AND id NOT IN (" + ",".join("?" for _ in processed) + ")") if processed else ""
                item = conn.execute(
                    "SELECT id,chat_id,text,attempts FROM notifications_outbox "
                    "WHERE sent_at IS NULL AND next_attempt_at<=?" + exclusion +
                    " ORDER BY id ASC LIMIT 1", params,
                ).fetchone()
                if not item:
                    break
                item = dict(zip(item.keys(), item))
                processed.add(item["id"])
                # 120-second reservation exceeds the 8-second request timeout.
                lease_until = now + 120
                conn.execute("UPDATE notifications_outbox SET attempts=attempts+1,"
                             "next_attempt_at=? WHERE id=? AND sent_at IS NULL",
                             (lease_until, item["id"]))
            try:
                if not deliver(item["chat_id"], item["text"], token):
                    raise RuntimeError("Telegram rejected notification")
            except urllib.error.HTTPError as exc:
                # NEVER log the request URL: it embeds the secret bot token.
                detail = "HTTP_" + str(exc.code)
            except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
                detail = type(exc).__name__
            else:
                detail = ""
            with db.transaction() as conn:
                if detail:
                    delay = min(60 * (2 ** min(item["attempts"], 6)), 3600)
                    conn.execute("UPDATE notifications_outbox SET last_error=?,next_attempt_at=? "
                                 "WHERE id=? AND sent_at IS NULL AND next_attempt_at=?",
                                 (detail, int(time.time()) + delay, item["id"], lease_until))
                else:
                    conn.execute("UPDATE notifications_outbox SET sent_at=?,last_error='' "
                                 "WHERE id=? AND sent_at IS NULL AND next_attempt_at=?",
                                 (int(time.time()), item["id"], lease_until))
            print("Notification", item["id"], "delivered" if not detail else detail)
    except Exception as exc:
        # Do not print URLs, DSNs, or exception messages (may contain secrets).
        print("Outbox unavailable:", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(dispatch())
