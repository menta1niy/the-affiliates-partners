"""Optional read-only CRM PostgreSQL -> Partners offer publisher.

Run with a dedicated SELECT-only PostgreSQL account. No CRM application code,
cookies, owner sessions, financial fields, or schema changes are involved.
Dry-run by default. --send is an explicit opt-in.
"""
import argparse
import json
import os
import sys
import urllib.request
from urllib.parse import urlparse
from uuid import UUID


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
            "is_active": bool(row["is_active"]),
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
                SELECT id, workspace_id, name, offer_type, target_action, is_active
                FROM offers
                WHERE workspace_id = :workspace AND archived_at IS NULL
                ORDER BY id
            """), {"workspace": str(workspace_id)}).mappings().all()
            return sanitized_offers(rows, workspace_id)
    finally:
        engine.dispose()


def publish(endpoint, token, workspace_id, offers):
    address = urlparse(endpoint)
    if address.scheme != "https" or address.username or address.password or not address.netloc:
        raise ValueError("Publisher requires an HTTPS endpoint without embedded credentials")
    if len(token) < 32:
        raise ValueError("Configured CRM feed token is missing or too short")
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
    for items in batches:
        batch = {"workspace_id": str(workspace_id), "offers": items}
        req = urllib.request.Request(
            endpoint, data=json.dumps(batch).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "X-CRM-Feed-Token": token},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.load(response)
            if response.status != 200 or not result.get("ok") or result.get("imported") != len(batch["offers"]):
                raise RuntimeError("CRM feed did not acknowledge the entire batch")
        total += len(batch["offers"])
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only CRM offers bridge (default: dry run)")
    parser.add_argument("--send", action="store_true", help="Explicitly POST to Partners")
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
    sent = publish(endpoint, os.environ["CRM_FEED_TOKEN"], workspace_id, rows)
    print(json.dumps({"mode": "sent", "offers": sent, "workspace_id": str(workspace_id)}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, RuntimeError) as error:
        print(f"CRM publishing refused: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
