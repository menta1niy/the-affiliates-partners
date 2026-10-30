"""Explicit owner-approved CRM blogger association; never infer from a username."""
from uuid import UUID


def normalize_uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid CRM blogger UUID") from None


def schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS crm_partner_links (
        telegram_id INTEGER PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        blogger_id TEXT NOT NULL,
        verified INTEGER NOT NULL DEFAULT 0,
        confirmed_at INTEGER NOT NULL DEFAULT 0,
        UNIQUE(workspace_id,blogger_id)
    )""")


def owner_assign(conn, telegram_id, workspace, blogger_id):
    schema(conn)
    uid = normalize_uuid(blogger_id)
    partner = conn.execute(
        "SELECT phone,status FROM partners WHERE telegram_id=?", (telegram_id,)
    ).fetchone()
    if not partner or not partner[0] or partner[1] != "active":
        raise ValueError("Only approved partners with verified contact may be linked")
    conn.execute("""INSERT INTO crm_partner_links(telegram_id,workspace_id,blogger_id,verified,confirmed_at)
        VALUES(?,?,?,0,0) ON CONFLICT(telegram_id) DO UPDATE SET
        workspace_id=excluded.workspace_id,blogger_id=excluded.blogger_id,
        verified=CASE WHEN crm_partner_links.workspace_id=excluded.workspace_id
                      AND crm_partner_links.blogger_id=excluded.blogger_id
                      THEN crm_partner_links.verified ELSE 0 END,
        confirmed_at=CASE WHEN crm_partner_links.workspace_id=excluded.workspace_id
                      AND crm_partner_links.blogger_id=excluded.blogger_id
                      THEN crm_partner_links.confirmed_at ELSE 0 END""",
        (telegram_id,workspace,uid))
    return uid


def attest(conn, workspace, blogger_ids, now):
    schema(conn)
    if not isinstance(blogger_ids, list) or len(blogger_ids) > 10000:
        raise ValueError("Invalid CRM blogger attestation")
    verified = {normalize_uuid(x) for x in blogger_ids}
    # The bridge only confirms a manually chosen UUID exists in the scoped
    # CRM database; it cannot create a partner or confer CRM permissions.
    changed = 0
    rows = conn.execute(
        "SELECT telegram_id,blogger_id FROM crm_partner_links WHERE workspace_id=?",
        (workspace,)
    ).fetchall()
    for telegram_id, blogger_id in rows:
        allowed = blogger_id in verified
        conn.execute(
            "UPDATE crm_partner_links SET verified=?,confirmed_at=? WHERE telegram_id=?",
            (int(allowed),now if allowed else 0,telegram_id)
        )
        changed += int(allowed)
    return changed
