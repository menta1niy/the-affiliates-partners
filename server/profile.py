"""Shared Fernet encryption used by private payout details and offer evidence."""
import os

from server import db


def _cipher():
    secret = os.environ.get("PARTNERS_PROFILE_ENCRYPTION_KEY", "")
    if not secret:
        raise db.Problem(503, "Защищённое хранение реквизитов пока не настроено")
    try:
        from cryptography.fernet import Fernet
        return Fernet(secret.encode("ascii"))
    except (ImportError, ValueError, TypeError):
        raise db.Problem(503, "Неправильно настроено защищённое хранение реквизитов") from None
