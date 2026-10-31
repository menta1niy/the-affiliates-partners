"""Durable, transactional partner identities, invitations and moderation."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit
from contextlib import closing, contextmanager
from pathlib import Path

from server.settings import ROOT

ROLES = {"owner", "admin", "staff", "referrer", "lead"}
STATUSES = {"invited", "pending", "active", "rejected", "blocked"}
STATUS_NOTIFICATIONS = {
    "active": "Заявка одобрена. Ваш аккаунт активен.",
    "rejected": "Заявка отклонена.",
    "blocked": "Ваш аккаунт заблокирован.",
}
CODE_PATTERN = re.compile(r"^(?:ag|ref|blog)_[A-Za-z0-9_-]{8,48}$")
BLOGGER_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
_PG_INIT_LOCK = threading.Lock()
_PG_INITIALIZED_URL = None


class Problem(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def database_path():
    return Path(os.environ.get("PARTNERS_DB_PATH") or ROOT / "data" / "partners.sqlite3")


def postgres_url():
    """Opt-in only; SQLite remains the default and production is untouched."""
    return os.environ.get("PARTNERS_DATABASE_URL", "").strip()


@contextmanager
def transaction():
    if postgres_url():
        from database.postgres import connect
        connection = connect(postgres_url())
        try:
            # SQLite BEGIN IMMEDIATE serializes writers. Preserve that
            # invariant for first-source capture and internal ID allocation.
            connection.execute("SELECT pg_advisory_xact_lock(601721408157)")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return
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
    if postgres_url():
        global _PG_INITIALIZED_URL
        from database.postgres import initialize as init_postgres, validate_ready
        url = postgres_url()
        schema_mode = os.environ.get("PARTNERS_PG_SCHEMA_READY", "").strip().lower()
        if schema_mode not in ("", "false", "true"):
            raise RuntimeError("PARTNERS_PG_SCHEMA_READY must be true or false")
        schema_ready = schema_mode == "true"
        cache_key = (url, schema_ready)
        if cache_key != _PG_INITIALIZED_URL:
            with _PG_INIT_LOCK:
                if cache_key != _PG_INITIALIZED_URL:
                    if schema_ready:
                        validate_ready(url)
                    else:
                        init_postgres(url)
                    _PG_INITIALIZED_URL = cache_key
        return
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path), timeout=15)) as conn:
        if os.name != "nt":
            conn.execute("PRAGMA journal_mode=WAL")
        # Legacy CHECK domains need a table rebuild; temporarily suspend FK
        # enforcement only within initialization, then validate/re-enable it.
        conn.execute("PRAGMA foreign_keys=OFF")
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
          source TEXT CHECK(source IN ('agency','referral','blogger')), consent_at INTEGER,
          introduced_by_id INTEGER REFERENCES users(id), internal_id INTEGER UNIQUE
        );
        CREATE TABLE IF NOT EXISTS invitations (
          code TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('agency','referral','blogger')),
          issuer_id INTEGER NOT NULL REFERENCES users(id), assignee_id INTEGER REFERENCES users(id),
          created_at INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          candidate_label TEXT NOT NULL DEFAULT '', blogger_uuid TEXT
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
        CREATE TABLE IF NOT EXISTS crm_registration_outbox (
          telegram_id INTEGER PRIMARY KEY REFERENCES users(id),
          payload TEXT NOT NULL, created_at INTEGER NOT NULL,
          delivered_at INTEGER, crm_lead_id TEXT,
          attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at INTEGER NOT NULL DEFAULT 0,
          last_error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS internal_id_sequence (
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), next_id INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS crm_events (event_id TEXT PRIMARY KEY, event_hash TEXT NOT NULL,
          event_type TEXT NOT NULL, received_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS crm_lead_bindings (crm_lead_id TEXT PRIMARY KEY,
          telegram_id INTEGER NOT NULL UNIQUE REFERENCES users(id), bound_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS crm_assigned_offers (crm_lead_id TEXT NOT NULL REFERENCES crm_lead_bindings(crm_lead_id),
          offer_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(crm_lead_id,offer_id));
        CREATE TABLE IF NOT EXISTS crm_participant_states (
          crm_lead_id TEXT PRIMARY KEY REFERENCES crm_lead_bindings(crm_lead_id),
          payload TEXT NOT NULL, updated_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS crm_bloggers (blogger_uuid TEXT PRIMARY KEY,
          channel TEXT NOT NULL, issuer_id INTEGER NOT NULL REFERENCES users(id), active INTEGER NOT NULL DEFAULT 1);
        CREATE UNIQUE INDEX IF NOT EXISTS ix_crm_bloggers_channel ON crm_bloggers(LOWER(channel));
        CREATE INDEX IF NOT EXISTS ix_users_manager ON users(manager_id);
        CREATE INDEX IF NOT EXISTS ix_users_status ON users(status);
        CREATE INDEX IF NOT EXISTS ix_audit_created ON audit(id DESC);
        """)
        user_columns = {item[1] for item in conn.execute("PRAGMA table_info(users)")}
        if "source" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN source TEXT CHECK(source IN ('agency','referral'))")
        if "consent_at" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN consent_at INTEGER")
        if "introduced_by_id" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN introduced_by_id INTEGER REFERENCES users(id)")
            # Historic agency introducers cannot be reconstructed from manager;
            # backfill only referrals with a known issuer.
            conn.execute("UPDATE users SET introduced_by_id=referrer_id WHERE source='referral' AND referrer_id IS NOT NULL")
        if "internal_id" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN internal_id INTEGER")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_internal_id ON users(internal_id)")
        # Migrate existing users deterministically: owner #100, then earlier
        # registrations first. Never renumber existing internal IDs.
        conn.execute("INSERT OR IGNORE INTO internal_id_sequence(singleton,next_id) VALUES(1,100)")
        highest = conn.execute("SELECT MAX(internal_id) FROM users").fetchone()[0]
        if highest is not None:
            conn.execute("UPDATE internal_id_sequence SET next_id=MAX(next_id,?) WHERE singleton=1", (highest + 1,))
        missing = conn.execute("SELECT id FROM users WHERE internal_id IS NULL ORDER BY CASE WHEN role='owner' THEN 0 ELSE 1 END, registered_at, id").fetchall()
        for (telegram_id,) in missing:
            number = conn.execute("SELECT next_id FROM internal_id_sequence WHERE singleton=1").fetchone()[0]
            conn.execute("UPDATE users SET internal_id=? WHERE id=?", (number, telegram_id))
            conn.execute("UPDATE internal_id_sequence SET next_id=next_id+1 WHERE singleton=1")
        invitation_columns = {item[1] for item in conn.execute("PRAGMA table_info(invitations)")}
        if "candidate_label" not in invitation_columns:
            conn.execute("ALTER TABLE invitations ADD COLUMN candidate_label TEXT NOT NULL DEFAULT ''")
        if "blogger_uuid" not in invitation_columns:
            conn.execute("ALTER TABLE invitations ADD COLUMN blogger_uuid TEXT")
        for table, old_check, new_check in (
            ("users", "('agency','referral')", "('agency','referral','blogger')"),
            ("invitations", "('agency','referral')", "('agency','referral','blogger')"),
        ):
            definition = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            if old_check in definition:
                columns = [item[1] for item in conn.execute(f"PRAGMA table_info({table})")]
                names = ",".join(columns)
                conn.execute(definition.replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}_new", 1).replace(old_check, new_check))
                conn.execute(f"INSERT INTO {table}_new({names}) SELECT {names} FROM {table}")
                conn.execute(f"DROP TABLE {table}")
                conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_users_manager ON users(manager_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_users_status ON users(status)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_internal_id ON users(internal_id)")
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Legacy database contains invalid foreign keys")
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")


def public_user(row):
    if row is None:
        return None
    return {key: row[key] for key in ("id", "internal_id", "first_name", "last_name", "username", "role", "status", "agency_id", "referrer_id", "manager_id", "source", "introduced_by_id")}


def allocate_internal_id(conn):
    number = conn.execute("SELECT next_id FROM internal_id_sequence WHERE singleton=1").fetchone()[0]
    conn.execute("UPDATE internal_id_sequence SET next_id=next_id+1 WHERE singleton=1")
    return number


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
        conn.execute("INSERT INTO users(id,internal_id,first_name,role,status,registered_at,updated_at) VALUES(?,? ,?,'owner','active',?,?)",
                     (owner_id, allocate_internal_id(conn), "Владелец", now, now))
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
            pending_code = conn.execute("SELECT code FROM pending_starts WHERE telegram_id=?", (identity["id"],)).fetchone()
            if pending_code and not valid_invitation_source(conn, identity["id"], pending_code["code"]):
                conn.execute("DELETE FROM pending_starts WHERE telegram_id=?", (identity["id"],))
                pending_code = None
            pending = conn.execute("SELECT kind,issuer_id FROM invitations WHERE code=?", (pending_code["code"],)).fetchone() if pending_code else None
        if row is not None:
            conn.execute("UPDATE users SET first_name=?,last_name=?,username=? WHERE id=?",
                         (identity["first_name"], identity["last_name"], identity["username"], identity["id"]))
            row = get_user(conn, identity["id"])
        return public_user(row) if row else {
            **identity, "role": "lead", "status": "invited", "agency_id": None,
            "referrer_id": None, "manager_id": None,
            "pending_source_info": ({
                "description": {"agency": "Приглашение от агентства", "referral": "Реферальное приглашение", "blogger": "Приглашение блогера"}[pending["kind"]],
                "inviter_id": pending["issuer_id"],
            } if pending else None),
        }


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
        # A client-supplied code is only a consistency check. Source must first
        # be attested by Telegram /start or HMAC-signed Mini App start_param.
        if not pending:
            raise Problem(400, "Откройте ссылку приглашения через Telegram")
        code = pending["code"]
        if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
            raise Problem(400, "Требуется действительное приглашение")
        # Eligibility is checked again at registration time: issuer roles and
        # assignees may have changed since Telegram verified the first link.
        if not valid_invitation_source(conn, identity["id"], code):
            raise Problem(409, "Приглашение больше не действительно; откройте новую ссылку")
        invite = conn.execute("SELECT * FROM invitations WHERE code=? AND active=1", (code,)).fetchone()
        if invite is None:
            raise Problem(400, "Приглашение не найдено или отключено")
        issuer = get_user(conn, invite["issuer_id"])
        if issuer is None or issuer["status"] != "active":
            raise Problem(400, "Приглашение недействительно")
        if invite["kind"] == "referral" and issuer["id"] == identity["id"]:
            raise Problem(400, "Нельзя пригласить себя")
        if invite["kind"] == "agency":
            assignee = get_user(conn, invite["assignee_id"])
            if assignee is None or assignee["status"] != "active" or assignee["role"] not in ("owner", "admin", "staff"):
                raise Problem(409, "Ответственный приглашения больше не активен")
            # Staff work within the agency that invited them; their Telegram
            # ID identifies the manager, not a new agency.
            agency = assignee["agency_id"] if assignee["role"] == "staff" and assignee["agency_id"] else assignee["id"]
            manager = assignee["id"]
        else:
            agency = issuer["agency_id"]
            if agency is None and issuer["role"] in ("owner", "admin", "staff"):
                agency = issuer["id"]
            # A referred lead stays visible to the responsible staff member.
            manager = issuer["id"] if issuer["role"] == "staff" else issuer["manager_id"]
        referrer = issuer["id"] if invite["kind"] == "referral" else None
        now = int(time.time())
        internal_id = allocate_internal_id(conn)
        conn.execute("""INSERT INTO users(id,internal_id,first_name,last_name,username,role,agency_id,referrer_id,manager_id,registered_at,updated_at,source,consent_at,introduced_by_id)
                     VALUES(?,?,?,?,?,'lead',?,?,?,?,?,?,?,?)""", (identity["id"], internal_id, identity["first_name"], identity["last_name"],
                                               identity["username"], agency, referrer, manager, now, now, invite["kind"], now, issuer["id"]))
        if invite["kind"] == "agency":
            # Agency introductions are individual, while referral links are reusable.
            conn.execute("UPDATE invitations SET active=0 WHERE code=?", (code,))
        conn.execute("DELETE FROM pending_starts WHERE telegram_id=?", (identity["id"],))
        audit(conn, identity["id"], "register", identity["id"], "source=" + invite["kind"])
        enqueue(conn, "register:" + str(identity["id"]), owner_id,
                "Новая заявка в The Affiliates Partners.\n"
                "Внутренний ID: " + str(internal_id) + ".\n"
                "Telegram ID кандидата: " + str(identity["id"]) + ".\n"
                "Статус: ожидает рассмотрения.")
        source_type = {"referral": "referrer", "agency": "agency", "blogger": "blogger"}[invite["kind"]]
        # A staff-assigned agency invitation is employee-sourced traffic,
        # even when an owner generated the link on their behalf. Keep the
        # local invitation type stable for older clients while differentiating
        # the authoritative CRM acquisition channel.
        if invite["kind"] == "agency" and assignee["role"] == "staff":
            source_type = "worker"
        source_partner_id = (invite["blogger_uuid"] if invite["kind"] == "blogger"
                             else f"{source_type}:{assignee['id'] if source_type == 'worker' else issuer['id']}")
        payload = {"name": (identity["first_name"] + " " + identity["last_name"]).strip() or str(identity["id"]),
                   "telegram_user_id": identity["id"], "telegram_username": identity["username"] or None,
                   "source_type": source_type, "source_partner_id": source_partner_id,
                   "source_external_id": f"partners:lead:{identity['id']}"}
        if invite["kind"] == "blogger":
            payload["source_channel"] = conn.execute("SELECT channel FROM crm_bloggers WHERE blogger_uuid=?", (invite["blogger_uuid"],)).fetchone()["channel"]
        conn.execute("INSERT INTO crm_registration_outbox(telegram_id,payload,created_at) VALUES(?,?,?)",
                     (identity["id"], json.dumps(payload, ensure_ascii=False, sort_keys=True), now))
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
        # Admins are tenant-scoped even when issuing a new invitation. The
        # assignee controls the eventual lead agency, so checking only the
        # issuer would permit an invisible cross-agency invitation.
        agency = admin_agency(user)
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
                if agency is not None and target["agency_id"] != agency:
                    raise Problem(403, "Ответственный другого агентства")
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


def invite_blogger(actor, owner_id, blogger_uuid):
    if not isinstance(blogger_uuid, str) or not BLOGGER_UUID.fullmatch(blogger_uuid):
        raise Problem(400, "Некорректный UUID блогера")
    initialize()
    with transaction() as conn:
        owner = require_staff(conn, actor, owner_id)
        if owner["role"] != "owner":
            raise Problem(403, "Ссылки блогеров выдаёт владелец")
        binding = conn.execute("SELECT * FROM crm_bloggers WHERE blogger_uuid=? AND active=1", (blogger_uuid.lower(),)).fetchone()
        if not binding:
            raise Problem(404, "Нет подтверждённой CRM привязки блогера")
        existing = conn.execute("SELECT code FROM invitations WHERE kind='blogger' AND blogger_uuid=? AND active=1 ORDER BY created_at LIMIT 1", (blogger_uuid.lower(),)).fetchone()
        if existing:
            return {"code": existing["code"], "invite_code": existing["code"], "blogger_uuid": blogger_uuid.lower(), "channel": binding["channel"]}
        code = "blog_" + secrets.token_urlsafe(18)
        conn.execute("INSERT INTO invitations(code,kind,issuer_id,created_at,blogger_uuid) VALUES(?,'blogger',?,?,?)",
                     (code, binding["issuer_id"], int(time.time()), blogger_uuid.lower()))
        audit(conn, actor, "invite_blogger", binding["issuer_id"], "blogger_uuid=" + blogger_uuid.lower())
        return {"code": code, "invite_code": code, "blogger_uuid": blogger_uuid.lower(), "channel": binding["channel"]}


def revoke_invitation(actor, owner_id, code):
    if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
        raise Problem(400, "Некорректный код приглашения")
    initialize()
    with transaction() as conn:
        ensure_owner(conn, owner_id)
        user = get_user(conn, actor)
        if not user or user["status"] != "active" or user["role"] not in ("owner", "admin", "staff", "referrer"):
            raise Problem(403, "Недостаточно прав")
        invitation = conn.execute("SELECT kind,issuer_id,active FROM invitations WHERE code=?", (code,)).fetchone()
        if invitation is None:
            raise Problem(404, "Приглашение не найдено")
        if actor != owner_id and invitation["issuer_id"] != actor:
            raise Problem(403, "Можно отозвать только своё приглашение")
        if invitation["kind"] == "blogger" and actor != owner_id:
            raise Problem(403, "Ссылки блогеров отзывает владелец")
        if not invitation["active"]:
            return {"changed": False}
        conn.execute("UPDATE invitations SET active=0 WHERE code=? AND active=1", (code,))
        digest = hashlib.sha256(code.encode("ascii")).hexdigest()[:16]
        audit(conn, actor, "invite_revoke", invitation["issuer_id"],
              f"kind={invitation['kind']};code_sha256={digest}")
        return {"changed": True}


def capture_signed_start(conn, identity):
    """Store the first eligible HMAC-verified Mini App start_param."""
    code = identity.get("start_param")
    if isinstance(code, str) and CODE_PATTERN.fullmatch(code):
        capture_pending_source(conn, identity["id"], code)


def capture_pending_source(conn, sender_id, code):
    if get_user(conn, sender_id) is not None:
        return
    # A one-time agency code may expire after it was captured but before the
    # candidate registers. In that case allow a new *verified* first valid code.
    previous = conn.execute("SELECT code FROM pending_starts WHERE telegram_id=?", (sender_id,)).fetchone()
    if previous:
        if valid_invitation_source(conn, sender_id, previous["code"]):
            return
        conn.execute("DELETE FROM pending_starts WHERE telegram_id=?", (sender_id,))
    if valid_invitation_source(conn, sender_id, code):
        conn.execute("INSERT OR IGNORE INTO pending_starts(telegram_id,code,updated_at) VALUES(?,?,?)",
                     (sender_id, code, int(time.time())))


def valid_invitation_source(conn, sender_id, code):
    """Eligibility for both initial capture and retention of the first source."""
    if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
        return False
    row = conn.execute(
        "SELECT i.kind,i.issuer_id,i.assignee_id,u.role AS issuer_role,u.status AS issuer_status,"
        "b.active AS blogger_active,b.issuer_id AS blogger_issuer,"
        "a.role AS assignee_role,a.status AS assignee_status "
        "FROM invitations i JOIN users u ON u.id=i.issuer_id "
        "LEFT JOIN crm_bloggers b ON b.blogger_uuid=i.blogger_uuid "
        "LEFT JOIN users a ON a.id=i.assignee_id WHERE i.code=? AND i.active=1",
        (code,),
    ).fetchone()
    if not row or row["issuer_status"] != "active":
        return False
    if row["kind"] == "agency":
        return (row["issuer_role"] in ("owner", "admin", "staff")
                and row["assignee_role"] in ("owner", "admin", "staff")
                and row["assignee_status"] == "active")
    if row["kind"] == "blogger":
        return (row["blogger_active"] == 1 and row["blogger_issuer"] == row["issuer_id"]
                and row["issuer_role"] in ("owner", "admin", "staff") )
    return (row["kind"] == "referral" and row["issuer_id"] != sender_id
            and row["issuer_role"] in ("owner", "admin", "staff", "referrer"))


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


def admin_agency(staff):
    """Admins have agency-local authority; missing scope denies access."""
    if staff["role"] != "admin":
        return None
    agency = staff["agency_id"]
    if type(agency) is not int or agency <= 0:
        raise Problem(403, "Администратор не привязан к агентству")
    return agency


def permitted_target(conn, staff, target):
    if not target:
        raise Problem(404, "Пользователь не найден")
    agency = admin_agency(staff)
    if agency is not None and target["agency_id"] != agency:
        raise Problem(403, "Пользователь другого агентства")
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
        agency = admin_agency(staff)
        where, params = (("WHERE agency_id=?", (agency,)) if agency is not None
                         else ("WHERE manager_id=?", (actor,)) if staff["role"] == "staff" else ("", ()))
        rows = conn.execute("SELECT * FROM users " + where + " ORDER BY registered_at DESC,id DESC LIMIT 200", params).fetchall()
        counts = dict(conn.execute("SELECT status,count(*) AS n FROM users " + where + " GROUP BY status", params).fetchall())
        users = [public_user(row) for row in rows]
        invite_where, invite_params = (
            ("WHERE kind!='blogger' AND issuer_id IN (SELECT id FROM users WHERE agency_id=?) "
             "AND (assignee_id IS NULL OR assignee_id IN (SELECT id FROM users WHERE agency_id=?))", (agency, agency))
            if agency is not None else
            ("WHERE kind!='blogger' AND issuer_id=?", (actor,))
            if staff["role"] == "staff" else ("", ())
        )
        invitations = conn.execute(
            "SELECT code,kind,issuer_id,assignee_id,created_at,active,candidate_label,blogger_uuid "
            "FROM invitations " + invite_where + " ORDER BY created_at DESC LIMIT 200", invite_params
        ).fetchall()
        events = scoped_audit_rows(conn, staff, 100)
        # The persisted active flag is not enough: an active invitation may
        # have an ineligible issuer or assignee after moderation/role changes.
        # Keep raw active for audit, but expose effective usability separately.
        invites = []
        for invitation in invitations:
            item = dict(invitation)
            item["usable"] = valid_invitation_source(conn, 0, item["code"])
            invites.append(item)
        return {"counts": {k: counts.get(k, 0) for k in STATUSES}, "users": users,
                "pending": [user for user in users if user["status"] == "pending"], "invites": invites, "audit": [dict(x) for x in events]}


def admin_participant_detail(actor, owner_id, target_id):
    """Read-only participant snapshot; every query is bound to an authorized Telegram ID."""
    initialize()
    with transaction() as conn:
        staff = require_staff(conn, actor, owner_id)
        target = get_user(conn, target_id)
        permitted_target(conn, staff, target)
        binding = conn.execute("SELECT crm_lead_id,bound_at FROM crm_lead_bindings WHERE telegram_id=?", (target_id,)).fetchone()
        crm_id = binding["crm_lead_id"] if binding else None
        offers = conn.execute("SELECT payload FROM crm_assigned_offers WHERE crm_lead_id=? ORDER BY offer_id", (crm_id,)).fetchall() if crm_id else []
        state = conn.execute("SELECT payload,updated_at FROM crm_participant_states WHERE crm_lead_id=?", (crm_id,)).fetchone() if crm_id else None
        from server.tasks import _schema
        _schema(conn)
        reports = conn.execute("SELECT report_id,offer_id,action,note,created_at FROM participant_task_reports WHERE telegram_id=? AND crm_lead_id=? ORDER BY created_at DESC,report_id DESC LIMIT 100", (target_id, crm_id)).fetchall() if crm_id else []
        audit_rows = scoped_audit_rows(conn, staff, 200)
        audit_rows = [dict(row) for row in audit_rows if row["target_id"] == target_id or row["actor_id"] == target_id]
        snapshot = json.loads(state["payload"]) if state else {"applications": [], "lead_payouts": []}
        return {"user": public_user(target), "crm_lead_id": crm_id,
                "bound_at": binding["bound_at"] if binding else None,
                "offers": [json.loads(row["payload"]) for row in offers],
                "reports": [dict(row) for row in reports],
                "status": snapshot, "status_updated_at": state["updated_at"] if state else None,
                "audit": audit_rows[:100]}


def decision(actor, owner_id, target_id, choice, reason=""):
    choice = {"approve": "active", "reject": "rejected", "block": "blocked"}.get(choice, choice)
    if choice not in ("active", "rejected", "blocked") or not isinstance(reason, str) or len(reason) > 500:
        raise Problem(400, "Недопустимое решение")
    reason = reason.strip()
    if choice in ("rejected", "blocked") and not reason:
        raise Problem(400, "Укажите причину отклонения или блокировки")
    initialize()
    with transaction() as conn:
        staff = require_staff(conn, actor, owner_id)
        target = get_user(conn, target_id)
        permitted_target(conn, staff, target)
        if target["role"] == "owner":
            raise Problem(403, "Владельца нельзя модерировать")
        if staff["role"] == "staff" and target["status"] == "blocked" and choice != "blocked":
            raise Problem(403, "Снять блокировку может администратор")
        status = choice
        if target["status"] != status or target["decision_reason"] != reason:
            conn.execute("UPDATE users SET status=?,decision_reason=?,updated_at=? WHERE id=?", (status, reason, int(time.time()), target_id))
            audit(conn, actor, "decision_" + choice, target_id, reason)
            event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            enqueue(conn, f"decision:{target_id}:{status}:{event_id}", target_id,
                    "The Affiliates Partners\n" + STATUS_NOTIFICATIONS[status]
                    + ("\nПричина: " + reason if reason else ""))
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
            agency = admin_agency(staff)
            if agency is not None and manager["agency_id"] != agency:
                raise Problem(403, "Руководитель другого агентства")
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


def correct_attribution(actor, owner_id, target_id, source, referrer_id=None, agency_id=None, reason="", introduced_by_id=None):
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
            resolved_agency = agency["agency_id"] if agency["role"] == "staff" and agency["agency_id"] else agency_id
            resolved_referrer = None
        if source == "referral":
            if introduced_by_id is not None and introduced_by_id != resolved_referrer:
                raise Problem(400, "Реферер и пригласивший должны совпадать")
            resolved_introducer = resolved_referrer
        else:
            resolved_introducer = agency_id if introduced_by_id is None else introduced_by_id
            if type(resolved_introducer) is not int or resolved_introducer <= 0 or resolved_introducer == target_id:
                raise Problem(400, "Неверный пригласивший")
            inviter = get_user(conn, resolved_introducer)
            if not inviter or inviter["role"] not in ("owner", "admin", "staff") or inviter["status"] != "active":
                raise Problem(400, "Пригласивший должен быть активным представителем агентства")
            inviter_agency = inviter["agency_id"] if inviter["role"] == "staff" and inviter["agency_id"] else inviter["id"]
            if inviter_agency != resolved_agency:
                raise Problem(409, "Пригласивший не относится к указанному агентству")
        previous = (target["source"], target["agency_id"], target["referrer_id"], target["introduced_by_id"])
        current = (source, resolved_agency, resolved_referrer, resolved_introducer)
        if previous == current:
            return {"user": public_user(target), "changed": False}
        conn.execute("UPDATE users SET source=?,agency_id=?,referrer_id=?,introduced_by_id=?,updated_at=? WHERE id=?",
                     (source, resolved_agency, resolved_referrer, resolved_introducer, int(time.time()), target_id))
        audit(conn, actor, "attribution_correction", target_id,
              f"old={previous};new={current};reason={reason.strip()}")
        return {"user": public_user(get_user(conn, target_id)), "changed": True}


def audit_events(actor, owner_id):
    initialize()
    with transaction() as conn:
        staff = require_staff(conn, actor, owner_id)
        rows = scoped_audit_rows(conn, staff, 200)
        return [{key: row[key] for key in ("id", "actor_id", "action", "target_id", "details", "created_at")} for row in rows]


def scoped_audit_rows(conn, staff, limit):
    agency = admin_agency(staff)
    if agency is not None:
        return conn.execute("SELECT * FROM audit WHERE actor_id IN (SELECT id FROM users WHERE agency_id=?) AND (target_id IS NULL OR target_id IN (SELECT id FROM users WHERE agency_id=?)) ORDER BY id DESC LIMIT ?", (agency, agency, limit)).fetchall()
    if staff["role"] == "staff":
        return conn.execute("SELECT * FROM audit WHERE actor_id=? OR target_id IN (SELECT id FROM users WHERE manager_id=?) ORDER BY id DESC LIMIT ?", (staff["id"], staff["id"], limit)).fetchall()
    return conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def sanitize_published_instruction(value):
    """Only released participant-safe plain text and HTTPS attachments."""
    if not isinstance(value, dict) or set(value) != {"text", "images", "links"}:
        raise Problem(400, "Invalid published instruction fields")

    def plain(text, limit):
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 and c not in '\n\t\r' for c in text):
            raise Problem(400, "Invalid published instruction text")
        return text

    def https(url):
        if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() for c in url):
            raise Problem(400, "Invalid published instruction URL")
        try:
            parsed = urlsplit(url)
            port = parsed.port  # Invalid or out-of-range ports raise ValueError.
            valid = (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
                     and not parsed.password and (port is None or port > 0)
                     and not parsed.fragment and not parsed.hostname.endswith("."))
        except ValueError:
            valid = False
        if not valid:
            raise Problem(400, "Published instruction requires HTTPS URL")
        return url

    if not isinstance(value["images"], list) or len(value["images"]) > 12:
        raise Problem(400, "Invalid published images")
    if not isinstance(value["links"], list) or len(value["links"]) > 24:
        raise Problem(400, "Invalid published links")
    images, links = [], []
    for item in value["images"]:
        if not isinstance(item, dict) or set(item) != {"url", "alt"}:
            raise Problem(400, "Invalid published image fields")
        images.append({"url": https(item["url"]), "alt": plain(item["alt"], 200)})
    for item in value["links"]:
        if not isinstance(item, dict) or set(item) != {"url", "label"}:
            raise Problem(400, "Invalid published link fields")
        links.append({"url": https(item["url"]), "label": plain(item["label"], 200)})
    return {"text": plain(value["text"], 12000), "images": images, "links": links}


