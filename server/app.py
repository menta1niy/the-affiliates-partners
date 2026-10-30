"""Minimal development API. Production: HTTPS reverse proxy + CRM integration."""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse
from config import load_local_env
from crm_feed import normalize_feed, apply_feed, finalize_snapshot
from crm_snapshot import begin as snapshot_begin, batch as snapshot_batch, finalize as snapshot_finalize
from crm_identity import schema as identity_schema, owner_assign, attest

load_local_env()

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("PARTNERS_DB_PATH") or ROOT / "partners.sqlite3").resolve()
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED = os.environ.get("ALLOWED_ORIGIN", "")
ADMIN_ID = 758398804  # Verify signed Telegram user ID, never the mutable username.
PARTNER_STATES = {"pending", "active", "rejected"}
OFFER_STATES = {"draft", "approved", "rejected", "paused"}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def db():
    conn = sqlite3.connect(DB, factory=ClosingConnection, timeout=5)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        # Serialize schema inspection and ALTER TABLE across concurrent requests.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS partners (
            telegram_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS offers (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
            rate INTEGER NOT NULL, goal TEXT NOT NULL, hold INTEGER NOT NULL,
            description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
            updated_at INTEGER NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS crm_offer_source (
            offer_id TEXT PRIMARY KEY, source_active INTEGER NOT NULL,
            last_seen INTEGER NOT NULL)""")
        identity_schema(conn)
        # Older installations may have tables without fields added later.
        # SQLite supports additive NOT NULL columns only with a constant default.
        missing_columns = {
            "partners": {
                "username": "TEXT NOT NULL DEFAULT ''",
                "name": "TEXT NOT NULL DEFAULT ''",
                "phone": "TEXT NOT NULL DEFAULT ''",
                "status": "TEXT NOT NULL DEFAULT 'pending'",
                "created_at": "INTEGER NOT NULL DEFAULT 0",
            },
            "offers": {
                "name": "TEXT NOT NULL DEFAULT ''",
                "type": "TEXT NOT NULL DEFAULT ''",
                "rate": "INTEGER NOT NULL DEFAULT 0",
                "goal": "TEXT NOT NULL DEFAULT ''",
                "hold": "INTEGER NOT NULL DEFAULT 0",
                "description": "TEXT NOT NULL DEFAULT ''",
                "status": "TEXT NOT NULL DEFAULT 'draft'",
                "updated_at": "INTEGER NOT NULL DEFAULT 0",
            },
        }
        for table, definitions in missing_columns.items():
            existing = {column[1] for column in conn.execute(f"PRAGMA table_info({table})")}
            for name, definition in definitions.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        # A nonunique index preserves legacy rows even if phones were duplicated.
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_partners_phone
            ON partners(phone) WHERE phone <> ''""")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    return conn


def verify_init_data(data: str):
    if not TOKEN or not isinstance(data, str) or not data or len(data) > 8192:
        return None
    try:
        pairs = parse_qsl(data, keep_blank_values=True, strict_parsing=True, max_num_fields=64)
        # Duplicate keys make the signed payload ambiguous between parsers.
        if len(pairs) != len({key for key, _ in pairs}):
            return None
        params = dict(pairs)
        check = params.pop("hash", "")
        if len(check) != 64 or "auth_date" not in params or "user" not in params:
            return None
        auth_date = int(params["auth_date"])
        if auth_date > time.time() + 60 or time.time() - auth_date > 3600:
            return None
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        body = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
        expected = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, check):
            return None
        user = json.loads(params["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or not (0 < user["id"] <= 9223372036854775807):
            return None
        return user
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def partner_for(telegram_id):
    with db() as conn:
        row = conn.execute("SELECT telegram_id,username,name,phone,status FROM partners WHERE telegram_id=?", (telegram_id,)).fetchone()
    return dict(zip(["telegram_id", "username", "name", "phone", "status"], row)) if row else None


def approved_offers():
    with db() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            """SELECT o.id,o.name,o.type,o.rate,o.goal,o.hold,o.description,o.status
            FROM offers o LEFT JOIN crm_offer_source s ON s.offer_id=o.id
            WHERE o.status='approved'
              AND (o.id NOT LIKE 'crm-%' OR s.source_active=1)
            ORDER BY o.updated_at DESC""")]


