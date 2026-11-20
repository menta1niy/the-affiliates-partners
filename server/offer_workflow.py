"""Participant-declared milestones, evidence and manually reviewed MFO requests.

Never treats a participant declaration as bank attribution, credited or paid.
Screenshots are only retrievable through authenticated, scoped POST endpoints.
"""
import base64
import binascii
import io
import json
import re
import secrets
import time

from server import db, mvp
from server.profile import access_reason, _cipher

EVENT_ID = re.compile(r"^evt_[0-9a-f]{24}$")
IMAGE_DATA = re.compile(r"^data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")
MAX_IMAGE_BYTES = 550_000
MAX_PIXELS = 8_000_000
MAX_EVENTS_PAGE = 100


def is_mfo(category):
    return any(token in str(category or "").lower().replace("ё", "е")
               for token in ("мфо", "микрозайм", "микрокредит"))


def schema(conn):
    if db.postgres_url():
        return
    conn.execute("""CREATE TABLE IF NOT EXISTS manual_offer_events (
      id TEXT PRIMARY KEY,
      telegram_id INTEGER NOT NULL REFERENCES users(id),
      offer_id TEXT NOT NULL REFERENCES manual_offers(id),
      kind TEXT NOT NULL CHECK(kind IN ('stage','mfo_request')),
      lead_stage TEXT NOT NULL DEFAULT '',
      proof_url TEXT NOT NULL DEFAULT '',
      evidence_data BLOB, evidence_type TEXT NOT NULL DEFAULT '',
      review_status TEXT NOT NULL DEFAULT 'pending',
      review_note TEXT NOT NULL DEFAULT '',
      reviewed_by INTEGER REFERENCES users(id),
      created_at INTEGER NOT NULL, reviewed_at INTEGER
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_manual_offer_events_user "
                 "ON manual_offer_events(telegram_id,created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_manual_offer_events_review "
                 "ON manual_offer_events(review_status,created_at)")


def _screenshot(data):
    if data is None:
        return None
    if not isinstance(data, str) or len(data) > MAX_IMAGE_BYTES * 4 // 3 + 128:
        raise db.Problem(400, "Скриншот слишком большой")
    match = IMAGE_DATA.fullmatch(data)
    if not match:
        raise db.Problem(400, "Поддерживаются только изображения PNG, JPG или WebP")
    try:
        raw = base64.b64decode(match.group(1), validate=True)
    except (ValueError, binascii.Error):
        raise db.Problem(400, "Некорректный файл") from None
    if not 1 <= len(raw) <= MAX_IMAGE_BYTES:
        raise db.Problem(400, "Файл превышает допустимый размер")
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ("PNG", "JPEG", "WEBP") or getattr(image, "n_frames", 1) != 1:
                raise ValueError
            if not 1 <= image.width * image.height <= MAX_PIXELS:
                raise ValueError
            image.load()
            safe = ImageOps.exif_transpose(image).convert("RGB")
            safe.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            safe.save(out, format="WEBP", quality=72, method=4)
            blob = out.getvalue()
            if len(blob) > MAX_IMAGE_BYTES:
                raise ValueError
            return blob
    except ImportError:
        raise db.Problem(503, "Обработка изображений не установлена") from None
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise db.Problem(400, "Повреждённый или слишком большой скриншот") from None


def _public(row):
    return {"id": row["id"], "offer_id": row["offer_id"], "kind": row["kind"],
            "lead_stage": row["lead_stage"], "proof_url": row["proof_url"],
            "has_screenshot": row["evidence_data"] is not None,
            "review_status": row["review_status"], "review_note": row["review_note"],
            "created_at": row["created_at"], "reviewed_at": row["reviewed_at"]}


def _assignment(conn, actor, offer_id):
    if not isinstance(offer_id, str) or not mvp.OFFER_ID.fullmatch(offer_id):
        raise db.Problem(400, "Некорректный оффер")
    user = db.get_user(conn, actor)
    if not user or user["status"] != "active" or user["role"] not in ("lead", "referrer"):
        raise db.Problem(403, "Только подтверждённый участник может отправить результат")
    row = conn.execute("SELECT o.*,a.stage FROM manual_assignments a "
                       "JOIN manual_offers o ON o.id=a.offer_id "
                       "WHERE a.telegram_id=? AND a.offer_id=?", (actor, offer_id)).fetchone()
    if row is None:
        raise db.Problem(404, "Оффер не назначен")
    if not row["active"]:
        raise db.Problem(409, "Оффер отключён")
    registration = conn.execute("SELECT * FROM registration_profiles WHERE telegram_id=?", (actor,)).fetchone()
    has_identity = conn.execute("SELECT 1 FROM participant_identities WHERE telegram_id=?",
                                (actor,)).fetchone() is not None
    reason = access_reason(registration, has_identity, row["category"])
    if reason:
        raise db.Problem(403, "Оформление недоступно: " + reason)
    if row["stage"] in ("completed", "rejected"):
        raise db.Problem(409, "Назначение закрыто администратором")
    return row, user


def mfo_approved(conn, actor, offer_id):
    row = conn.execute("SELECT 1 FROM manual_offer_events WHERE telegram_id=? AND offer_id=? "
                       "AND kind='mfo_request' AND review_status='approved' LIMIT 1",
                       (actor, offer_id)).fetchone()
    return row is not None


def send(actor, owner_id, data):
    offer_id = data.get("offer_id")
    kind = data.get("kind")
    if kind not in ("stage", "mfo_request"):
        raise db.Problem(400, "Некорректный тип отправки")
    stage = data.get("lead_stage", "")
    if kind == "mfo_request":
        if stage not in ("", None) or data.get("screenshot") or data.get("proof_url"):
            raise db.Problem(400, "Запрос МФО не требует подтверждений")
        stage = ""
        link = ""
        screenshot = None
    else:
        if not isinstance(stage, str) or stage not in mvp.LEAD_STAGE_LABELS:
            raise db.Problem(400, "Некорректный этап")
        raw_url = data.get("proof_url", "")
        if not isinstance(raw_url, str):
            raise db.Problem(400, "Некорректная ссылка подтверждения")
        link = mvp._url(raw_url)
        screenshot = _screenshot(data.get("screenshot"))
        if not link and screenshot is None:
            raise db.Problem(400, "Добавьте ссылку или скриншот подтверждения")
        if screenshot is not None:
            screenshot = _cipher().encrypt(screenshot)
    db.initialize()
    with db.transaction() as conn:
        mvp.schema(conn)
        schema(conn)
        offer, user = _assignment(conn, actor, offer_id)
        mfo = is_mfo(offer["category"])
        if kind == "mfo_request" and not mfo:
            raise db.Problem(400, "Запрос доступен только для МФО")
        if kind == "stage":
            allowed = json.loads(offer["lead_stages"])
            if stage not in allowed:
                raise db.Problem(400, "Этот этап не включён для оффера")
            if mfo and not mfo_approved(conn, actor, offer_id):
                raise db.Problem(403, "Сначала запросите и получите одобрение МФО")
        if kind == "mfo_request" and mfo_approved(conn, actor, offer_id):
            raise db.Problem(409, "МФО уже согласован")
        pending = conn.execute("SELECT 1 FROM manual_offer_events WHERE telegram_id=? AND offer_id=? "
                               "AND kind=? AND review_status='pending' LIMIT 1",
                               (actor, offer_id, kind)).fetchone()
        if pending:
            raise db.Problem(409, "Предыдущая отправка ещё на рассмотрении")
        if kind == "stage":
            approved = conn.execute("SELECT 1 FROM manual_offer_events WHERE telegram_id=? AND offer_id=? "
                                    "AND kind='stage' AND lead_stage=? AND review_status='approved' LIMIT 1",
                                    (actor, offer_id, stage)).fetchone()
            if approved:
                raise db.Problem(409, "Этап уже был подтверждён менеджером")
        event_id = "evt_" + secrets.token_hex(12)
        now = int(time.time())
        conn.execute("INSERT INTO manual_offer_events(id,telegram_id,offer_id,kind,lead_stage,proof_url,"
                     "evidence_data,evidence_type,review_status,created_at) VALUES(?,?,?,?,?,?,?,'image/webp','pending',?)",
                     (event_id, actor, offer_id, kind, stage, link, screenshot, now))
        db.audit(conn, actor, "manual_offer_event_submitted", actor,
                 "offer=" + offer_id + ";type=" + kind + ";stage=" + stage)
        recipients = {owner_id}
        if user["manager_id"]:
            recipients.add(user["manager_id"])
        for recipient in recipients:
            db.enqueue(conn, "offer_event:" + event_id + ":" + str(recipient), recipient,
                       "The Affiliates Partners\nНовый результат по офферу на рассмотрении.\n"
                       "ID участника: " + str(user["internal_id"]) +
                       "\nОффер: " + offer["name"][:90])
        db.enqueue(conn, "offer_event_received:" + event_id, actor,
                   "The Affiliates Partners\n" +
                   ("Ваш запрос МФО отправлен и ожидает рассмотрения." if kind == "mfo_request"
                    else "Ваш отчёт по офферу отправлен и ожидает рассмотрения.") +
                   "\nОффер: " + offer["name"][:90])
        return {"event": {"id": event_id, "kind": kind, "lead_stage": stage,
                          "review_status": "pending"}, "created": True}


def my_events(actor, owner_id, data):
    db.initialize()
    with db.transaction() as conn:
        schema(conn)
        user = db.get_user(conn, actor)
        if not user or user["status"] != "active":
            raise db.Problem(403, "Нет доступа")
        rows = conn.execute("SELECT * FROM manual_offer_events WHERE telegram_id=? "
                            "ORDER BY created_at DESC,id DESC LIMIT ?", (actor, MAX_EVENTS_PAGE)).fetchall()
        return {"events": [_public(row) for row in rows]}


def admin_queue(actor, owner_id, data):
    status = data.get("status", "pending")
    if status not in ("pending", "approved", "rejected", "all"):
        raise db.Problem(400, "Некорректный фильтр")
    db.initialize()
    with db.transaction() as conn:
        staff = db.require_staff(conn, actor, owner_id)
        schema(conn)
        conditions = []
        params = []
        agency = db.admin_agency(staff)
        if agency is not None:
            conditions.append("u.agency_id=?")
            params.append(agency)
        if staff["role"] == "staff":
            conditions.append("u.manager_id=?")
            params.append(actor)
        if status != "all":
            conditions.append("e.review_status=?")
            params.append(status)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        rows = conn.execute("SELECT e.*,u.internal_id,o.name AS offer_name FROM manual_offer_events e "
                            "JOIN users u ON u.id=e.telegram_id "
                            "JOIN manual_offers o ON o.id=e.offer_id " + where +
                            " ORDER BY e.created_at DESC,e.id DESC LIMIT 100", tuple(params)).fetchall()
        return {"events": [{**_public(row), "user_id": row["telegram_id"],
                            "display_id": "L-" + str(row["internal_id"]).zfill(6),
                            "offer_name": row["offer_name"]} for row in rows]}


def review(actor, owner_id, data):
    event_id = data.get("event_id")
    decision = data.get("decision")
    note = data.get("note", "")
    if not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id):
        raise db.Problem(400, "Некорректное подтверждение")
    if decision not in ("approve", "reject") or not isinstance(note, str) or len(note) > 300:
        raise db.Problem(400, "Некорректное решение")
    note = note.strip()
    if decision == "reject" and not note:
        raise db.Problem(400, "Укажите причину отклонения")
    db.initialize()
    with db.transaction() as conn:
        staff = db.require_staff(conn, actor, owner_id)
        schema(conn)
        event = conn.execute("SELECT * FROM manual_offer_events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise db.Problem(404, "Результат не найден")
        target = db.get_user(conn, event["telegram_id"])
        db.permitted_target(conn, staff, target)
        if event["review_status"] != "pending":
            raise db.Problem(409, "Решение уже принято")
        if target["status"] != "active":
            raise db.Problem(409, "Аккаунт участника неактивен")
        assignment = conn.execute("SELECT a.stage,o.active FROM manual_assignments a "
                                  "JOIN manual_offers o ON o.id=a.offer_id "
                                  "WHERE a.telegram_id=? AND a.offer_id=?",
                                  (event["telegram_id"], event["offer_id"])).fetchone()
        if assignment is None:
            raise db.Problem(409, "Назначение удалено")
        if not assignment["active"]:
            raise db.Problem(409, "Оффер отключён")
        if assignment["stage"] in ("completed", "rejected"):
            raise db.Problem(409, "Назначение закрыто")
        now = int(time.time())
        outcome = "approved" if decision == "approve" else "rejected"
        conn.execute("UPDATE manual_offer_events SET review_status=?,review_note=?,reviewed_by=?,reviewed_at=? "
                     "WHERE id=? AND review_status='pending'",
                     (outcome, note, actor, now, event_id))
        if outcome == "approved":
            # A lead's evidence is NOT bank confirmation; never set completed.
            next_stage = "in_progress" if event["kind"] == "mfo_request" else "submitted"
            conn.execute("UPDATE manual_assignments SET stage=?,updated_at=? "
                         "WHERE telegram_id=? AND offer_id=?",
                         (next_stage, now, event["telegram_id"], event["offer_id"]))
        db.audit(conn, actor, "manual_offer_event_reviewed", event["telegram_id"],
                 "offer=" + event["offer_id"] + ";outcome=" + outcome + ";event=" + event_id)
        db.enqueue(conn, "offer_event_review:" + event_id, event["telegram_id"],
                   "The Affiliates Partners\n" +
                   ("Ваш запрос по офферу одобрен." if outcome == "approved"
                    else "Результат по офферу отклонён.") +
                   ("\nКомментарий: " + note if note else ""))
        return {"changed": True, "review_status": outcome, "event_id": event_id}


def evidence(actor, owner_id, data):
    event_id = data.get("event_id")
    if not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id):
        raise db.Problem(400, "Некорректный файл")
    db.initialize()
    with db.transaction() as conn:
        staff = db.require_staff(conn, actor, owner_id)
        schema(conn)
        row = conn.execute("SELECT telegram_id,evidence_data FROM manual_offer_events WHERE id=?",
                           (event_id,)).fetchone()
        if row is None or row["evidence_data"] is None:
            raise db.Problem(404, "Скриншот отсутствует")
        db.permitted_target(conn, staff, db.get_user(conn, row["telegram_id"]))
        try:
            from cryptography.fernet import InvalidToken
            raw = _cipher().decrypt(bytes(row["evidence_data"]))
        except InvalidToken:
            raise db.Problem(503, "Не удалось расшифровать подтверждение") from None
        return {"mime": "image/webp", "data": base64.b64encode(raw).decode("ascii")}
