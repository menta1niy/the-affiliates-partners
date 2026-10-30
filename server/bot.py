"""Telegram bot polling, dependency-free. Use only one bot instance."""
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

from config import load_local_env

load_local_env()
from app import DB, db

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
APP_URL = os.environ.get("MINI_APP_URL", "")
API = f"https://api.telegram.org/bot{TOKEN}/"


def api(method, payload):
    req = urllib.request.Request(API + method, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = json.load(response)
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram API error"))
    return data["result"]


def send(chat_id, text, markup=None):
    body = {"chat_id": chat_id, "text": text}
    if markup:
        body["reply_markup"] = markup
    api("sendMessage", body)


def handle(message):
    sender = message.get("from", {})
    uid = sender.get("id")
    cid = message["chat"]["id"]
    if not isinstance(uid, int) or message["chat"].get("type") != "private":
        return
    contact = message.get("contact")
    if contact:
        # A forwarded contact must never verify a different Telegram user.
        if contact.get("user_id") != uid:
            return send(cid, "Подтвердите собственный контакт кнопкой Telegram.")
        phone = contact.get("phone_number", "")
        if not phone:
            return
        with db() as con:
            con.execute("""INSERT INTO partners(telegram_id,username,name,phone,status,created_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,name=excluded.name,phone=excluded.phone""",
                (uid, sender.get("username") or "", sender.get("first_name") or "Партнёр", phone,
                 "pending", int(time.time())))
        markup = {"remove_keyboard": True}
        send(cid, "Номер сохранён. Ваша заявка партнёра ожидает одобрения.", markup)
        if APP_URL.startswith("https://") and not APP_URL.endswith(".example") and ".example/" not in APP_URL:
            send(cid, "Откройте кабинет:", {"inline_keyboard": [[{"text": "Открыть The Affiliates Partners", "web_app": {"url": APP_URL}}]]})
        return
    if message.get("text", "").startswith("/start"):
        send(cid, "The Affiliates Partners. Для регистрации поделитесь собственным контактом.",
             {"keyboard": [[{"text": "Поделиться контактом", "request_contact": True}]],
              "resize_keyboard": True, "one_time_keyboard": True})


def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    db().close()
    offset = None
    print("Bot polling started. Do not run another process using this token.", flush=True)
    while True:
        try:
            data = {"timeout": 30, "allowed_updates": ["message"]}
            if offset is not None:
                data["offset"] = offset
            for update in api("getUpdates", data):
                offset = update["update_id"] + 1
                if "message" in update:
                    try:
                        handle(update["message"])
                    except (urllib.error.URLError, RuntimeError, sqlite3.Error) as err:
                        print("Message handling failed:", type(err).__name__, flush=True)
        except (urllib.error.URLError, RuntimeError, TimeoutError) as err:
            print("Polling retry:", type(err).__name__, flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
