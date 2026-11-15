"""Small, independently usable Partners offer-management mode.

These are admin-managed *operational* states, never CRM banking approvals or
payment confirmation. All reads are Telegram-identity scoped.
"""
import re
import secrets
import time
from urllib.parse import urlsplit

from server import db

STAGES = {"assigned", "in_progress", "submitted", "completed", "rejected"}
OFFER_ID = re.compile(r"^manual_[0-9a-f]{20}$")


def schema(conn):
    if db.postgres_url():
        return
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_offers (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
        target_action TEXT NOT NULL, payout_rub INTEGER NOT NULL,
        hold_days INTEGER NOT NULL, instructions TEXT NOT NULL DEFAULT '',
        referral_url TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_assignments (
        telegram_id INTEGER NOT NULL REFERENCES users(id),
        offer_id TEXT NOT NULL REFERENCES manual_offers(id),
        stage TEXT NOT NULL DEFAULT 'assigned',
        note TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL,
        PRIMARY KEY(telegram_id,offer_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_manual_assignments_user ON manual_assignments(telegram_id)")


def _admin(conn, actor, owner_id):
    operator = db.require_staff(conn, actor, owner_id)
    if operator["role"] not in ("owner", "admin"):
        raise db.Problem(403, "Управление офферами доступно администратору")
    return operator


def _field(payload, name, max_length, *, required=True):
    value = payload.get(name)
    if not required and value is None:
        return ""
    if not isinstance(value, str) or len(value) > max_length or (required and not value.strip()):
        raise db.Problem(400, "Некорректное поле: " + name)
    return value.strip()


def _url(value):
    if not value:
        return ""
    if len(value) > 2048 or any(ord(c) < 32 or c == "\\" for c in value):
        raise db.Problem(400, "Некорректная ссылка")
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        _ = parsed.port
    except ValueError:
        raise db.Problem(400, "Допускается только безопасная HTTPS-ссылка") from None
    return value


def _offer(row):
    return {k: row[k] for k in ("id", "name", "category", "target_action", "payout_rub",
                                 "hold_days", "instructions", "referral_url", "active")}


def catalog(actor, owner_id):
    db.initialize()
    with db.transaction() as conn:
        _admin(conn, actor, owner_id)
        schema(conn)
        rows = conn.execute("SELECT * FROM manual_offers ORDER BY created_at DESC,id DESC LIMIT 300").fetchall()
        return {"offers": [_offer(row) for row in rows]}


def save_offer(actor, owner_id, data):
    name = _field(data, "name", 120)
    category = _field(data, "category", 80)
    target_action = _field(data, "target_action", 200)
    instructions = _field(data, "instructions", 2000, required=False)
    link = _url(_field(data, "referral_url", 2048, required=False))
    payout, hold = data.get("payout_rub"), data.get("hold_days")
    if type(payout) is not int or not 0 <= payout <= 10000000:
        raise db.Problem(400, "Некорректная оплата")
    if type(hold) is not int or not 0 <= hold <= 365:
        raise db.Problem(400, "Некорректный холд")
    offer_id = data.get("offer_id")
    if offer_id is not None and (not isinstance(offer_id, str) or not OFFER_ID.fullmatch(offer_id)):
        raise db.Problem(400, "Некорректный оффер")
    active = data.get("active", True)
    if type(active) is not bool:
        raise db.Problem(400, "Некорректная доступность")
    now = int(time.time())
    db.initialize()
    with db.transaction() as conn:
        staff = _admin(conn, actor, owner_id)
        if staff["role"] != "owner":
            raise db.Problem(403, "Изменять общий каталог может только владелец")
        schema(conn)
        if offer_id:
            if not conn.execute("SELECT 1 FROM manual_offers WHERE id=?", (offer_id,)).fetchone():
                raise db.Problem(404, "Оффер не найден")
            conn.execute("UPDATE manual_offers SET name=?,category=?,target_action=?,payout_rub=?,hold_days=?,instructions=?,referral_url=?,active=?,updated_at=? WHERE id=?",
                         (name, category, target_action, payout, hold, instructions, link, int(active), now, offer_id))
        else:
            offer_id = "manual_" + secrets.token_hex(10)
            conn.execute("INSERT INTO manual_offers(id,name,category,target_action,payout_rub,hold_days,instructions,referral_url,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (offer_id, name, category, target_action, payout, hold, instructions, link, int(active), now, now))
        db.audit(conn, actor, "manual_offer_save", None, offer_id)
        return {"offer_id": offer_id}


def _participant(conn, staff, user_id):
    if type(user_id) is not int or user_id <= 0:
        raise db.Problem(400, "Некорректный Telegram ID")
    target = db.get_user(conn, user_id)
    db.permitted_target(conn, staff, target)
    if target["role"] not in ("lead", "referrer"):
        raise db.Problem(403, "Назначение доступно только участнику")
    return target


def assignment(actor, owner_id, data):
    user_id, offer_id = data.get("user_id"), data.get("offer_id")
    if not isinstance(offer_id, str) or not OFFER_ID.fullmatch(offer_id):
        raise db.Problem(400, "Некорректный оффер")
    stage = data.get("stage", "assigned")
    if stage not in STAGES:
        raise db.Problem(400, "Некорректный статус")
    note = _field(data, "note", 300, required=False)
    enabled = data.get("enabled", True)
    if type(enabled) is not bool:
        raise db.Problem(400, "Некорректное назначение")
    db.initialize()
    with db.transaction() as conn:
        staff = _admin(conn, actor, owner_id)
        schema(conn)
        target = _participant(conn, staff, user_id)
        if target["status"] != "active":
            raise db.Problem(409, "Сначала одобрите участника")
        offer = conn.execute("SELECT active FROM manual_offers WHERE id=?", (offer_id,)).fetchone()
        if not offer:
            raise db.Problem(404, "Оффер не найден")
        if enabled and not offer["active"]:
            raise db.Problem(409, "Оффер отключён")
        now = int(time.time())
        if enabled:
            conn.execute("INSERT INTO manual_assignments(telegram_id,offer_id,stage,note,updated_at) VALUES(?,?,?,?,?) "
                         "ON CONFLICT(telegram_id,offer_id) DO UPDATE SET stage=excluded.stage,note=excluded.note,updated_at=excluded.updated_at",
                         (user_id, offer_id, stage, note, now))
        else:
            conn.execute("DELETE FROM manual_assignments WHERE telegram_id=? AND offer_id=?", (user_id, offer_id))
        db.audit(conn, actor, "manual_assignment", user_id, f"offer={offer_id};stage={stage if enabled else 'removed'}")
        return {"changed": True}


def overview(user_id, owner_id, *, for_admin=None):
    db.initialize()
    with db.transaction() as conn:
        schema(conn)
        if for_admin is not None:
            staff = _admin(conn, for_admin, owner_id)
            _participant(conn, staff, user_id)
        else:
            user = db.get_user(conn, user_id)
            if not user or user["status"] != "active" or (user["consent_at"] is None and user["role"] != "owner"):
                return {"offers": [], "statistics": {"total": 0, "completed": 0, "in_progress": 0}}
        rows = conn.execute("SELECT o.*,a.stage,a.note,a.updated_at AS status_updated_at FROM manual_assignments a "
                            "JOIN manual_offers o ON o.id=a.offer_id WHERE a.telegram_id=? "
                            "ORDER BY a.updated_at DESC,o.id", (user_id,)).fetchall()
        offers = [{**_offer(row), "stage": row["stage"], "note": row["note"], "status_updated_at": row["status_updated_at"]}
                  for row in rows if for_admin is not None or row["active"]]
        return {"offers": offers, "statistics": {"total": len(offers),
                "completed": sum(row["stage"] == "completed" for row in offers),
                "in_progress": sum(row["stage"] in ("in_progress", "submitted") for row in offers)}}
