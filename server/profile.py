"""Sensitive lead identity, credit questionnaire refresh and offer eligibility.

Full names and taxpayer IDs never appear in logs, audit details or bulk user
listings. Fernet uses a separate stable deployment secret, not the bot token.
"""
import os
import re
from datetime import date

from server import db
from server.registration import COUNTS, MAX_CREDIT_PRODUCTS_PER_TYPE, age, normalize

NAME = re.compile(r"^[A-Za-zА-Яа-яЁё]+(?:[ '-][A-Za-zА-Яа-яЁё]+)*$")
INN = re.compile(r"^\d{12}$")
SURVEY_FRESH_DAYS = 30


def _cipher():
    secret = os.environ.get("PARTNERS_PROFILE_ENCRYPTION_KEY", "")
    if not secret:
        raise db.Problem(503, "Защищённое хранение реквизитов пока не настроено")
    try:
        from cryptography.fernet import Fernet
        return Fernet(secret.encode("ascii"))
    except (ImportError, ValueError, TypeError):
        raise db.Problem(503, "Неправильно настроено защищённое хранение реквизитов") from None


def _inn_valid(value):
    if not isinstance(value, str) or not INN.fullmatch(value):
        return False
    digits = [int(ch) for ch in value]
    first = (sum(a * b for a, b in zip(digits[:10], (7, 2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11) % 10
    second = (sum(a * b for a, b in zip(digits[:11], (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11) % 10
    return digits[10] == first and digits[11] == second


def _name(value):
    if not isinstance(value, str):
        raise db.Problem(400, "Укажите ФИО по документу")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise db.Problem(400, "Проверьте ФИО: недопустимые символы")
    value = " ".join(value.strip().split())
    if not 2 <= len(value) <= 70 or not NAME.fullmatch(value):
        raise db.Problem(400, "Проверьте ФИО: только буквы, пробелы и дефис")
    return value


def save_identity(actor, data):
    surname = _name(data.get("surname"))
    given_name = _name(data.get("given_name"))
    patronymic = data.get("patronymic", "")
    if not isinstance(patronymic, str) or len(patronymic) > 70:
        raise db.Problem(400, "Некорректное отчество")
    patronymic = _name(patronymic) if patronymic.strip() else ""
    taxpayer_id = data.get("inn")
    if not _inn_valid(taxpayer_id):
        raise db.Problem(400, "Проверьте ИНН: требуется действительный 12-значный номер")
    cipher = _cipher()
    encrypted_name = cipher.encrypt(("\x1f".join((surname, given_name, patronymic))).encode("utf-8")).decode("ascii")
    encrypted_inn = cipher.encrypt(taxpayer_id.encode("ascii")).decode("ascii")
    db.initialize()
    with db.transaction() as conn:
        user = db.get_user(conn, actor)
        if not user or user["status"] != "active" or user["role"] not in ("lead", "referrer"):
            raise db.Problem(403, "Реквизиты доступны только подтверждённым участникам")
        if not conn.execute("SELECT 1 FROM registration_profiles WHERE telegram_id=?", (actor,)).fetchone():
            raise db.Problem(409, "Сначала завершите регистрацию")
        import time
        now = int(time.time())
        conn.execute("INSERT INTO participant_identities(telegram_id,full_name_encrypted,inn_encrypted,updated_at) "
                     "VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET "
                     "full_name_encrypted=excluded.full_name_encrypted,"
                     "inn_encrypted=excluded.inn_encrypted,updated_at=excluded.updated_at",
                     (actor, encrypted_name, encrypted_inn, now))
        db.audit(conn, actor, "participant_identity_saved", actor, "updated")
        return {"saved": True, "identity": {"complete": True, "surname": surname,
                                               "given_name": given_name, "patronymic": patronymic,
                                               "inn_masked": "********" + taxpayer_id[-4:]}}


def identity_view(conn, actor):
    row = conn.execute("SELECT full_name_encrypted,inn_encrypted,updated_at "
                       "FROM participant_identities WHERE telegram_id=?", (actor,)).fetchone()
    if not row:
        return {"complete": False}
    try:
        from cryptography.fernet import InvalidToken
        cipher = _cipher()
        surname, given_name, patronymic = cipher.decrypt(row["full_name_encrypted"].encode("ascii")).decode("utf-8").split("\x1f")
        inn = cipher.decrypt(row["inn_encrypted"].encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeError, ValueError):
        raise db.Problem(503, "Не удалось расшифровать реквизиты пользователя") from None
    return {"complete": True, "surname": surname, "given_name": given_name,
            "patronymic": patronymic, "inn_masked": "********" + inn[-4:],
            "updated_at": row["updated_at"]}


def profile_view(actor):
    db.initialize()
    with db.transaction() as conn:
        user = db.get_user(conn, actor)
        if not user:
            return {"complete": False}
        return identity_view(conn, actor)


def update_credit(actor, data):
    values = {}
    for name in COUNTS:
        value = data.get(name)
        if type(value) is not int or not 0 <= value <= MAX_CREDIT_PRODUCTS_PER_TYPE:
            raise db.Problem(400, "Укажите количество кредитных продуктов от 0 до 50")
        values[name] = value
    db.initialize()
    with db.transaction() as conn:
        user = db.get_user(conn, actor)
        if not user or user["status"] != "active" or user["role"] not in ("lead", "referrer"):
            raise db.Problem(403, "Анкета доступна только подтверждённым участникам")
        if not conn.execute("SELECT 1 FROM registration_profiles WHERE telegram_id=?", (actor,)).fetchone():
            raise db.Problem(409, "Анкета регистрации не найдена")
        import time
        now = int(time.time())
        conn.execute("UPDATE registration_profiles SET credit_cards=?,installments=?,loans=?,mortgages=?,"
                     "credit_updated_at=? WHERE telegram_id=?",
                     (*(values[name] for name in COUNTS), now, actor))
        db.audit(conn, actor, "credit_survey_updated", actor, "self")
        from server.registration import public_view
        row = conn.execute("SELECT * FROM registration_profiles WHERE telegram_id=?", (actor,)).fetchone()
        return {"registration": public_view(row)}


def complete_legacy_onboarding(actor, data):
    """Fill a missing survey for an existing approved user without reallocating IDs."""
    details = normalize(data)
    db.initialize()
    with db.transaction() as conn:
        user = db.get_user(conn, actor)
        if not user or user["status"] != "active" or user["role"] not in ("lead", "referrer"):
            raise db.Problem(403, "Анкета доступна только подтверждённым участникам")
        existing = conn.execute("SELECT 1 FROM registration_profiles WHERE telegram_id=?", (actor,)).fetchone()
        if existing:
            raise db.Problem(409, "Анкета уже была заполнена. Обновляйте только кредитные продукты")
        import time
        now = int(time.time())
        db.save_registration_profile(conn, actor, details, now)
        conn.execute("UPDATE users SET consent_at=COALESCE(consent_at,?),updated_at=? WHERE id=?",
                     (now, now, actor))
        db.audit(conn, actor, "registration_profile_backfill", actor, "self")
        from server.registration import public_view
        row = conn.execute("SELECT * FROM registration_profiles WHERE telegram_id=?", (actor,)).fetchone()
        return {"registration": public_view(row), "id_unchanged": user["internal_id"]}


def credit_offer(category):
    category = str(category or "").lower().replace("ё", "е")
    return any(word in category for word in ("кредит", "мфо", "микрозайм", "микрокредит", "ипотек", "рассроч"))


def access_reason(registration, identity_present, category, *, now=None):
    """Only two user-facing states: available or unavailable.

    Reason explains what the user must change, not extra offer statuses.
    """
    if not registration:
        return "registration"
    if age(registration["birth_date"]) < 18:
        return "underage"
    if not identity_present:
        return "identity"
    if credit_offer(category):
        import time
        now = now if now is not None else int(time.time())
        if now - registration["credit_updated_at"] > SURVEY_FRESH_DAYS * 86400:
            return "credit_review"
    return ""
