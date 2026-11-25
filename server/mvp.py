"""Small, independently usable Partners offer-management mode.

These are admin-managed *operational* states, never CRM banking approvals or
payment confirmation. All reads are Telegram-identity scoped.
"""
import base64
import binascii
import hashlib
import io
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from server import db

STAGES = {"assigned", "in_progress", "submitted", "completed", "rejected"}
OFFER_ID = re.compile(r"^manual_[0-9a-f]{20}$")
MAX_BULK_ASSIGNMENTS = 200
LOGO_HASH = re.compile(r"^[0-9a-f]{64}$")
LOGO_DATA = re.compile(r"^data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")
MAX_LOGO_UPLOAD = 1024 * 1024
MAX_LOGO_PIXELS = 8_000_000
MAX_LOGO_OUTPUT = 250_000
LEAD_STAGE_LABELS = {
    "application_sent": "Отправил заявку",
    "meeting_scheduled": "Назначена встреча",
    "product_received": "Продукт получен",
    "account_opened": "Счёт открыт",
    "loan_issued": "Займ получен",
}
DEFAULT_LEAD_STAGES = ("application_sent", "meeting_scheduled", "product_received")


def default_lead_stages(category):
    kind = category.lower().replace("ё", "е")
    if "мфо" in kind or "микрозайм" in kind or "микрокредит" in kind:
        return ["application_sent", "loan_issued"]
    if "бизнес" in kind or "рко" in kind or "расчетн" in kind:
        return list(DEFAULT_LEAD_STAGES)
    if "карт" in kind:
        return list(DEFAULT_LEAD_STAGES)
    return ["application_sent", "product_received"]


def _lead_stages(value, category):
    if value is None:
        return default_lead_stages(category)
    if (not isinstance(value, list) or not 1 <= len(value) <= 5
            or any(type(v) is not str or v not in LEAD_STAGE_LABELS for v in value)
            or len(value) != len(set(value))):
        raise db.Problem(400, "Некорректные этапы выполнения оффера")
    return value


