"""Durable, transactional partner identities, invitations and moderation."""
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path

from server.settings import ROOT

ROLES = {"owner", "admin", "staff", "referrer", "lead"}
STATUSES = {"invited", "pending", "active", "rejected", "blocked"}
CODE_PATTERN = re.compile(r"^(?:ag|ref)_[A-Za-z0-9_-]{8,48}$")


class Problem(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def database_path():
    return Path(os.environ.get("PARTNERS_DB_PATH") or ROOT / "data" / "partners.sqlite3")


@contextmanager
def transaction():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout=15000")
        if os.name != "nt":
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path), timeout=15)) as conn:
        if os.name != "nt":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL DEFAULT '',
          username TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'lead'
          CHECK(role IN ('owner','admin','staff','referrer','lead')),
          status TEXT NOT NULL DEFAULT 'pending'
          CHECK(status IN ('invited','pending','active','rejected','blocked')),
          agency_id INTEGER REFERENCES users(id), referrer_id INTEGER REFERENCES users(id),
          manager_id INTEGER REFERENCES users(id), registered_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL, decision_reason TEXT NOT NULL DEFAULT '',
          source TEXT CHECK(source IN ('agency','referral')), consent_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS invitations (
          code TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('agency','referral')),
          issuer_id INTEGER NOT NULL REFERENCES users(id), assignee_id INTEGER REFERENCES users(id),
          created_at INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          candidate_label TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS pending_starts (
          telegram_id INTEGER PRIMARY KEY, code TEXT NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telegram_updates (
          update_id INTEGER PRIMARY KEY, received_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER NOT NULL,
          action TEXT NOT NULL, target_id INTEGER, details TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notifications_outbox (
          id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE,
          chat_id INTEGER NOT NULL, text TEXT NOT NULL,
          created_at INTEGER NOT NULL, sent_at INTEGER,
          attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at INTEGER NOT NULL DEFAULT 0,
          last_error TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS ix_users_manager ON users(manager_id);
        CREATE INDEX IF NOT EXISTS ix_users_status ON users(status);
        CREATE INDEX IF NOT EXISTS ix_audit_created ON audit(id DESC);
        """)
        user_columns = {item[1] for item in conn.execute("PRAGMA table_info(users)")}
        if "source" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN source TEXT CHECK(source IN ('agency','referral'))")
        if "consent_at" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN consent_at INTEGER")
        invitation_columns = {item[1] for item in conn.execute("PRAGMA table_info(invitations)")}
        if "candidate_label" not in invitation_columns:
            conn.execute("ALTER TABLE invitations ADD COLUMN candidate_label TEXT NOT NULL DEFAULT ''")
        conn.commit()


def public_user(row):
    if row is None:
        return None
    return {key: row[key] for key in ("id", "first_name", "last_name", "username", "role", "status", "agency_id", "referrer_id", "manager_id", "source")}


def audit(conn, actor, action, target=None, details=""):
    conn.execute("INSERT INTO audit(actor_id,action,target_id,details,created_at) VALUES(?,?,?,?,?)",
                 (actor, action, target, details[:500], int(time.time())))


def enqueue(conn, event_key, recipient, message):
    conn.execute("INSERT OR IGNORE INTO notifications_outbox(event_key,chat_id,text,created_at) VALUES(?,?,?,?)",
                 (event_key, recipient, message[:1000], int(time.time())))


def get_user(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def ensure_owner(conn, owner_id):
    if not isinstance(owner_id, int) or owner_id <= 0:
        raise Problem(503, "Владелец не настроен")
    now = int(time.time())
    row = get_user(conn, owner_id)
    if row is None:
        conn.execute("INSERT INTO users(id,first_name,role,status,registered_at,updated_at) VALUES(?,?,'owner','active',?,?)",
                     (owner_id, "Владелец", now, now))
        audit(conn, owner_id, "owner_bootstrap", owner_id)
    elif row["role"] != "owner" or row["status"] != "active":
        conn.execute("UPDATE users SET role='owner',status='active',manager_id=NULL,updated_at=? WHERE id=?", (now, owner_id))
        audit(conn, owner_id, "owner_restore", owner_id)


def session(identity, owner_id):
    initialize()
    with transaction() as conn:
        ensure_owner(conn, owner_id)
        row = get_user(conn, identity["id"])
        if row is None:
            capture_signed_start(conn, identity)
        if row is not None:
            conn.execute("UPDATE users SET first_name=?,last_name=?,username=? WHERE id=?",
                         (identity["first_name"], identity["last_name"], identity["username"], identity["id"]))
            row = get_user(conn, identity["id"])
        return public_user(row) if row else {**identity, "role": "lead", "status": "invited", "agency_id": None, "referrer_id": None, "manager_id": None}


def register(identity, owner_id, invitation_code):
    initialize()
    with transaction() as conn:
        ensure_owner(conn, owner_id)
        existing = get_user(conn, identity["id"])
        if existing:
            return public_user(existing)
        capture_signed_start(conn, identity)
        pending = conn.execute("SELECT code FROM pending_starts WHERE telegram_id=?", (identity["id"],)).fetchone()
        if pending and invitation_code and invitation_code != pending["code"]:
            raise Problem(409, "Источник приглашения уже закреплён")
        code = pending["code"] if pending else invitation_code
        if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
            raise Problem(400, "Требуется действительное приглашение")
        invite = conn.execute("SELECT * FROM invitations WHERE code=? AND active=1", (code,)).fetchone()
        if invite is None:
            raise Problem(400, "Приглашение не найдено или отключено")
        issuer = get_user(conn, invite["issuer_id"])
        if issuer is None or issuer["status"] != "active":
            raise Problem(400, "Приглашение недействительно")
        if invite["kind"] == "referral" and issuer["id"] == identity["id"]:
            raise Problem(400, "Нельзя пригласить себя")
        agency = invite["assignee_id"] if invite["kind"] == "agency" else issuer["agency_id"]
        if invite["kind"] == "referral" and agency is None:
            agency = issuer["id"] if issuer["role"] in ("owner", "admin", "staff") else None
        referrer = issuer["id"] if invite["kind"] == "referral" else None
        now = int(time.time())
        manager = invite["assignee_id"] if invite["kind"] == "agency" and issuer["role"] in ("owner", "admin", "staff") else None
        conn.execute("""INSERT INTO users(id,first_name,last_name,username,role,agency_id,referrer_id,manager_id,registered_at,updated_at,source,consent_at)
                     VALUES(?,?,?,?,'lead',?,?,?,?,?,?,?)""", (identity["id"], identity["first_name"], identity["last_name"],
                                               identity["username"], agency, referrer, manager, now, now, invite["kind"], now))
        if invite["kind"] == "agency":
            # Agency introductions are individual, while referral links are reusable.
            conn.execute("UPDATE invitations SET active=0 WHERE code=?", (code,))
        conn.execute("DELETE FROM pending_starts WHERE telegram_id=?", (identity["id"],))
        audit(conn, identity["id"], "register", identity["id"], "source=" + invite["kind"])
        enqueue(conn, "register:" + str(identity["id"]), owner_id,
                "Новая заявка The Affiliates Partners: Telegram ID " + str(identity["id"]) + ". Статус: pending.")
        return public_user(get_user(conn, identity["id"]))


def invite(actor, owner_id, kind, assignee=None, candidate_label=""):
    if kind not in ("agency", "referral"):
        raise Problem(400, "Недопустимый тип приглашения")
    initialize()
    with transaction() as conn:
        ensure_owner(conn, owner_id)
        user = get_user(conn, actor)
        if not user or user["status"] != "active":
            raise Problem(403, "Профиль не подтверждён")
        if kind == "agency":
            if not isinstance(candidate_label, str) or len(candidate_label) > 120:
                raise Problem(400, "Неверная метка приглашения")
            candidate_label = candidate_label.strip()
            if user["role"] not in ("owner", "admin", "staff"):
                raise Problem(403, "Недостаточно прав")
            if assignee is not None and (not isinstance(assignee, int) or isinstance(assignee, bool) or assignee <= 0):
                raise Problem(400, "Неверный ответственный")
            if assignee is not None:
                target = get_user(conn, assignee)
                if not target or target["status"] != "active" or target["role"] not in ("owner", "admin", "staff"):
                    raise Problem(400, "Ответственный не найден")
                if user["role"] == "staff" and assignee != actor:
                    raise Problem(403, "Недостаточно прав")
            else:
                assignee = actor
        else:
            if user["role"] not in ("owner", "admin", "staff", "referrer"):
                raise Problem(403, "Недостаточно прав")
            if assignee is not None:
                raise Problem(400, "Недопустимый ответственный")
            existing = conn.execute(
                "SELECT code FROM invitations WHERE kind='referral' AND issuer_id=? AND active=1 ORDER BY created_at LIMIT 1",
                (actor,),
            ).fetchone()
            if existing:
                return {"code": existing["code"], "invite_code": existing["code"], "assignee_id": None}
        code = ("ag_" if kind == "agency" else "ref_") + secrets.token_urlsafe(18)
        conn.execute("INSERT INTO invitations(code,kind,issuer_id,assignee_id,created_at,candidate_label) VALUES(?,?,?,?,?,?)",
                     (code, kind, actor, assignee, int(time.time()), candidate_label))
        audit(conn, actor, "invite_" + kind, assignee)
        return {"code": code, "invite_code": code, "assignee_id": assignee}


def capture_signed_start(conn, identity):
    """Store the first eligible HMAC-verified Mini App start_param."""
    code = identity.get("start_param")
    if isinstance(code, str) and CODE_PATTERN.fullmatch(code):
        capture_pending_source(conn, identity["id"], code)


def capture_pending_source(conn, sender_id, code):
    if get_user(conn, sender_id) is not None:
        return
    invitation = conn.execute(
        "SELECT i.kind,i.issuer_id,u.status FROM invitations i "
        "JOIN users u ON u.id=i.issuer_id WHERE i.code=? AND i.active=1",
        (code,),
    ).fetchone()
    if invitation and invitation["status"] == "active" and (
        invitation["kind"] != "referral" or invitation["issuer_id"] != sender_id
    ):
        conn.execute("INSERT OR IGNORE INTO pending_starts(telegram_id,code,updated_at) VALUES(?,?,?)",
                     (sender_id, code, int(time.time())))


def record_start(update_id, sender_id, code):
    initialize()
    with transaction() as conn:
        inserted = conn.execute("INSERT OR IGNORE INTO telegram_updates(update_id,received_at) VALUES(?,?)", (update_id, int(time.time())))
        if inserted.rowcount == 0:
            return False
        if isinstance(code, str) and CODE_PATTERN.fullmatch(code):
            capture_pending_source(conn, sender_id, code)
        return True


def require_staff(conn, actor, owner_id):
    ensure_owner(conn, owner_id)
    user = get_user(conn, actor)
    if not user or user["status"] != "active" or user["role"] not in ("owner", "admin", "staff"):
        raise Problem(403, "Недостаточно прав")
    return user


def permitted_target(conn, staff, target):
    if not target:
        raise Problem(404, "Пользователь не найден")
    if staff["role"] == "staff" and target["manager_id"] != staff["id"]:
        raise Problem(403, "Пользователь не закреплён за вами")
    if staff["role"] == "staff" and target["role"] not in ("lead", "referrer"):
        raise Problem(403, "Недостаточно прав")
    if staff["role"] == "admin" and target["role"] in ("owner", "admin"):
        raise Problem(403, "Недостаточно прав")


def dashboard(actor, owner_id):
    initialize()
    with transaction() as conn:
        staff = require_staff(conn, actor, owner_id)
        where, params = ("WHERE manager_id=?", (actor,)) if staff["role"] == "staff" else ("", ())
        rows = conn.execute("SELECT * FROM users " + where + " ORDER BY registered_at DESC,id DESC LIMIT 200", params).fetchall()
        counts = dict(conn.execute("SELECT status,count(*) AS n FROM users " + where + " GROUP BY status", params).fetchall())
        users = [public_user(row) for row in rows]
        invitations = conn.execute("SELECT code,kind,issuer_id,assignee_id,created_at,active,candidate_label FROM invitations ORDER BY created_at DESC LIMIT 200").fetchall() if staff["role"] != "staff" else conn.execute("SELECT code,kind,issuer_id,assignee_id,created_at,active,candidate_label FROM invitations WHERE issuer_id=? ORDER BY created_at DESC LIMIT 200", (actor,)).fetchall()
        events = conn.execute("SELECT id,actor_id,action,target_id,details,created_at FROM audit ORDER BY id DESC LIMIT 100").fetchall() if staff["role"] != "staff" else conn.execute("SELECT id,actor_id,action,target_id,details,created_at FROM audit WHERE actor_id=? ORDER BY id DESC LIMIT 100", (actor,)).fetchall()
        return {"counts": {k: counts.get(k, 0) for k in STATUSES}, "users": users,
                "pending": [user for user in users if user["status"] == "pending"], "invites": [dict(x) for x in invitations], "audit": [dict(x) for x in events]}


def decision(actor, owner_id, target_id, choice, reason=""):
    choice = {"approve": "active", "reject": "rejected", "block": "blocked"}.get(choice, choice)
    if choice not in ("active", "rejected", "blocked") or not isinstance(reason, str) or len(reason) > 500:
        raise Problem(400, "Недопустимое решение")
    initialize()
    with transaction() as conn:
        staff = require_staff(conn, actor, owner_id)
        target = get_user(conn, target_id)
        permitted_target(conn, staff, target)
        if target["role"] == "owner":
            raise Problem(403, "Владельца нельзя модерировать")
        if staff["role"] == "staff" and target["status"] == "blocked":
            raise Problem(403, "Снять блокировку может администратор")
        status = choice
        if target["status"] != status or target["decision_reason"] != reason:
            conn.execute("UPDATE users SET status=?,decision_reason=?,updated_at=? WHERE id=?", (status, reason, int(time.time()), target_id))
            audit(conn, actor, "decision_" + choice, target_id, reason)
            event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            enqueue(conn, f"decision:{target_id}:{status}:{event_id}", target_id,
                    "Статус вашей заявки The Affiliates Partners: " + status + (". Причина: " + reason if reason else "."))
        return public_user(get_user(conn, target_id))


def assign(actor, owner_id, target_id, manager_id=None, role=None, clear_manager=False):
    initialize()
    with transaction() as conn:
        staff = require_staff(conn, actor, owner_id)
        if staff["role"] == "staff":
            raise Problem(403, "Недостаточно прав")
        target = get_user(conn, target_id)
        permitted_target(conn, staff, target)
        if target_id == owner_id or target["role"] == "owner":
            raise Problem(403, "Владельца нельзя изменить")
        if target["status"] != "active" and role in ("staff", "admin"):
            raise Problem(409, "Сначала подтвердите пользователя")
        if role is not None and (role not in ("lead", "referrer", "staff", "admin") or (role == "admin" and staff["role"] != "owner")):
            raise Problem(403, "Недопустимая роль")
        if clear_manager and manager_id is not None:
            raise Problem(400, "Конфликт назначения руководителя")
        if manager_id is not None:
            if type(manager_id) is not int or manager_id <= 0 or manager_id == target_id:
                raise Problem(400, "Недопустимый руководитель")
            manager = get_user(conn, manager_id)
            if not manager or manager["role"] not in ("owner", "admin", "staff") or manager["status"] != "active":
                raise Problem(400, "Руководитель не найден")
            seen = {target_id}
            cursor = manager
            while cursor is not None:
                if cursor["id"] in seen:
                    raise Problem(400, "Циклическое назначение")
                seen.add(cursor["id"])
                cursor = get_user(conn, cursor["manager_id"]) if cursor["manager_id"] else None
        new_role = role or target["role"]
        selected_manager = (
            None if clear_manager or new_role == "admin"
            else target["manager_id"] if manager_id is None else manager_id
        )
        if new_role in ("owner", "admin") and selected_manager is not None:
            raise Problem(400, "Руководитель для этой роли не допускается")
        conn.execute("UPDATE users SET role=?,manager_id=?,updated_at=? WHERE id=?",
                     (new_role, selected_manager, int(time.time()), target_id))
        audit(conn, actor, "assign", target_id, "role=" + new_role + ";manager=" + str(manager_id))
        return public_user(get_user(conn, target_id))


def correct_attribution(actor, owner_id, target_id, source, referrer_id=None, agency_id=None, reason=""):
    """Exceptional owner-only correction; ordinary registration remains immutable."""
    if source not in ("agency", "referral") or not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise Problem(400, "Укажите источник и причину исправления")
    if type(target_id) is not int or target_id <= 0:
        raise Problem(400, "Неверный пользователь")
    initialize()
    with transaction() as conn:
        ensure_owner(conn, owner_id)
        operator = get_user(conn, actor)
        if actor != owner_id or not operator or operator["role"] != "owner" or operator["status"] != "active":
            raise Problem(403, "Исправление источника доступно только владельцу")
        target = get_user(conn, target_id)
        if not target or target["role"] == "owner" or target["consent_at"] is None or target["source"] not in ("agency", "referral"):
            raise Problem(404, "Зарегистрированный участник не найден")
        if source == "referral":
            if agency_id is not None or type(referrer_id) is not int or referrer_id <= 0 or referrer_id == target_id:
                raise Problem(400, "Неверный реферер")
            referrer = get_user(conn, referrer_id)
            if not referrer or referrer["status"] != "active" or referrer["role"] not in ("referrer", "staff", "admin", "owner"):
                raise Problem(400, "Реферер должен быть активным участником с правом приглашать")
            # Referral attribution inherits the referrer's agency. It may not
            # independently carry a client-selected agency or create cycles.
            chain = {target_id}
            cursor = referrer
            while cursor is not None:
                if cursor["id"] in chain:
                    raise Problem(409, "Циклическая реферальная связь")
                chain.add(cursor["id"])
                cursor = get_user(conn, cursor["referrer_id"]) if cursor["referrer_id"] else None
            resolved_agency = referrer["agency_id"]
            if resolved_agency is None and referrer["role"] in ("owner", "admin", "staff"):
                resolved_agency = referrer_id
            resolved_referrer = referrer_id
        else:
            if referrer_id is not None or type(agency_id) is not int or agency_id <= 0 or agency_id == target_id:
                raise Problem(400, "Неверное агентство")
            agency = get_user(conn, agency_id)
            if not agency or agency["status"] != "active" or agency["role"] not in ("owner", "admin", "staff"):
                raise Problem(400, "Ответственный агентства не найден")
            resolved_agency, resolved_referrer = agency_id, None
        previous = (target["source"], target["agency_id"], target["referrer_id"])
        current = (source, resolved_agency, resolved_referrer)
        if previous == current:
            return {"user": public_user(target), "changed": False}
        conn.execute("UPDATE users SET source=?,agency_id=?,referrer_id=?,updated_at=? WHERE id=?",
                     (source, resolved_agency, resolved_referrer, int(time.time()), target_id))
        audit(conn, actor, "attribution_correction", target_id,
              f"old={previous};new={current};reason={reason.strip()}")
        return {"user": public_user(get_user(conn, target_id)), "changed": True}


def audit_events(actor, owner_id):
    initialize()
    with transaction() as conn:
        staff = require_staff(conn, actor, owner_id)
        if staff["role"] == "staff":
            rows = conn.execute("SELECT * FROM audit WHERE actor_id=? OR target_id IN (SELECT id FROM users WHERE manager_id=?) ORDER BY id DESC LIMIT 200", (actor, actor)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200").fetchall()
        return [{key: row[key] for key in ("id", "actor_id", "action", "target_id", "details", "created_at")} for row in rows]
