"""Verify Telegram Web App signed initData according to Telegram's HMAC scheme."""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl

MAX_AGE = 86400


def verify_init_data(data, token, now=None):
    """Return a safely normalized Telegram user or None. Never trust initDataUnsafe."""
    if not isinstance(data, str) or not isinstance(token, str) or not token:
        return None
    if not data or len(data) > 8192:
        return None
    try:
        pairs = parse_qsl(data, keep_blank_values=True, strict_parsing=True, max_num_fields=40)
        if len(pairs) != len({key for key, _ in pairs}):
            return None
        fields = dict(pairs)
        signature = fields.pop("hash", "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
            return None
        stamp = int(fields.get("auth_date", ""))
        now = int(now if now is not None else time.time())
        if stamp > now + 60 or now - stamp > MAX_AGE:
            return None
        secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
        check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        expected = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.lower()):
            return None
        user = json.loads(fields["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int:
            return None
        if not 0 < user["id"] <= 9223372036854775807:
            return None
        return {
            "id": user["id"],
            "first_name": str(user.get("first_name") or "Партнёр")[:120],
            "last_name": str(user.get("last_name") or "")[:120],
            "username": str(user.get("username") or "")[:120],
        }
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