def admin_snapshot():
    with db() as conn:
        conn.row_factory = sqlite3.Row
        partners = [dict(r) for r in conn.execute(
            """SELECT p.telegram_id,p.username,p.name,p.phone,p.status,p.created_at,
               m.blogger_id AS crm_blogger_id,m.verified AS crm_verified
               FROM partners p LEFT JOIN crm_partner_links m ON m.telegram_id=p.telegram_id
               ORDER BY p.created_at DESC""")]
        offers = [dict(r) for r in conn.execute(
            """SELECT o.id,o.name,o.type,o.rate,o.goal,o.hold,o.description,
               o.status,o.updated_at,s.source_active
               FROM offers o LEFT JOIN crm_offer_source s ON s.offer_id=o.id
               ORDER BY o.updated_at DESC""")]
    return {"partners": partners, "offers": offers}


def queue_partner_status(conn, telegram_id, status):
    """Queue in the same transaction as the partner status change."""
    messages = {
        "active": "Ваша заявка The Affiliates Partners одобрена. Откройте кабинет через бота.",
        "rejected": "Ваша заявка The Affiliates Partners отклонена. Для повторной подачи отправьте /retry боту.",
        "pending": "Статус вашей заявки The Affiliates Partners: на рассмотрении.",
    }
    if os.environ.get("TELEGRAM_NOTIFICATIONS_ENABLED") == "0":
        return
    conn.execute("""CREATE TABLE IF NOT EXISTS bot_outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
        message TEXT NOT NULL, created_at INTEGER NOT NULL)""")
    conn.execute("INSERT INTO bot_outbox(chat_id,message,created_at) VALUES(?,?,?)",
                 (telegram_id, messages[status], int(time.time())))


