"""Explicit owner-approved CRM blogger association; never infer from a username."""
from uuid import UUID, uuid4


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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(crm_partner_links)")}
    if "mapping_version" not in columns:
        conn.execute("ALTER TABLE crm_partner_links ADD COLUMN mapping_version TEXT NOT NULL DEFAULT ''")
    if "check_version" not in columns:
        conn.execute("ALTER TABLE crm_partner_links ADD COLUMN check_version TEXT NOT NULL DEFAULT ''")
    # Upgrade old mappings in place; the next attestation must target a real
    # version instead of blindly accepting a stale pre-migration response.
    for (telegram_id,) in conn.execute(
        "SELECT telegram_id FROM crm_partner_links WHERE mapping_version=''"
    ).fetchall():
        conn.execute("UPDATE crm_partner_links SET mapping_version=?,verified=0,confirmed_at=0 "
                     "WHERE telegram_id=? AND mapping_version=''",
                     (str(uuid4()), telegram_id))


def owner_assign(conn, telegram_id, workspace, blogger_id):
    schema(conn)
    uid = normalize_uuid(blogger_id)
    partner = conn.execute(
        "SELECT phone,status FROM partners WHERE telegram_id=?", (telegram_id,)
    ).fetchone()
    if not partner or not partner[0] or partner[1] != "active":
        raise ValueError("Only approved partners with verified contact may be linked")
    version = str(uuid4())
    conn.execute("""INSERT INTO crm_partner_links(telegram_id,workspace_id,blogger_id,verified,confirmed_at,mapping_version)
        VALUES(?,?,?,0,0,?) ON CONFLICT(telegram_id) DO UPDATE SET
        workspace_id=excluded.workspace_id,blogger_id=excluded.blogger_id,
        verified=CASE WHEN crm_partner_links.workspace_id=excluded.workspace_id
                      AND crm_partner_links.blogger_id=excluded.blogger_id
                      THEN crm_partner_links.verified ELSE 0 END,
        confirmed_at=CASE WHEN crm_partner_links.workspace_id=excluded.workspace_id
                      AND crm_partner_links.blogger_id=excluded.blogger_id
                      THEN crm_partner_links.confirmed_at ELSE 0 END,
        mapping_version=CASE WHEN crm_partner_links.workspace_id=excluded.workspace_id
                      AND crm_partner_links.blogger_id=excluded.blogger_id
                      THEN crm_partner_links.mapping_version ELSE excluded.mapping_version END""",
        (telegram_id,workspace,uid,version))
    return uid


def attest(conn, workspace, attestations, now):
    schema(conn)
    if not isinstance(attestations, list) or len(attestations) > 10000:
        raise ValueError("Invalid CRM blogger attestation")
    decisions = {}
    for item in attestations:
        if not isinstance(item, dict) or set(item) != {"telegram_id","blogger_id","mapping_version","check_version","exists"}:
            raise ValueError("Invalid attestation record")
        if type(item["telegram_id"]) is not int or type(item["exists"]) is not bool:
            raise ValueError("Invalid attestation types")
        version = str(UUID(item["mapping_version"]))
        check_version = str(UUID(item["check_version"]))
        key = item["telegram_id"]
        if key in decisions:
            raise ValueError("Duplicate attestation")
        decisions[key] = (normalize_uuid(item["blogger_id"]),version,check_version,item["exists"])
    # The bridge only confirms a manually chosen UUID exists in the scoped
    # CRM database; it cannot create a partner or confer CRM permissions.
    changed = 0
    for telegram_id, (blogger_id,version,check_version,exists) in decisions.items():
        updated = conn.execute(
            """UPDATE crm_partner_links SET verified=?,confirmed_at=?,check_version=''
               WHERE telegram_id=? AND workspace_id=? AND blogger_id=?
                 AND mapping_version=? AND check_version=? AND check_version<>''""",
            (int(exists),now if exists else 0,telegram_id,workspace,blogger_id,version,check_version)
        ).rowcount
        changed += int(exists and updated > 0)
    return changed


def issue_checks(conn, workspace):
    """Latest read-only bridge query invalidates responses from older rounds."""
    schema(conn)
    rows = conn.execute(
        "SELECT telegram_id,blogger_id,mapping_version FROM crm_partner_links WHERE workspace_id=?",
        (workspace,)
    ).fetchall()
    result = []
    for telegram_id, blogger_id, mapping_version in rows:
        nonce = str(uuid4())
        conn.execute("UPDATE crm_partner_links SET check_version=? WHERE telegram_id=?",
                     (nonce,telegram_id))
        result.append(dict(telegram_id=telegram_id, blogger_id=blogger_id,
                           mapping_version=mapping_version,check_version=nonce))
    return result