def _logo_bytes(value):
    if not isinstance(value, str) or len(value) > MAX_LOGO_UPLOAD * 4 // 3 + 128:
        raise db.Problem(400, "Логотип слишком большой")
    match = LOGO_DATA.fullmatch(value)
    if not match:
        raise db.Problem(400, "Поддерживаются PNG, JPG и WebP")
    try:
        raw = base64.b64decode(match.group(1), validate=True)
    except (binascii.Error, ValueError):
        raise db.Problem(400, "Некорректное изображение") from None
    if len(raw) > MAX_LOGO_UPLOAD:
        raise db.Problem(400, "Размер логотипа превышает 1 МБ")
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        raise db.Problem(503, "Обработка изображений не установлена на сервере") from None
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ("PNG", "JPEG", "WEBP") or getattr(image, "n_frames", 1) != 1:
                raise ValueError
            if image.width * image.height > MAX_LOGO_PIXELS or min(image.size) < 1:
                raise ValueError
            image.load()
            normalized = ImageOps.exif_transpose(image).convert("RGBA")
            normalized.thumbnail((960, 960), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            normalized.save(output, format="WEBP", quality=78, method=4)
            content = output.getvalue()
            if len(content) > MAX_LOGO_OUTPUT:
                raise ValueError
            return hashlib.sha256(content).hexdigest(), content
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise db.Problem(400, "Некорректное изображение или слишком большое разрешение") from None


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
    existing = {row[1] for row in conn.execute("PRAGMA table_info(manual_offers)")}
    if "logo_hash" not in existing:
        conn.execute("ALTER TABLE manual_offers ADD COLUMN logo_hash TEXT NOT NULL DEFAULT ''")
    if "lead_stages" not in existing:
        conn.execute("""ALTER TABLE manual_offers ADD COLUMN lead_stages TEXT NOT NULL
                        DEFAULT '["application_sent","meeting_scheduled","product_received"]'""")
    if "deleted_at" not in existing:
        conn.execute("ALTER TABLE manual_offers ADD COLUMN deleted_at INTEGER NOT NULL DEFAULT 0")
    conn.execute("""CREATE TABLE IF NOT EXISTS offer_logos (
        logo_hash TEXT PRIMARY KEY, image_data BLOB NOT NULL,
        created_at INTEGER NOT NULL)""")
    from server import offer_workflow
    offer_workflow.schema(conn)


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
    result = {k: row[k] for k in ("id", "name", "category", "target_action", "payout_rub",
                                  "hold_days", "instructions", "referral_url", "active")}
    result["lead_stages"] = json.loads(row["lead_stages"])
    result["logo_url"] = ("/partners/api/offer-logo/" + row["logo_hash"]) if row["logo_hash"] else ""
    return result


def logo(logo_hash):
    if not isinstance(logo_hash, str) or not LOGO_HASH.fullmatch(logo_hash):
        return None
    db.initialize()
    with db.transaction() as conn:
        schema(conn)
        row = conn.execute("SELECT image_data FROM offer_logos WHERE logo_hash=?", (logo_hash,)).fetchone()
        return bytes(row["image_data"]) if row is not None else None


def catalog(actor, owner_id):
    db.initialize()
    with db.transaction() as conn:
        _admin(conn, actor, owner_id)
        schema(conn)
        rows = conn.execute("SELECT * FROM manual_offers WHERE deleted_at=0 ORDER BY created_at DESC,id DESC LIMIT 300").fetchall()
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
    lead_stages = json.dumps(_lead_stages(data.get("lead_stages"), category), separators=(",", ":"))
    logo_data = data.get("logo_data")
    remove_logo = data.get("remove_logo", False)
    if type(remove_logo) is not bool or (logo_data is not None and remove_logo):
        raise db.Problem(400, "Некорректное действие с логотипом")
    now = int(time.time())
    db.initialize()
    with db.transaction() as conn:
        _admin(conn, actor, owner_id)
        schema(conn)
        previous = None
        if offer_id:
            previous = conn.execute("SELECT logo_hash FROM manual_offers WHERE id=? AND deleted_at=0", (offer_id,)).fetchone()
            if not previous:
                raise db.Problem(404, "Оффер не найден")
        logo_hash = "" if remove_logo else previous["logo_hash"] if previous else ""
        if logo_data is not None:
            logo_hash, content = _logo_bytes(logo_data)
            conn.execute("INSERT INTO offer_logos(logo_hash,image_data,created_at) VALUES(?,?,?) "
                         "ON CONFLICT(logo_hash) DO NOTHING", (logo_hash, content, now))
        if offer_id:
            conn.execute("UPDATE manual_offers SET name=?,category=?,target_action=?,payout_rub=?,hold_days=?,instructions=?,referral_url=?,active=?,logo_hash=?,lead_stages=?,updated_at=? WHERE id=?",
                         (name, category, target_action, payout, hold, instructions, link, int(active), logo_hash, lead_stages, now, offer_id))
        else:
            offer_id = "manual_" + secrets.token_hex(10)
            conn.execute("INSERT INTO manual_offers(id,name,category,target_action,payout_rub,hold_days,instructions,referral_url,active,logo_hash,lead_stages,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (offer_id, name, category, target_action, payout, hold, instructions, link, int(active), logo_hash, lead_stages, now, now))
        db.audit(conn, actor, "manual_offer_save", None, offer_id)
        return {"offer_id": offer_id}


def delete_offer(actor, owner_id, data):
    """Hide an offer from the catalogue without deleting assignments or ledger references."""
    offer_id = data.get("offer_id")
    if not isinstance(offer_id, str) or not OFFER_ID.fullmatch(offer_id):
        raise db.Problem(400, "Некорректный оффер")
    db.initialize()
    with db.transaction() as conn:
        _admin(conn, actor, owner_id)
        schema(conn)
        offer = conn.execute("SELECT id FROM manual_offers WHERE id=? AND deleted_at=0", (offer_id,)).fetchone()
        if not offer:
            raise db.Problem(404, "Оффер не найден")
        conn.execute("UPDATE manual_offers SET active=0,deleted_at=?,updated_at=? WHERE id=?",
                     (int(time.time()), int(time.time()), offer_id))
        db.audit(conn, actor, "manual_offer_delete", None, offer_id)
        return {"deleted": True, "offer_id": offer_id}


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
    if not isinstance(stage, str) or stage not in STAGES:
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
        offer = conn.execute("SELECT active FROM manual_offers WHERE id=? AND deleted_at=0", (offer_id,)).fetchone()
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


def assignment_candidates(actor, owner_id, data):
    """Page through eligible participants without leaking other agencies' leads."""
    page = data.get("page", 1)
    query = data.get("query", "")
    role = data.get("role_filter", "all")
    if type(page) is not int or not 1 <= page <= 100000:
        raise db.Problem(400, "Некорректная страница")
    if not isinstance(query, str) or len(query) > 120:
        raise db.Problem(400, "Некорректный поиск")
    if role not in ("all", "lead", "referrer"):
        raise db.Problem(400, "Некорректный фильтр")
    db.initialize()
    with db.transaction() as conn:
        staff = _admin(conn, actor, owner_id)
        schema(conn)
        conditions = ["status='active'", "role IN ('lead','referrer')"]
        params = []
        agency = db.admin_agency(staff)
        if agency is not None:
            conditions.append("agency_id=?")
            params.append(agency)
        if role != "all":
            conditions.append("role=?")
            params.append(role)
        if query.strip():
            escaped = query.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            terms = ("CAST(id AS TEXT)", "CAST(internal_id AS TEXT)",
                     "LOWER(COALESCE(first_name,''))", "LOWER(COALESCE(last_name,''))",
                     "LOWER(COALESCE(username,''))")
            conditions.append("(" + " OR ".join(f"{term} LIKE ? ESCAPE '\\'" for term in terms) + ")")
            params.extend([f"%{escaped}%"] * len(terms))
        where = " WHERE " + " AND ".join(conditions)
        total = conn.execute("SELECT count(*) FROM users" + where, tuple(params)).fetchone()[0]
        rows = conn.execute("SELECT * FROM users" + where + " ORDER BY registered_at DESC,id DESC "
                            "LIMIT 50 OFFSET ?", tuple(params) + (50 * (page - 1),)).fetchall()
        return {"users": [db.public_user(user) for user in rows], "total": total,
                "page": page, "page_size": 50, "has_next": page * 50 < total}


def bulk_assignment(actor, owner_id, data):
    """Atomic add-only assignment, with side-effect-free preview and deduplication."""
    mode = data.get("mode")
    preview = data.get("preview", False)
    if mode not in ("offer_to_leads", "lead_to_offers") or type(preview) is not bool:
        raise db.Problem(400, "Некорректный режим назначения")
    if mode == "offer_to_leads":
        offer_id = data.get("offer_id")
        raw = data.get("user_ids")
        if not isinstance(offer_id, str) or not OFFER_ID.fullmatch(offer_id):
            raise db.Problem(400, "Некорректный оффер")
        if (not isinstance(raw, list) or not 1 <= len(raw) <= MAX_BULK_ASSIGNMENTS or
                any(type(item) is not int or item <= 0 for item in raw)):
            raise db.Problem(400, "Некорректный список участников")
        user_ids = list(dict.fromkeys(raw))
        offer_ids = [offer_id]
        pairs = [(user_id, offer_id) for user_id in user_ids]
    else:
        user_id = data.get("user_id")
        raw = data.get("offer_ids")
        if type(user_id) is not int or user_id <= 0:
            raise db.Problem(400, "Некорректный участник")
        if (not isinstance(raw, list) or not 1 <= len(raw) <= MAX_BULK_ASSIGNMENTS or
                any(not isinstance(item, str) or not OFFER_ID.fullmatch(item) for item in raw)):
            raise db.Problem(400, "Некорректный список офферов")
        offer_ids = list(dict.fromkeys(raw))
        user_ids = [user_id]
        pairs = [(user_id, offer_id) for offer_id in offer_ids]
    db.initialize()
    with db.transaction() as conn:
        staff = _admin(conn, actor, owner_id)
        schema(conn)
        for user_id in user_ids:
            target = _participant(conn, staff, user_id)
            if target["status"] != "active":
                raise db.Problem(409, "Сначала одобрите всех выбранных участников")
        for offer_id in offer_ids:
            offer = conn.execute("SELECT active FROM manual_offers WHERE id=? AND deleted_at=0", (offer_id,)).fetchone()
            if not offer:
                raise db.Problem(404, "Оффер не найден")
            if not offer["active"]:
                raise db.Problem(409, "Среди выбранных есть отключённый оффер")
        existing = 0
        to_create = []
        for user_id, offer_id in pairs:
            assigned = conn.execute("SELECT 1 FROM manual_assignments WHERE telegram_id=? AND offer_id=?",
                                    (user_id, offer_id)).fetchone()
            if assigned:
                existing += 1
            else:
                to_create.append((user_id, offer_id))
        if preview:
            return {"preview": True, "requested": len(pairs), "to_create": len(to_create),
                    "already_assigned": existing, "created": 0}
        now = int(time.time())
        created = 0
        for user_id, offer_id in to_create:
            cursor = conn.execute("INSERT INTO manual_assignments(telegram_id,offer_id,stage,note,updated_at) "
                                  "VALUES(?,?,'assigned','',?) ON CONFLICT(telegram_id,offer_id) DO NOTHING",
                                  (user_id, offer_id, now))
            if cursor.rowcount:
                created += 1
                db.audit(conn, actor, "manual_assignment_bulk", user_id,
                         "offer=" + offer_id + ";stage=assigned")
        return {"preview": False, "requested": len(pairs), "to_create": 0,
                "already_assigned": existing, "created": created}


def overview(user_id, owner_id, *, for_admin=None):
    db.initialize()
    with db.transaction() as conn:
        schema(conn)
        if for_admin is not None:
            staff = _admin(conn, for_admin, owner_id)
            _participant(conn, staff, user_id)
        else:
            user = db.get_user(conn, user_id)
            if not user or user["status"] != "active":
                return {"offers": [], "statistics": {"total": 0, "completed": 0, "in_progress": 0}}
        rows = conn.execute("SELECT o.*,a.stage,a.note,a.updated_at AS status_updated_at FROM manual_assignments a "
                            "JOIN manual_offers o ON o.id=a.offer_id WHERE a.telegram_id=? "
                            "ORDER BY a.updated_at DESC,o.id", (user_id,)).fetchall()
        from server import offer_workflow
        offers = []
        for row in rows:
            if for_admin is None and not row["active"]:
                continue
            offer = {**_offer(row), "stage": row["stage"], "note": row["note"],
                     "status_updated_at": row["status_updated_at"]}
            if for_admin is None:
                offer["can_apply"] = True
                offer["unavailable_reason"] = ""
                is_mfo = offer_workflow.is_mfo(row["category"])
                offer["requires_request"] = is_mfo
                approved = offer_workflow.mfo_approved(conn, user_id, row["id"]) if is_mfo else False
                offer["mfo_approved"] = approved
                latest = conn.execute("SELECT id,kind,lead_stage,review_status,review_note,created_at FROM manual_offer_events "
                                      "WHERE telegram_id=? AND offer_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
                                      (user_id, row["id"])).fetchone()
                offer["latest_event"] = dict(latest) if latest else None
                if is_mfo and not approved:
                    offer["unavailable_reason"] = "mfo_request"
                    offer["can_apply"] = False
                if not offer["can_apply"]:
                    # Hiding a link in HTML alone is not a permission boundary.
                    offer["referral_url"] = ""
            offers.append(offer)
        return {"offers": offers, "statistics": {"total": len(offers),
                "completed": sum(row["stage"] == "completed" for row in offers),
                "in_progress": sum(row["stage"] in ("in_progress", "submitted") for row in offers)}}
