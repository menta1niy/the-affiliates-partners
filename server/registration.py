"""Minimal Telegram participant signup: only consent and adult confirmation."""
import os
import re

CONSENT_VERSION = "partners-registration-v1-2026-11-draft"


def normalize(payload):
    from server.db import Problem
    if (not isinstance(payload, dict)
            or payload.get("consent") is not True
            or payload.get("privacy_accepted") is not True
            or payload.get("terms_accepted") is not True):
        raise Problem(400, "Подтвердите условия и согласие на обработку данных")
    approved = os.environ.get("PARTNERS_LEGAL_APPROVED_VERSION", "").strip()
    if not approved and os.environ.get("PARTNERS_REQUIRE_APPROVED_LEGAL", "").lower() == "true":
        raise Problem(503, "Публичная регистрация недоступна до утверждения документов")
    if approved:
        if approved.endswith("-draft") or not re.fullmatch(r"partners-legal-v[0-9]+-[0-9]{4}-[0-9]{2}", approved):
            raise Problem(503, "Не настроена утверждённая версия юридических документов")
        if payload.get("legal_version") != approved:
            raise Problem(409, "Условия обновились. Подтвердите согласия заново")
    if payload.get("adult_confirmed") is not True:
        raise Problem(400, "Подтвердите, что вам исполнилось 18 лет")
    return {"consent_version": approved or CONSENT_VERSION}
