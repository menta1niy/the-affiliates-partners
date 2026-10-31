"""Retry signed, unverified participant action reports to CRM without changing CRM stages."""
import json
import time
from datetime import UTC, datetime
import urllib.error
import urllib.request

from server import crm_registration, db, integration, tasks


def endpoint():
    return crm_registration.endpoint().rsplit("/leads", 1)[0] + "/task-reports"


def submit(event, url, *, opener=urllib.request.urlopen, now=None):
    if event.get("type") != "participant.task.reported":
        raise integration.BridgeError("Unexpected task report type")
    # The CRM contract is a strict report record. Keep the transport event
    # identifier and Telegram identity internal to the trusted outbox.
    payload = {key: event[key] for key in ("report_id", "crm_lead_id", "offer_id", "action", "note")}
    payload["created_at"] = datetime.fromtimestamp(event["created_at"], UTC).isoformat()
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if not 0 < len(raw) <= integration.MAX_BODY:
        raise integration.BridgeError("Invalid task report size")
    timestamp = int(time.time() if now is None else now)
    request = urllib.request.Request(url, raw, {
        "Content-Type": "application/json; charset=utf-8",
        "X-TA-Timestamp": str(timestamp),
        "X-TA-Signature": integration.signature(raw, timestamp, integration.secret()),
        "X-TA-Event-ID": event["event_id"],
    }, method="POST")
    try:
        with opener(request, timeout=8) as response:
            if not 200 <= response.status < 300 or len(response.read(integration.MAX_BODY + 1)) > integration.MAX_BODY:
                raise integration.BridgeError("CRM task report rejected")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise integration.BridgeError("CRM task report transport failed") from exc


def dispatch_once(*, sender=None, now=None, batch_size=30):
    url = endpoint()
    sender = submit if sender is None else sender
    now = int(time.time() if now is None else now)
    db.initialize()
    with db.transaction() as conn:
        tasks._schema(conn)
        rows = conn.execute("SELECT report_id,payload,attempts FROM participant_task_report_outbox "
                            "WHERE delivered_at IS NULL AND next_attempt_at<=? "
                            "ORDER BY created_at,report_id LIMIT ?", (now,batch_size)).fetchall()
        jobs = [dict(row) for row in rows]
        for job in jobs:
            conn.execute("UPDATE participant_task_report_outbox SET next_attempt_at=? "
                         "WHERE report_id=? AND delivered_at IS NULL", (now+90,job["report_id"]))
    delivered = 0
    for job in jobs:
        try:
            sender(json.loads(job["payload"]), url)
        except Exception as exc:
            attempts = job["attempts"] + 1
            with db.transaction() as conn:
                conn.execute("UPDATE participant_task_report_outbox SET attempts=?,next_attempt_at=?,last_error=? "
                             "WHERE report_id=? AND delivered_at IS NULL",
                             (attempts,now+min(3600,30*2**min(attempts,7)),type(exc).__name__[:100],job["report_id"]))
            continue
        with db.transaction() as conn:
            conn.execute("UPDATE participant_task_report_outbox SET delivered_at=?,attempts=attempts+1,last_error='' "
                         "WHERE report_id=? AND delivered_at IS NULL",(now,job["report_id"]))
        delivered += 1
    return {"claimed":len(jobs),"delivered":delivered,"failed":len(jobs)-delivered}


if __name__ == "__main__":
    print(json.dumps(dispatch_once()))
