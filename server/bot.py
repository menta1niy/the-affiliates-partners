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
from app import db

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
APP_URL = os.environ.get("MINI_APP_URL", "")
API = f"https://api.telegram.org/bot{TOKEN}/"
ADMIN_ID = 758398804


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


def app_button():
    if APP_URL.startswith("https://") and not APP_URL.endswith(".example") and ".example/" not in APP_URL:
        return {"inline_keyboard": [[{"text": "Открыть The Affiliates Partners", "web_app": {"url": APP_URL}}]]}
    return None


CONTACT_BUTTON = {"keyboard": [[{"text": "Поделиться контактом", "request_contact": True}]],
                  "resize_keyboard": True, "one_time_keyboard": True}


def show_status(cid, status, has_phone):
    if status == "active":
        send(cid, "Ваш аккаунт партнёра активен. Откройте кабинет:", app_button())
    elif status == "pending" and has_phone:
        send(cid, "Ваша заявка находится на рассмотрении.", {"remove_keyboard": True})
    elif status == "rejected":
        send(cid, "Заявка отклонена. Если хотите подать её повторно, отправьте /retry.",
             {"remove_keyboard": True})
    else:
        send(cid, "The Affiliates Partners. Для регистрации поделитесь собственным контактом.",
             CONTACT_BUTTON)


def handle(message):
    sender = message.get("from", {})
    uid = sender.get("id")
    cid = message["chat"]["id"]
    if not isinstance(uid, int) or message["chat"].get("type") != "private":
        return
    with db() as con:
        profile = con.execute("SELECT status,phone FROM partners WHERE telegram_id=?", (uid,)).fetchone()
    contact = message.get("contact")
    if contact is not None:
        # A forwarded contact must never verify a different Telegram user.
        if not isinstance(contact, dict) or type(contact.get("user_id")) is not int or contact["user_id"] != uid:
            return send(cid, "Подтвердите собственный контакт кнопкой Telegram.")
        phone = contact.get("phone_number", "")
        if not isinstance(phone, str) or not phone.strip():
            return send(cid, "Контакт не содержит номера телефона. Попробуйте ещё раз.")
        # A contact can update user details, but cannot change an approval decision.
        first_registration = not profile or (not profile[1] and profile[0] == "pending")
        with db() as con:
            con.execute("""INSERT INTO partners(telegram_id,username,name,phone,status,created_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,name=excluded.name,phone=excluded.phone""",
                (uid, sender.get("username") or "", sender.get("first_name") or "Партнёр", phone,
                 "pending", int(time.time())))
        if first_registration:
            try:
                send(ADMIN_ID, f"Новая заявка партнёра: Telegram ID {uid}. Проверьте заявку в админ-панели.")
            except (urllib.error.URLError, RuntimeError, TimeoutError):
                print("Admin registration notification failed", flush=True)
        with db() as con:
            profile = con.execute("SELECT status,phone FROM partners WHERE telegram_id=?", (uid,)).fetchone()
        show_status(cid, profile[0], bool(profile[1]))
        return
    command = (message.get("text") or "").split(maxsplit=1)[0].split("@", 1)[0]
    if command == "/retry" and profile and profile[0] == "rejected":
        with db() as con:
            con.execute("UPDATE partners SET status='pending' WHERE telegram_id=? AND status='rejected'", (uid,))
        if profile[1]:
            send(cid, "Повторная заявка отправлена на рассмотрение.", {"remove_keyboard": True})
        else:
            send(cid, "Для повторной заявки подтвердите собственный контакт.", CONTACT_BUTTON)
    elif command in ("/start", "/retry"):
        show_status(cid, profile[0] if profile else None, bool(profile and profile[1]))


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
