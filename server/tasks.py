"""Participant action reports; only CRM may confirm a banking outcome."""
import json
import time
import uuid

from server import db


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS participant_task_reports (
        report_id TEXT PRIMARY KEY, telegram_id BIGINT NOT NULL,
        crm_lead_id TEXT NOT NULL, offer_id TEXT NOT NULL,
        action TEXT NOT NULL, note TEXT NOT NULL,
        created_at BIGINT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_task_reports_user ON participant_task_reports(telegram_id,created_at)")


def _assignment(conn, telegram_id, offer_id):
    return conn.execute("SELECT o.payload,b.crm_lead_id FROM crm_assigned_offers o "
                        "JOIN crm_lead_bindings b ON b.crm_lead_id=o.crm_lead_id "
                        "WHERE b.telegram_id=? AND o.offer_id=?", (telegram_id, offer_id)).fetchone()


def _active(conn, telegram_id):
    user = db.get_user(conn, telegram_id)
    return bool(user and user["status"] == "active" and user["consent_at"] is not None)


def list_tasks(telegram_id, owner_id):
    db.initialize()
    with db.transaction() as conn:
        _schema(conn)
        if not _active(conn, telegram_id):
            return {"tasks": [], "history": []}
        rows = conn.execute("SELECT o.payload FROM crm_assigned_offers o "
                            "JOIN crm_lead_bindings b ON b.crm_lead_id=o.crm_lead_id "
                            "WHERE b.telegram_id=? ORDER BY o.offer_id", (telegram_id,)).fetchall()
        history = conn.execute("SELECT report_id,offer_id,action,note,created_at "
                               "FROM participant_task_reports WHERE telegram_id=? "
                               "ORDER BY created_at DESC,report_id DESC LIMIT 100", (telegram_id,)).fetchall()
        return {"tasks": [json.loads(r["payload"]) for r in rows],
                "history": [dict(r) for r in history]}


def report_action(telegram_id, owner_id, offer_id, action, note):
    if not isinstance(offer_id, str) or not 1 <= len(offer_id) <= 128:
        raise db.Problem(400, "Некорректный идентификатор задания")
    if action not in ("opened", "started", "submitted"):
        raise db.Problem(400, "Некорректное действие")
    if not isinstance(note, str) or len(note) > 1000:
        raise db.Problem(400, "Комментарий слишком длинный")
    db.initialize()
    with db.transaction() as conn:
        _schema(conn)
        if not _active(conn, telegram_id):
            raise db.Problem(403, "Задания доступны только активному участнику")
        assigned = _assignment(conn, telegram_id, offer_id)
        if assigned is None:
            raise db.Problem(403, "Задание вам не назначено")
        report_id = str(uuid.uuid4())
        created_at = int(time.time())
        conn.execute("INSERT INTO participant_task_reports(report_id,telegram_id,crm_lead_id,offer_id,action,note,created_at) "
                     "VALUES(?,?,?,?,?,?,?)", (report_id,telegram_id,assigned["crm_lead_id"],offer_id,action,note.strip(),created_at))
        return {"report_id": report_id, "offer_id": offer_id, "action": action,
                "created_at": created_at, "status": "reported"}
