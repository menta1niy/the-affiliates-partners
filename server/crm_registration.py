"""Retryable CRM lead registration from the transactional Partners outbox.

Run periodically with `python -m server.crm_registration`. The CRM must send
a separately authenticated lead.bound event to attach its ID to Telegram.
"""
import json
import os
import time
import urllib.error
import urllib.request
from uuid import UUID

from server import db, integration


def endpoint():
    base = os.environ.get("PARTNERS_CRM_BASE_URL", "").rstrip("/")
    workspace = os.environ.get("PARTNERS_CRM_WORKSPACE_ID", "")
    if not base.startswith("https://") or not base.split("/", 3)[2] or not workspace:
        raise integration.BridgeError("CRM endpoint is not configured")
    try:
        UUID(workspace)
    except ValueError as exc:
        raise integration.BridgeError("Invalid CRM workspace ID") from exc
    return f"{base}/api/v1/workspaces/{workspace}/integrations/partners/leads"


def submit(payload, url, *, opener=urllib.request.urlopen, now=None):
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not 0 < len(raw) <= integration.MAX_BODY:
        raise integration.BridgeError("Invalid CRM registration payload size")
    timestamp = int(time.time() if now is None else now)
    request = urllib.request.Request(url, raw, {
        "Content-Type": "application/json; charset=utf-8",
        "X-TA-Timestamp": str(timestamp),
        "X-TA-Signature": integration.signature(raw, timestamp, integration.secret()),
    }, method="POST")
    try:
        with opener(request, timeout=8) as response:
            result = response.read(integration.MAX_BODY + 1)
            if response.status < 200 or response.status >= 300 or len(result) > integration.MAX_BODY:
                raise integration.BridgeError("CRM registration rejected")
            body = json.loads(result)
            crm_id = body.get("id") if isinstance(body, dict) else None
            if not isinstance(crm_id, str) or not crm_id or len(crm_id) > 128:
                raise integration.BridgeError("CRM response missing lead ID")
            return crm_id
    except (urllib.error.URLError, TimeoutError, ValueError, UnicodeError) as exc:
        raise integration.BridgeError("CRM registration transport/response failed") from exc


def dispatch_once(*, sender=None, now=None, batch_size=30):
    """Claim jobs briefly, send without holding DB locks, retry failures."""
    url = endpoint()
    sender = submit if sender is None else sender
    now = int(time.time() if now is None else now)
    db.initialize()
    with db.transaction() as conn:
        rows = conn.execute("SELECT telegram_id,payload,attempts FROM crm_registration_outbox "
                            "WHERE delivered_at IS NULL AND next_attempt_at<=? "
                            "ORDER BY created_at,telegram_id LIMIT ?", (now, batch_size)).fetchall()
        jobs = [dict(row) for row in rows]
        for job in jobs:
            conn.execute("UPDATE crm_registration_outbox SET next_attempt_at=? WHERE telegram_id=? AND delivered_at IS NULL",
                         (now + 90, job["telegram_id"]))
    count = 0
    for job in jobs:
        try:
            crm_id = sender(json.loads(job["payload"]), url)
            if not isinstance(crm_id, str) or not crm_id or len(crm_id) > 128:
                raise integration.BridgeError("CRM response missing lead ID")
        except Exception as exc:
            attempts = job["attempts"] + 1
            with db.transaction() as conn:
                conn.execute("UPDATE crm_registration_outbox SET attempts=?,next_attempt_at=?,last_error=? "
                             "WHERE telegram_id=? AND delivered_at IS NULL",
                             (attempts, now + min(3600, 30 * 2 ** min(attempts, 7)), type(exc).__name__[:100], job["telegram_id"]))
            continue
        with db.transaction() as conn:
            conn.execute("UPDATE crm_registration_outbox SET delivered_at=?,crm_lead_id=?,attempts=attempts+1,last_error='' "
                         "WHERE telegram_id=? AND delivered_at IS NULL", (now, crm_id, job["telegram_id"]))
        count += 1
    return {"claimed": len(jobs), "delivered": count, "failed": len(jobs) - count}


if __name__ == "__main__":
    print(json.dumps(dispatch_once()))
