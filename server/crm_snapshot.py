"""Staged, atomic, replay-safe CRM snapshot protocol."""
import hashlib
import json
import time
from uuid import UUID
from crm_feed import apply_feed

TTL = 3600


def schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS crm_sync_runs (
      run_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, state TEXT NOT NULL,
      expected INTEGER NOT NULL, created_at INTEGER NOT NULL, finished_at INTEGER,
      digest TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS crm_sync_items (
      run_id TEXT NOT NULL, offer_id TEXT NOT NULL, payload TEXT NOT NULL,
      PRIMARY KEY(run_id,offer_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS crm_sync_state (
      workspace_id TEXT PRIMARY KEY, last_completed INTEGER NOT NULL DEFAULT 0)""")


def begin(conn, workspace, run_id, expected, now=None):
    now = int(time.time()) if now is None else now
    UUID(run_id)
    if type(expected) is not int or not 0 <= expected <= 100000:
        raise ValueError("Invalid expected count")
    schema(conn)
    conn.execute("DELETE FROM crm_sync_items WHERE run_id IN "
                 "(SELECT run_id FROM crm_sync_runs WHERE state='pending' AND created_at<?)", (now-TTL,))
    conn.execute("UPDATE crm_sync_runs SET state='expired' WHERE state='pending' AND created_at<?", (now-TTL,))
    existing = conn.execute("SELECT workspace_id,state,expected FROM crm_sync_runs WHERE run_id=?", (run_id,)).fetchone()
    if existing:
        if existing[0] != workspace or existing[2] != expected or existing[1] == 'expired':
            raise ValueError("Snapshot ID conflict or expired")
        return existing[1]
    # New runs are serialized by a monotonic server-side creation order.
    conn.execute("INSERT INTO crm_sync_runs(run_id,workspace_id,state,expected,created_at) "
                 "VALUES(?,?,'pending',?,?)", (run_id,workspace,expected,now))
    return 'pending'


def batch(conn, workspace, run_id, prepared, now=None):
    now = int(time.time()) if now is None else now
    schema(conn)
    row = conn.execute("SELECT state,created_at FROM crm_sync_runs WHERE run_id=? AND workspace_id=?",
                       (run_id, workspace)).fetchone()
    if not row or row[0] != 'pending' or now-row[1] > TTL:
        raise ValueError("Snapshot is absent, completed or expired")
    for offer_id, name, category, goal, active in prepared:
        data = json.dumps([offer_id,name,category,goal,active],ensure_ascii=False)
        current = conn.execute("SELECT payload FROM crm_sync_items WHERE run_id=? AND offer_id=?",
                               (run_id, offer_id)).fetchone()
        if current and current[0] != data:
            raise ValueError("Conflicting replay of offer")
        conn.execute("INSERT OR IGNORE INTO crm_sync_items(run_id,offer_id,payload) VALUES(?,?,?)",
                     (run_id,offer_id,data))
    return conn.execute("SELECT count(*) FROM crm_sync_items WHERE run_id=?", (run_id,)).fetchone()[0]


def finalize(conn, workspace, run_id, digest, now=None):
    now = int(time.time()) if now is None else now
    schema(conn)
    run = conn.execute("SELECT state,expected,created_at,digest FROM crm_sync_runs "
                       "WHERE run_id=? AND workspace_id=?", (run_id,workspace)).fetchone()
    if not run:
        raise ValueError("Unknown snapshot")
    if run[0] == 'complete':
        if digest != run[3]:
            raise ValueError("Conflicting snapshot replay")
        return 0
    if run[0] != 'pending' or now-run[2] > TTL:
        raise ValueError("Snapshot expired")
    newer = conn.execute("SELECT 1 FROM crm_sync_runs WHERE workspace_id=? AND "
                         "state='complete' AND rowid>(SELECT rowid FROM crm_sync_runs WHERE run_id=?) LIMIT 1",
                         (workspace,run_id)).fetchone()
    if newer:
        raise ValueError("Stale snapshot")
    entries = conn.execute("SELECT offer_id,payload FROM crm_sync_items WHERE run_id=? ORDER BY offer_id",
                           (run_id,)).fetchall()
    if len(entries) != run[1]:
        raise ValueError("Snapshot incomplete")
    calculated = hashlib.sha256("\n".join(p for _, p in entries).encode()).hexdigest()
    if digest != calculated:
        raise ValueError("Snapshot digest mismatch")
    prepared = [tuple(json.loads(payload)) for _,payload in entries]
    apply_feed(conn,prepared,now)
    present = {item[0] for item in prepared}
    # Scope to CRM source records; do not affect locally created offers.
    conn.execute("""CREATE TABLE IF NOT EXISTS crm_offer_source (
      offer_id TEXT PRIMARY KEY,source_active INTEGER NOT NULL,last_seen INTEGER NOT NULL)""")
    existing = conn.execute("SELECT offer_id FROM crm_offer_source").fetchall()
    stale = [id for (id,) in existing if id not in present]
    for offer_id in stale:
        conn.execute("UPDATE offers SET status='paused',updated_at=? WHERE id=?", (now,offer_id))
        conn.execute("UPDATE crm_offer_source SET source_active=0 WHERE offer_id=?", (offer_id,))
    conn.execute("UPDATE crm_sync_runs SET state='complete',finished_at=?,digest=? WHERE run_id=?",
                 (now,digest,run_id))
    conn.execute("DELETE FROM crm_sync_items WHERE run_id=?", (run_id,))
    return len(stale)
