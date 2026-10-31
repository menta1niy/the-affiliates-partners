"""Read only the minimal private settings needed by the new application."""
import hashlib
import hmac
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {
    "TELEGRAM_BOT_TOKEN", "MINI_APP_URL", "ADMIN_TELEGRAM_ID", "SERVER_PORT",
    "PARTNERS_DB_PATH", "PARTNERS_DATABASE_URL", "PARTNERS_CRM_SHARED_SECRET",
    "PARTNERS_CRM_BASE_URL", "PARTNERS_CRM_WORKSPACE_ID",
}


def load_settings():
    local = ROOT / ".env.local"
    if local.is_file():
        for line in local.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in ALLOWED:
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))


load_settings()


def admin_id():
    value = os.environ.get("ADMIN_TELEGRAM_ID", "")
    return int(value) if value.isdecimal() else None


def bot_token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def webhook_secret():
    """Derive an independent webhook header secret from the existing bot token."""
    token = bot_token()
    if not token:
        return ""
    return hmac.new(token.encode("utf-8"), b"the-affiliates-partners-v2-inbound-webhook", hashlib.sha256).hexdigest()


def app_url():
    value = os.environ.get("MINI_APP_URL", "")
    return value if value.startswith("https://") else ""
