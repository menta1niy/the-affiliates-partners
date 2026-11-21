"""Validated registration details for the standalone Telegram Mini App.

This data is intentionally distinct from Telegram display names, referral
attribution, bank approvals and later payout-identification documents.
"""
import re
import os
from datetime import date


CONSENT_VERSION = "partners-registration-v1-2026-11-draft"
MAX_CREDIT_PRODUCTS_PER_TYPE = 50
COUNTS = ("credit_cards", "installments", "loans", "mortgages")
SIMPLE_BANDS = ("0", "1-3", "3+")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize(payload):
    from server.db import Problem

    if (not isinstance(payload, dict)
            or payload.get("consent") is not True
            or payload.get("privacy_accepted") is not True
            or payload.get("terms_accepted") is not True):
        raise Problem(400, "Для регистрации необходимо принять условия и согласие на обработку данных")
    approved_version = os.environ.get("PARTNERS_LEGAL_APPROVED_VERSION", "").strip()
    if not approved_version and os.environ.get("PARTNERS_REQUIRE_APPROVED_LEGAL", "").strip().lower() == "true":
        raise Problem(503, "Публичная регистрация недоступна до утверждения юридических документов")
    if approved_version:
        if approved_version.endswith("-draft") or not re.fullmatch(r"partners-legal-v[0-9]+-[0-9]{4}-[0-9]{2}", approved_version):
            raise Problem(503, "Не настроена утверждённая версия юридических документов")
        if payload.get("legal_version") != approved_version:
            raise Problem(409, "Условия обновились. Ознакомьтесь с документами и подтвердите согласия заново")
    band = payload.get("credit_band")
    if band in SIMPLE_BANDS:
        if payload.get("adult_confirmed") is not True:
            raise Problem(400, "Подтвердите, что вам исполнилось 18 лет")
        return {"birth_date": "", **{field: 0 for field in COUNTS},
                "credit_band": band, "adult_confirmed": True,
                "consent_version": approved_version or CONSENT_VERSION}
    # Backward-compatible legacy clients and previously collected birth dates.
    if band is not None:
        raise Problem(400, "Выберите количество кредитных продуктов: 0, 1–3 или >3")
    birth_date = payload.get("birth_date")
    if not isinstance(birth_date, str) or not DATE_PATTERN.fullmatch(birth_date):
        raise Problem(400, "Введите дату рождения в формате ГГГГ-ММ-ДД")
    try:
        parsed = date.fromisoformat(birth_date)
    except ValueError:
        raise Problem(400, "Некорректная дата рождения") from None
    if parsed.year < 1900 or parsed > date.today():
        raise Problem(400, "Укажите действительную дату рождения")
    normalized = {"birth_date": parsed.isoformat()}
    for field in COUNTS:
        count = payload.get(field)
        if type(count) is not int or not 0 <= count <= MAX_CREDIT_PRODUCTS_PER_TYPE:
            raise Problem(400, "Укажите количество действующих кредитных продуктов (0–50)")
        normalized[field] = count
    total = sum(normalized[field] for field in COUNTS)
    normalized["credit_band"] = "0" if total == 0 else "1-3" if total <= 3 else "3+"
    normalized["adult_confirmed"] = age(parsed.isoformat()) >= 18
    normalized["consent_version"] = approved_version or CONSENT_VERSION
    return normalized


def age(birth_date, *, today=None):
    today = today or date.today()
    value = date.fromisoformat(birth_date)
    return today.year - value.year - ((today.month, today.day) < (value.month, value.day))


def credit_segment(counts):
    """A rough product-count classification, NOT a probability of approval."""
    total = sum(counts[field] for field in COUNTS)
    return "low_count" if total <= 1 else "medium_count" if total <= 3 else "high_count"


def public_view(row):
    if row is None:
        return None
    values = {field: row[field] for field in COUNTS}
    birth = row["birth_date"] or None
    total = sum(values.values())
    band = row["credit_band"] or ("0" if total == 0 else "1-3" if total <= 3 else "3+")
    return {
        "birth_date": birth,
        "age": age(birth) if birth else None,
        "adult_confirmed": bool(row["adult_confirmed"] or (birth and age(birth)>=18)),
        "credit_products": values,
        "credit_products_total": total if birth else None,
        "credit_band": band,
        "credit_segment": {"0":"low_count", "1-3":"medium_count", "3+":"high_count"}[band],
        "consent_version": row["consent_version"],
        "submitted_at": row["submitted_at"],
        "credit_updated_at": row["credit_updated_at"],
    }