def receive_crm_event(event):
    """Apply authenticated CRM delivery once; never infer Telegram identity from lead ID."""
    if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not 1 <= len(event["event_id"]) <= 128:
        raise Problem(400, "Некорректный идентификатор события CRM")
    kind = event.get("type")
    if kind not in ("lead.bound", "offers.assigned", "blogger.bound", "participant.state"):
        raise Problem(400, "Неизвестное событие CRM")
    crm_id = event.get("crm_lead_id")
    if kind != "blogger.bound" and (not isinstance(crm_id, str) or not 1 <= len(crm_id) <= 128):
        raise Problem(400, "Некорректный CRM ID")
    if kind == "blogger.bound":
        blogger_uuid, channel, issuer_id, active = (event.get(k) for k in ("blogger_uuid", "channel", "issuer_id", "active"))
        if (not isinstance(blogger_uuid, str) or not BLOGGER_UUID.fullmatch(blogger_uuid)
                or not isinstance(channel, str) or not 1 <= len(channel.strip()) <= 200
                or type(issuer_id) is not int or issuer_id <= 0 or type(active) is not bool):
            raise Problem(400, "Некорректная привязка блогера CRM")
    elif kind == "lead.bound":
        telegram_id = event.get("telegram_id")
        if type(telegram_id) is not int or telegram_id <= 0:
            raise Problem(400, "Требуется подтверждённая привязка Telegram ID")
    elif kind == "offers.assigned":
        offers = event.get("offers")
        if not isinstance(offers, list) or len(offers) > 200:
            raise Problem(400, "Некорректный список офферов")
        ids = set()
        safe_offers = []
        visible_fields = {"id", "name", "advertiser", "type", "target_action", "referral_url", "lead_reward", "instructions"}
        for offer in offers:
            if not isinstance(offer, dict) or not isinstance(offer.get("id"), (str, int)) or isinstance(offer.get("id"), bool):
                raise Problem(400, "Некорректный оффер CRM")
            key = str(offer["id"])
            if not key or len(key) > 128 or key in ids:
                raise Problem(400, "Повторяющийся CRM offer ID")
            ids.add(key)
            # Never persist or echo arbitrary CRM fields into a participant's
            # cabinet. In particular, agency_rate, blogger_payout and profit
            # are server-internal even when present in an authenticated event.
            public = {field: offer[field] for field in visible_fields if field in offer}
            public["id"] = key
            if "name" not in public and isinstance(offer.get("title"), str):
                public["name"] = offer["title"]
            if "published_instruction" in offer:
                public["published_instruction"] = sanitize_published_instruction(offer["published_instruction"])
            safe_offers.append(public)
    elif kind == "participant.state":
        applications, payouts = event.get("applications"), event.get("lead_payouts")
        if not isinstance(applications, list) or len(applications) > 200 or not isinstance(payouts, list) or len(payouts) > 200:
            raise Problem(400, "Некорректное состояние CRM")
        for item in applications:
            if (not isinstance(item, dict) or set(item) != {"application_id", "offer_id", "stage"}
                    or any(not isinstance(item[k], str) or not 1 <= len(item[k]) <= 128 for k in item)
                    or item["stage"] not in {"applied", "meeting_scheduled", "picked_up", "target_done", "credited", "paid"}):
                raise Problem(400, "Некорректный статус заявки CRM")
        for item in payouts:
            if (not isinstance(item, dict) or set(item) != {"conversion_id", "offer_id", "amount", "status", "reversed"}
                    or any(not isinstance(item[k], str) or not 1 <= len(item[k]) <= 128 for k in ("conversion_id", "offer_id", "amount", "status"))
                    or item["status"] not in {"confirmed", "paid"} or type(item["reversed"]) is not bool):
                raise Problem(400, "Некорректная выплата CRM")
            try:
                from decimal import Decimal, InvalidOperation
                amount = Decimal(item["amount"])
                if not amount.is_finite() or amount < 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                raise Problem(400, "Некорректная сумма выплаты CRM") from None
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(canonical.encode("utf-8")) > 65536:
        raise Problem(400, "Событие CRM слишком велико")
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    initialize()
    with transaction() as conn:
        previous = conn.execute("SELECT event_hash FROM crm_events WHERE event_id=?", (event["event_id"],)).fetchone()
        if previous:
            if previous["event_hash"] != digest:
                raise Problem(409, "CRM event ID уже использован с другим содержимым")
            return {"changed": False}
        if kind == "blogger.bound":
            issuer = get_user(conn, issuer_id)
            if not issuer or issuer["status"] != "active" or issuer["role"] not in ("owner", "admin", "staff"):
                raise Problem(409, "CRM указала неактивного ответственного блогера")
            existing = conn.execute("SELECT issuer_id FROM crm_bloggers WHERE blogger_uuid=?", (blogger_uuid.lower(),)).fetchone()
            if existing and existing["issuer_id"] != issuer_id:
                raise Problem(409, "CRM блогер уже привязан к другому ответственному")
            occupied = conn.execute("SELECT blogger_uuid FROM crm_bloggers WHERE LOWER(channel)=LOWER(?)", (channel.strip(),)).fetchone()
            if occupied and occupied["blogger_uuid"] != blogger_uuid.lower():
                raise Problem(409, "Канал CRM уже привязан к другому блогеру")
            conn.execute("INSERT INTO crm_bloggers(blogger_uuid,channel,issuer_id,active) VALUES(?,?,?,?) "
                         "ON CONFLICT(blogger_uuid) DO UPDATE SET channel=excluded.channel,active=excluded.active",
                         (blogger_uuid.lower(), channel.strip(), issuer_id, int(active)))
        elif kind == "lead.bound":
            participant = get_user(conn, telegram_id)
            if participant is None or participant["consent_at"] is None:
                raise Problem(409, "Участник Telegram не зарегистрирован")
            outbound = conn.execute("SELECT crm_lead_id FROM crm_registration_outbox WHERE telegram_id=?",
                                    (telegram_id,)).fetchone()
            if outbound is not None and outbound["crm_lead_id"] is not None and outbound["crm_lead_id"] != crm_id:
                raise Problem(409, "CRM ID не совпадает с регистрацией участника")
            current = conn.execute("SELECT crm_lead_id,telegram_id FROM crm_lead_bindings WHERE crm_lead_id=? OR telegram_id=?",
                                   (crm_id, telegram_id)).fetchall()
            if current and any(r["crm_lead_id"] != crm_id or r["telegram_id"] != telegram_id for r in current):
                raise Problem(409, "CRM ID уже закреплён за другим участником")
            conn.execute("INSERT OR IGNORE INTO crm_lead_bindings(crm_lead_id,telegram_id,bound_at) VALUES(?,?,?)",
                         (crm_id, telegram_id, int(time.time())))
        elif kind == "offers.assigned":
            binding = conn.execute("SELECT telegram_id FROM crm_lead_bindings WHERE crm_lead_id=?", (crm_id,)).fetchone()
            if not binding:
                raise Problem(409, "CRM ID не привязан к подтверждённому Telegram пользователю")
            conn.execute("DELETE FROM crm_assigned_offers WHERE crm_lead_id=?", (crm_id,))
            for offer in safe_offers:
                conn.execute("INSERT INTO crm_assigned_offers(crm_lead_id,offer_id,payload) VALUES(?,?,?)",
                             (crm_id, str(offer["id"]), json.dumps(offer, ensure_ascii=False, sort_keys=True)))
        else:
            binding = conn.execute("SELECT telegram_id FROM crm_lead_bindings WHERE crm_lead_id=?", (crm_id,)).fetchone()
            if not binding:
                raise Problem(409, "CRM ID не привязан к подтверждённому Telegram пользователю")
            safe = {"applications": applications, "lead_payouts": payouts}
            conn.execute("INSERT INTO crm_participant_states(crm_lead_id,payload,updated_at) VALUES(?,?,?) "
                         "ON CONFLICT(crm_lead_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                         (crm_id, json.dumps(safe, ensure_ascii=False, sort_keys=True), int(time.time())))
        conn.execute("INSERT INTO crm_events(event_id,event_hash,event_type,received_at) VALUES(?,?,?,?)",
                     (event["event_id"], digest, kind, int(time.time())))
        return {"changed": True}


def list_assigned_offers(telegram_id, owner_id):
    initialize()
    with transaction() as conn:
        user = get_user(conn, telegram_id)
        if not user or user["status"] != "active" or user["consent_at"] is None:
            return []
        rows = conn.execute("SELECT o.payload FROM crm_assigned_offers o "
                            "JOIN crm_lead_bindings b ON b.crm_lead_id=o.crm_lead_id "
                            "WHERE b.telegram_id=? ORDER BY o.offer_id", (telegram_id,)).fetchall()
        return [json.loads(row["payload"]) for row in rows]


def participant_status(telegram_id, owner_id):
    initialize()
    with transaction() as conn:
        user = get_user(conn, telegram_id)
        if not user or user["status"] != "active" or user["consent_at"] is None:
            return {"applications": [], "lead_payouts": []}
        row = conn.execute("SELECT s.payload FROM crm_participant_states s "
                           "JOIN crm_lead_bindings b ON b.crm_lead_id=s.crm_lead_id "
                           "WHERE b.telegram_id=?", (telegram_id,)).fetchone()
        return json.loads(row["payload"]) if row else {"applications": [], "lead_payouts": []}
