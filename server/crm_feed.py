"""Restricted, opt-in CRM offer ingestion. No CRM cookies or private finance fields."""
from uuid import UUID

CRM_CATEGORIES = {
    "debit": "БАНКИ / ДЕБЕТОВЫЕ КАРТЫ",
    "credit": "БАНКИ / КРЕДИТЫ",
    "rko": "БАНКИ / РКО",
    "microloan": "МФО / ЗАЙМЫ",
    "invest": "ИНВЕСТИЦИИ",
    "job": "РАБОТА",
    "betting": "ДРУГОЕ / СПОРТ",
    "other": "ДРУГОЕ",
}


def normalize_feed(payload, configured_workspace):
    if not isinstance(payload, dict) or payload.get("workspace_id") != configured_workspace:
        raise ValueError("Workspace is not permitted")
    rows = payload.get("offers")
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("Invalid offer collection")
    prepared = []
    unique = set()
    for item in rows:
        if not isinstance(item, dict) or set(item) != {
            "id", "name", "offer_type", "target_action", "is_active"
        }:
            raise ValueError("Only explicitly allowed public offer fields are accepted")
        try:
            remote_id = str(UUID(item["id"]))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid CRM offer UUID") from None
        if remote_id in unique:
            raise ValueError("Repeated CRM offer")
        unique.add(remote_id)
        name, category, goal = (item[key] for key in ("name", "offer_type", "target_action"))
        # CRM name is VARCHAR(180), offer_type is a compact enum, but
        # target_action is TEXT. Reject unreasonable payloads without
        # truncating a legitimate longer target-action description.
        if (not isinstance(name, str) or not 0 < len(name.strip()) <= 180
                or not isinstance(category, str) or not 0 < len(category.strip()) <= 24
                or not isinstance(goal, str) or not 0 < len(goal.strip()) <= 1000):
            raise ValueError("Invalid public offer fields")
        if type(item["is_active"]) is not bool:
            raise ValueError("Invalid active flag")
        prepared.append(("crm-" + remote_id, name.strip(),
                         CRM_CATEGORIES.get(category.strip(), category.strip()),
                         goal.strip(), item["is_active"]))
    return prepared


def apply_feed(conn, prepared, now):
    conn.execute("""CREATE TABLE IF NOT EXISTS crm_offer_source (
        offer_id TEXT PRIMARY KEY, source_active INTEGER NOT NULL,
        last_seen INTEGER NOT NULL)""")
    count = 0
    for offer_id, name, category, goal, active in prepared:
        current = conn.execute("SELECT status FROM offers WHERE id=?", (offer_id,)).fetchone()
        # Moderation remains a local decision; upstream reactivation must never
        # auto-approve an offer. Explicitly inactive CRM records stay hidden.
        # Source availability lives in crm_offer_source; do not overwrite
        # the owner's moderation decision on inactivity.
        status = "draft" if current is None else current[0]
        # Rate and hold cannot be inferred from CRM's source schema.
        # Zero is an internal 'not provided' sentinel; UI displays 'not specified'.
        conn.execute("""INSERT INTO offers(id,name,type,rate,goal,hold,description,status,updated_at)
            VALUES(?,?,?,0,?,0,'Источник: CRM. Выплата и холд не указаны.',?,?)
            ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,type=excluded.type,goal=excluded.goal,
            status=excluded.status,updated_at=excluded.updated_at""",
            (offer_id, name, category, goal, status, now))
        conn.execute("""INSERT INTO crm_offer_source(offer_id,source_active,last_seen)
            VALUES(?,?,?) ON CONFLICT(offer_id) DO UPDATE SET
            source_active=excluded.source_active,last_seen=excluded.last_seen""",
            (offer_id, int(active), now))
        count += 1
    return count


def finalize_snapshot(conn, workspace_id, offer_ids, now):
    """Reconcile only after every feed batch was acknowledged.

    The publisher supplies the complete set of source UUIDs. A failed batch
    never calls this operation, so incomplete transfers cannot hide offers.
    """
    if not isinstance(offer_ids, list) or len(offer_ids) > 300:
        raise ValueError("Invalid snapshot manifest")
    expected = set()
    for value in offer_ids:
        try:
            canonical = str(UUID(value))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid snapshot UUID") from None
        if canonical in expected:
            raise ValueError("Duplicate snapshot UUID")
        expected.add(canonical)
    rows = conn.execute("SELECT id FROM offers WHERE id LIKE 'crm-%'").fetchall()
    stale = [row[0] for row in rows if row[0][4:] not in expected]
    for local_id in stale:
        conn.execute("UPDATE crm_offer_source SET source_active=0 WHERE offer_id=?", (local_id,))
    return len(stale)
