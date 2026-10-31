"""Optional read-only CRM PostgreSQL -> Partners offer publisher.

Run with a dedicated SELECT-only PostgreSQL account. No CRM application code,
cookies, owner sessions, financial fields, or schema changes are involved.
Dry-run by default. --send is an explicit opt-in.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from uuid import UUID, uuid4
from crm_feed import normalize_feed


class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the CRM service key to a redirected host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_urlopen(request, timeout):
    return urllib.request.build_opener(NoCredentialRedirect()).open(request, timeout=timeout)


def sanitized_offers(records, workspace_id):
    """Project only known CRM Offer columns, never its economics."""
    result = []
    for row in records:
        if str(row["workspace_id"]) != str(workspace_id):
            raise ValueError("Cross-workspace source row")
        result.append({
            "id": str(UUID(str(row["id"]))),
            "name": str(row["name"]),
            "offer_type": str(row["offer_type"]),
            "target_action": str(row["target_action"]),
            "is_active": bool(row["is_active"]) and row.get("archived_at") is None,
        })
    return result


def load_crm_offers(database_url, workspace_id):
    try:
        from sqlalchemy import create_engine, text
    except ImportError as error:
        raise RuntimeError("Install the CRM backend's pinned SQLAlchemy and PostgreSQL driver") from error
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = connection.execute(text("""
                SELECT id, workspace_id, name, offer_type, target_action, is_active, archived_at
                FROM offers
                WHERE workspace_id = :workspace
                ORDER BY id
            """), {"workspace": str(workspace_id)}).mappings().all()
            return sanitized_offers(rows, workspace_id)
    finally:
        engine.dispose()


def publish(endpoint, token, workspace_id, offers, run_id=None):
    address = urlparse(endpoint)
    if address.scheme != "https" or address.username or address.password or not address.netloc:
        raise ValueError("Publisher requires an HTTPS endpoint without embedded credentials")
    if len(token) < 32:
        raise ValueError("Configured CRM feed token is missing or too short")
    run_id = str(UUID(run_id)) if run_id is not None else str(uuid4())
    def send(payload):
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
             headers={"Content-Type": "application/json", "X-CRM-Feed-Token": token})
        result = send_with_retry(req)
        if not result.get("ok"):
            raise RuntimeError("CRM snapshot request failed")
        return result
    try:
        result = send({"mode":"begin","workspace_id":str(workspace_id),"run_id":run_id,"expected":len(offers)})
    except Exception as error:
        raise RuntimeError(f"CRM run {run_id}: begin failed ({type(error).__name__}); retry with same --run-id") from None
    if result.get("state") not in ("pending", "complete"):
        raise RuntimeError(f"CRM run {run_id}: unexpected server state")
    completed = result["state"] == "complete"
    total = 0
    batches = []
    pending = []
    for item in offers:
        candidate = pending + [item]
        data = json.dumps({"workspace_id": str(workspace_id), "offers": candidate}).encode("utf-8")
        if len(candidate) > 100 or len(data) > 12000:
            if not pending:
                raise ValueError("Single CRM offer exceeds API request limit")
            batches.append(pending)
            pending = [item]
            if len(json.dumps({"workspace_id": str(workspace_id), "offers": pending}).encode("utf-8")) > 12000:
                raise ValueError("Single CRM offer exceeds API request limit")
        else:
            pending = candidate
    if pending:
        batches.append(pending)
    for items in ([] if completed else batches):
        try:
            result = send({"mode":"batch","workspace_id":str(workspace_id),"run_id":run_id,"offers":items})
        except Exception as error:
            raise RuntimeError(f"CRM run {run_id}: batch failed ({type(error).__name__}); retry with same --run-id") from None
        if result.get("received",0) < len(items):
            raise RuntimeError(f"CRM run {run_id}: batch not acknowledged; retry with same --run-id")
        total += len(items)
    normalized = normalize_feed({"workspace_id":str(workspace_id),"offers":[]}, str(workspace_id))
    # Apply the exact same canonical type projection used by the receiver.
    for item in offers:
        normalized += normalize_feed({"workspace_id":str(workspace_id),"offers":[item]},str(workspace_id))
    ordered = sorted(normalized, key=lambda item:item[0])
    digest = hashlib.sha256("\n".join(json.dumps(list(row),ensure_ascii=False) for row in ordered).encode()).hexdigest()
    try:
        send({"mode":"commit","workspace_id":str(workspace_id),"run_id":run_id,"digest":digest})
    except Exception as error:
        raise RuntimeError(f"CRM run {run_id}: commit unconfirmed ({type(error).__name__}); retry with same --run-id") from None
    return len(offers) if completed else total


def send_with_retry(request, attempts=3):
    for number in range(attempts):
        try:
            with safe_urlopen(request, timeout=15) as response:
                if response.status != 200:
                    raise RuntimeError("CRM feed unexpected response")
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504) or number == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if number == attempts - 1:
                raise
        time.sleep(min(2 ** number, 4))


def verify_partner_links(endpoint, token, database_url, workspace_id):
    """Attest owner-selected CRM blogger UUIDs using actual scoped CRM rows."""
    parsed = urlparse(endpoint)
    if (len(token) < 32 or parsed.scheme != "https" or not parsed.netloc
            or parsed.username or parsed.password
            or not parsed.path.endswith("/api/internal/crm/offers")):
        raise ValueError("Identity bridge requires HTTPS and a service credential")
    root = endpoint.rsplit("/", 1)[0]

    def call(url, body):
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-CRM-Feed-Token": token}, method="POST")
        return send_with_retry(request)

    pending = call(root + "/identity/requests", {"workspace_id": str(workspace_id)})
    if not isinstance(pending, dict) or not isinstance(pending.get("mappings"), list):
        raise RuntimeError("CRM identity request response invalid")
    mappings = pending["mappings"]
    for item in mappings:
        if (not isinstance(item, dict)
                or set(item) != {"telegram_id", "blogger_id", "mapping_version", "check_version"}
                or type(item["telegram_id"]) is not int):
            raise ValueError("Invalid CRM identity request mapping")
        UUID(item["mapping_version"])
        UUID(item["check_version"])
    requested = {str(UUID(item["blogger_id"])) for item in mappings}
    if len(requested) > 10000:
        raise ValueError("Too many identity requests")
    try:
        from sqlalchemy import create_engine, text
    except ImportError as error:
        raise RuntimeError("CRM backend SQLAlchemy required") from error
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = connection.execute(text("""
                SELECT id FROM bloggers WHERE workspace_id=:workspace AND archived_at IS NULL
            """), {"workspace": str(workspace_id)}).all()
            existing = [str(UUID(str(row[0]))) for row in rows if str(row[0]) in requested]
    finally:
        engine.dispose()
    found = set(existing)
    attestations = [{
        "telegram_id": item["telegram_id"],
        "blogger_id": str(UUID(item["blogger_id"])),
        "mapping_version": item["mapping_version"],
        "check_version": item["check_version"],
        "exists": str(UUID(item["blogger_id"])) in found
    } for item in mappings]
    result = call(root + "/identity", {"workspace_id": str(workspace_id), "attestations": attestations})
    if not result.get("ok"):
        raise RuntimeError("CRM identity attestation failed")
    return result.get("verified", 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only CRM offers bridge (default: dry run)")
    parser.add_argument("--send", action="store_true", help="Explicitly POST to Partners")
    parser.add_argument("--verify-links", action="store_true", help="Attest owner-approved CRM partner links")
    parser.add_argument("--run-id", help="Resume an interrupted snapshot with exactly the same source data")
    args = parser.parse_args(argv)
    workspace_id = UUID(os.environ["CRM_WORKSPACE_ID"])
    source = os.environ["CRM_READONLY_DATABASE_URL"]
    if not source.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")):
        raise ValueError("CRM source must be PostgreSQL")
    rows = load_crm_offers(source, workspace_id)
    if not args.send:
        print(json.dumps({"mode": "dry-run", "workspace_id": str(workspace_id),
                          "offers": len(rows), "fields": list(rows[0]) if rows else []}))
        return
    endpoint = os.environ["PARTNERS_CRM_FEED_URL"]
    sent = publish(endpoint, os.environ["CRM_FEED_TOKEN"], workspace_id, rows, run_id=args.run_id)
    verified = verify_partner_links(endpoint, os.environ["CRM_FEED_TOKEN"], source, workspace_id) if args.verify_links else None
    print(json.dumps({"mode": "sent", "offers": sent, "workspace_id": str(workspace_id),
                      "identity_links_verified": verified}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, RuntimeError) as error:
        print(f"CRM publishing refused: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
