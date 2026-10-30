"""Restricted, opt-in CRM offer ingestion. No CRM cookies or private finance fields."""
from uuid import UUID


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
        if not all(isinstance(v, str) and 0 < len(v.strip()) <= 180 for v in (name, category, goal)):
            raise ValueError("Invalid public offer fields")
        if type(item["is_active"]) is not bool:
            raise ValueError("Invalid active flag")
        prepared.append(("crm-" + remote_id, name.strip(), category.strip(), goal.strip(), item["is_active"]))
    return prepared


def apply_feed(conn, prepared, now):
    count = 0
    for offer_id, name, category, goal, active in prepared:
        current = conn.execute("SELECT status FROM offers WHERE id=?", (offer_id,)).fetchone()
        status = ("draft" if active else "paused") if current is None else (
            current[0] if active else "paused"
        )
        # Rate and hold cannot be inferred from CRM's source schema.
        # Zero is an internal 'not provided' sentinel; UI displays 'not specified'.
        conn.execute("""INSERT INTO offers(id,name,type,rate,goal,hold,description,status,updated_at)
            VALUES(?,?,?,0,?,0,'Источник: CRM. Выплата и холд не указаны.',?,?)
            ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,type=excluded.type,goal=excluded.goal,
            status=excluded.status,updated_at=excluded.updated_at""",
            (offer_id, name, category, goal, status, now))
        count += 1
    return count