def notify_partner_status(telegram_id, status):
    with db() as conn:
        queue_partner_status(conn, telegram_id, status)


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, body):
        payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if ALLOWED:
            self.send_header("Access-Control-Allow-Origin", ALLOWED)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/api/health":
            return self.respond(200, {"ok": True})
        return self.respond(404, {"error": "Не найдено"})

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.respond(400, {"error": "Неверный размер запроса"})
        if size < 1 or size > 16384:
            return self.respond(400, {"error": "Неверный размер запроса"})
        try:
            body = json.loads(self.rfile.read(size))
        except (ValueError, TypeError, UnicodeDecodeError):
            return self.respond(400, {"error": "Неверный JSON"})
        if not isinstance(body, dict):
            return self.respond(400, {"error": "Неверный запрос"})
        route = urlparse(self.path).path
        if route in ("/api/internal/crm/offers", "/api/internal/crm/identity",
                     "/api/internal/crm/identity/requests"):
            token = os.environ.get("CRM_FEED_TOKEN", "")
            workspace = os.environ.get("CRM_WORKSPACE_ID", "")
            if len(token) < 32 or not workspace:
                return self.respond(503, {"error": "CRM feed is not configured"})
            presented = self.headers.get("X-CRM-Feed-Token", "")
            if not hmac.compare_digest(token, presented):
                return self.respond(403, {"error": "CRM feed not authorized"})
            if route == "/api/internal/crm/identity/requests":
                if body != {"workspace_id": workspace}:
                    return self.respond(400, {"error": "Invalid identity lookup"})
                with db() as conn:
                    ids = [row[0] for row in conn.execute(
                        "SELECT blogger_id FROM crm_partner_links WHERE workspace_id=? ORDER BY blogger_id",
                        (workspace,))]
                return self.respond(200, {"blogger_ids": ids})
            if route == "/api/internal/crm/identity":
                if body.get("workspace_id") != workspace or set(body) != {"workspace_id", "blogger_ids"}:
                    return self.respond(400, {"error": "Invalid CRM identity attestation"})
                try:
                    with db() as conn:
                        verified = attest(conn, workspace, body["blogger_ids"], int(time.time()))
                except ValueError as error:
                    return self.respond(400, {"error": str(error)})
                return self.respond(200, {"ok": True, "verified": verified})
            if body.get("mode") in {"begin", "batch", "commit"}:
                if body.get("workspace_id") != workspace or not isinstance(body.get("run_id"), str):
                    return self.respond(400, {"error": "Invalid snapshot identity"})
                try:
                    mode = body["mode"]
                    with db() as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        if mode == "begin":
                            state = snapshot_begin(conn, workspace, body["run_id"], body.get("expected"))
                            result = {"state": state}
                        elif mode == "batch":
                            prepared = normalize_feed({"workspace_id": workspace, "offers": body.get("offers")}, workspace)
                            result = {"received": snapshot_batch(conn, workspace, body["run_id"], prepared)}
                        else:
                            result = {"paused": snapshot_finalize(conn, workspace, body["run_id"], body.get("digest"))}
                    return self.respond(200, {"ok": True, **result})
                except (ValueError, TypeError) as error:
                    return self.respond(409, {"error": str(error)})
            # Older unversioned calls cannot guarantee a complete snapshot.
            # Keep an explicit local-test compatibility switch, disabled in production.
            if os.environ.get("CRM_ALLOW_LEGACY_FEED") != "1":
                return self.respond(409, {"error": "Staged CRM sync protocol required"})
            if body.get("mode") == "finalize":
                if set(body) != {"mode", "workspace_id", "offer_ids"} or body["workspace_id"] != workspace:
                    return self.respond(400, {"error": "Invalid CRM manifest"})
                try:
                    with db() as conn:
                        paused = finalize_snapshot(conn, workspace, body["offer_ids"], int(time.time()))
                except ValueError as error:
                    return self.respond(400, {"error": str(error)})
                return self.respond(200, {"ok": True, "stale": paused})
            try:
                prepared = normalize_feed(body, workspace)
            except ValueError as error:
                return self.respond(400, {"error": str(error)})
            with db() as conn:
                count = apply_feed(conn, prepared, int(time.time()))
            return self.respond(200, {"ok": True, "imported": count, "reviewRequired": True})
        user = verify_init_data(body.get("initData", ""))
        if not user:
            return self.respond(401, {"error": "Данные Telegram не прошли проверку"})
        uid = user["id"]
        route = urlparse(self.path).path
        if route == "/api/offers":
            profile = partner_for(uid)
            if uid != ADMIN_ID and (not profile or profile["status"] != "active" or not profile["phone"]):
                return self.respond(403, {"error": "Офферы доступны только одобренным партнёрам"})
            return self.respond(200, {"offers": approved_offers()})
        if route in ("/api/auth/telegram", "/api/me"):
            if uid != ADMIN_ID:
                with db() as conn:
                    conn.execute("""INSERT INTO partners(telegram_id, username, name, created_at)
                        VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                        username=excluded.username, name=excluded.name""",
                        (uid, str(user.get("username") or ""), str(user.get("first_name") or "Партнёр"), int(time.time())))
            profile = partner_for(uid)
            if uid == ADMIN_ID:
                # The verified Telegram identity is authoritative, even if a
                # historical row exists with a stale pending/rejected status.
                profile = {"telegram_id": uid, "username": str(user.get("username") or ""),
                           "name": str(user.get("first_name") or "Администратор"),
                           "phone": profile["phone"] if profile else "", "status": "active"}
            elif profile:
                with db() as conn:
                    link = conn.execute("SELECT verified FROM crm_partner_links WHERE telegram_id=?", (uid,)).fetchone()
                profile["crmLinked"] = bool(link and link[0]) and profile["status"] == "active"
            return self.respond(200, {"profile": profile, "isAdmin": uid == ADMIN_ID})
        if route.startswith("/api/admin/"):
            if uid != ADMIN_ID:
                return self.respond(403, {"error": "Недостаточно прав"})
            if route == "/api/admin/snapshot":
                return self.respond(200, admin_snapshot())
            if route == "/api/admin/partners/crm-link":
                partner_id = body.get("telegram_id")
                blogger_id = body.get("blogger_id")
                workspace = os.environ.get("CRM_WORKSPACE_ID", "")
                if type(partner_id) is not int or partner_id == ADMIN_ID or not workspace:
                    return self.respond(400, {"error": "CRM mapping is not configured or partner invalid"})
                try:
                    with db() as conn:
                        mapped = owner_assign(conn, partner_id, workspace, blogger_id)
                except (ValueError, sqlite3.IntegrityError) as error:
                    return self.respond(400, {"error": str(error)})
                return self.respond(200, {"ok": True, "blogger_id": mapped, "verified": False})
            if route == "/api/admin/partners/status":
                status = body.get("status")
                partner_id = body.get("telegram_id")
                if status not in {"active", "rejected", "pending"} or type(partner_id) is not int:
                    return self.respond(400, {"error": "Неверные параметры"})
                if partner_id == ADMIN_ID:
                    return self.respond(400, {"error": "Нельзя менять собственную роль"})
                with db() as conn:
                    row = conn.execute("SELECT phone,status FROM partners WHERE telegram_id=?", (partner_id,)).fetchone()
                    if status == "active":
                        if row and not row[0]:
                            return self.respond(400, {"error": "Сначала требуется подтверждение телефона"})
                    if row and row[1] != status:
                        conn.execute("UPDATE partners SET status=? WHERE telegram_id=?", (status, partner_id))
                        queue_partner_status(conn, partner_id, status)
                return self.respond(200 if row else 404, {"ok": bool(row)})
            if route == "/api/admin/offers/save":
                offer = body.get("offer")
                if not isinstance(offer, dict):
                    return self.respond(400, {"error": "Неверный оффер"})
                fields = ("id", "name", "type", "goal", "description")
                if any(not isinstance(offer.get(k), str) or not offer[k].strip() or len(offer[k]) > 1000 for k in fields):
                    return self.respond(400, {"error": "Заполните поля оффера"})
                if len(offer["id"]) > 80 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in offer["id"]):
                    return self.respond(400, {"error": "Неверный ID"})
                if offer.get("status") not in OFFER_STATES or type(offer.get("rate")) is not int or type(offer.get("hold")) is not int:
                    return self.respond(400, {"error": "Неверные значения"})
                if not (0 <= offer["rate"] <= 100000000 and 0 <= offer["hold"] <= 365):
                    return self.respond(400, {"error": "Значение вне диапазона"})
                with db() as conn:
                    if offer["status"] == "approved" and offer["id"].startswith("crm-"):
                        active = conn.execute("SELECT source_active FROM crm_offer_source WHERE offer_id=?",
                                              (offer["id"],)).fetchone()
                        if not active or not active[0]:
                            return self.respond(409, {"error": "CRM offer is inactive or missing"})
                    conn.execute("""INSERT INTO offers(id,name,type,rate,goal,hold,description,status,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,type=excluded.type,rate=excluded.rate,
                        goal=excluded.goal,hold=excluded.hold,description=excluded.description,
                        status=excluded.status,updated_at=excluded.updated_at""",
                        tuple(offer[k].strip() if isinstance(offer[k], str) else offer[k]
                              for k in ("id", "name", "type", "rate", "goal", "hold", "description", "status"))
                        + (int(time.time()),))
                return self.respond(200, {"ok": True})
            if route == "/api/admin/offers/status":
                status, offer_id = body.get("status"), body.get("id")
                if status not in OFFER_STATES or not isinstance(offer_id, str):
                    return self.respond(400, {"error": "Неверные параметры"})
                with db() as conn:
                    if status == "approved" and offer_id.startswith("crm-"):
                        active = conn.execute("SELECT source_active FROM crm_offer_source WHERE offer_id=?",
                                              (offer_id,)).fetchone()
                        if not active or not active[0]:
                            return self.respond(409, {"error": "CRM offer is inactive or missing"})
                    changed = conn.execute("UPDATE offers SET status=?,updated_at=? WHERE id=?",
                                           (status, int(time.time()), offer_id)).rowcount
                return self.respond(200 if changed else 404, {"ok": bool(changed)})
            return self.respond(404, {"error": "Не найдено"})
        if route.startswith("/api/links/"):
            return self.respond(503, {"error": "Выдача ссылок станет доступна после подключения CRM и трекинга"})
        return self.respond(404, {"error": "Не найдено"})


if __name__ == "__main__":
    db().close()
    port = int(os.environ.get("SERVER_PORT", "8788"))
    print(f"Partner API listening on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
