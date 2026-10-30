"""Read local configuration without logging secret values."""
import os
from pathlib import Path


def load_local_env():
    env_path = Path(__file__).resolve().parent.parent / '.env.local'
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key in {'TELEGRAM_BOT_TOKEN', 'MINI_APP_URL', 'ALLOWED_ORIGIN', 'SERVER_PORT',
                   'CRM_FEED_TOKEN', 'CRM_WORKSPACE_ID', 'PARTNERS_DB_PATH'}:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))
