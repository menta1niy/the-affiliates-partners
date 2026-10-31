"""Tiny Telegram bot: menu and launch button; no legacy registration state."""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from server.settings import ROOT, app_url, bot_token


def telegram(method, payload):
    token = bot_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("Telegram returned an error")
    return result["result"]


def reply(chat_id, text, with_button=False):
    payload = {"chat_id": chat_id, "text": text}
    url = app_url()
    if with_button and url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "Открыть кабинет", "web_app": {"url": url}}]]
        }
    telegram("sendMessage", payload)


def process(update):
    message = update.get("message")
    if not isinstance(message, dict):
        return
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    if chat.get("type") != "private" or type(sender.get("id")) is not int:
        return
    if sender["id"] != chat.get("id"):
        return
    command = (message.get("text") or "").split(maxsplit=1)[0].split("@", 1)[0]
    if command in {"/start", "/app"}:
        reply(sender["id"], "The Affiliates Partners. Откройте личный кабинет:", True)
    elif command == "/help":
        reply(sender["id"], "Команды: /start — открыть кабинет; /app — ссылка на Mini App; /help — помощь.")


CURSOR_FILE = ROOT / ".runtime" / "bot_cursor.json"


def read_cursor():
    try:
        value = json.loads(CURSOR_FILE.read_text("utf-8"))["offset"]
        return value if type(value) is int and value >= 0 else None
    except (OSError, ValueError, TypeError, KeyError):
        return None


def save_cursor(offset):
    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CURSOR_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    os.replace(tmp, CURSOR_FILE)


def main():
    if not bot_token() or not app_url():
        raise SystemExit("Bot requires TELEGRAM_BOT_TOKEN and a HTTPS MINI_APP_URL")
    offset = read_cursor()
    print("Partners bot polling started", flush=True)
    while True:
        try:
            args = {"timeout": 25, "allowed_updates": ["message"]}
            if offset is not None:
                args["offset"] = offset
            updates = telegram("getUpdates", args)
            for update in updates:
                new_offset = update["update_id"] + 1
                if offset is not None and new_offset <= offset:
                    continue
                process(update)
                offset = new_offset
                save_cursor(offset)
        except urllib.error.HTTPError as exc:
            print(f"Telegram HTTP error {exc.code}; retrying", flush=True)
            time.sleep(5)
        except urllib.error.URLError as exc:
            # Do not log exc URLs: the Telegram API URL contains the bot token.
            print(f"Telegram network failure ({type(exc.reason).__name__}); retrying", flush=True)
            time.sleep(5)
        except (RuntimeError, TimeoutError, OSError) as exc:
            print(f"Telegram request failed ({type(exc).__name__}); retrying", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
