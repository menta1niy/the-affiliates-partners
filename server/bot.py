"""Telegram bot polling, dependency-free. Use only one bot instance."""
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

from config import load_local_env

load_local_env()
from app import ADMIN_ID, db

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


def app_button():
    if APP_URL.startswith("https://") and not APP_URL.endswith(".example") and ".example/" not in APP_URL:
        return {"inline_keyboard": [[{"text": "Открыть The Affiliates Partners", "web_app": {"url": APP_URL}}]]}
    return None


CONTACT_BUTTON = {"keyboard": [[{"text": "Поделиться контактом", "request_contact": True}]],
                  "resize_keyboard": True, "one_time_keyboard": True}


def normalized_phone(raw):
    """Accept Telegram contact numbers; store one canonical E.164-style value."""
    if not isinstance(raw, str) or not re.fullmatch(r"[+\d\s()\-]{10,24}", raw):
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if not 10 <= len(digits) <= 15:
        return None
    return "+" + digits


def notify_admin(uid, repeated=False):
    """Delivery is best-effort; registration is already committed to the shared DB."""
    kind = "Повторная заявка" if repeated else "Новая заявка"
    try:
        send(ADMIN_ID, f"{kind} партнёра: Telegram ID {uid}. Проверьте заявку в админ-панели.")
    except (urllib.error.URLError, RuntimeError, TimeoutError, OSError):
        print("Admin registration notification failed", flush=True)


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
    if type(uid) is not int or uid <= 0 or message["chat"].get("type") != "private" or cid != uid:
        return
    if uid == ADMIN_ID:
        if (message.get("text") or "").split(maxsplit=1)[0].split("@", 1)[0] == "/start" or message.get("contact") is not None:
            send(cid, "Администратор The Affiliates Partners. Откройте кабинет:", app_button())
        return
    with db() as con:
        profile = con.execute("SELECT status,phone FROM partners WHERE telegram_id=?", (uid,)).fetchone()
    contact = message.get("contact")
    if contact is not None:
        # A forwarded contact must never verify a different Telegram user.
        if not isinstance(contact, dict) or type(contact.get("user_id")) is not int or contact["user_id"] != uid:
            return send(cid, "Подтвердите собственный контакт кнопкой Telegram.")
        phone = normalized_phone(contact.get("phone_number"))
        if not phone:
            return send(cid, "Контакт не содержит номера телефона. Попробуйте ещё раз.")
        # Serialize check and update: two simultaneous contacts cannot claim the same number.
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT telegram_id FROM partners WHERE phone=? AND telegram_id<>?",
                (phone, uid)).fetchone()
            if not existing:
                current = con.execute("SELECT status,phone FROM partners WHERE telegram_id=?", (uid,)).fetchone()
                first_registration = not current or (not current[1] and current[0] == "pending")
                # Contact updates identity details but never overwrites an admin decision.
                con.execute("""INSERT INTO partners(telegram_id,username,name,phone,status,created_at)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                    username=excluded.username,name=excluded.name,phone=excluded.phone""",
                    (uid, sender.get("username") or "", sender.get("first_name") or "Партнёр", phone,
                     "pending", int(time.time())))
        if existing:
            return send(cid, "Этот номер уже привязан к другому Telegram-аккаунту. Обратитесь к администратору.")
        if first_registration:
            notify_admin(uid)
        with db() as con:
            profile = con.execute("SELECT status,phone FROM partners WHERE telegram_id=?", (uid,)).fetchone()
        send(cid, f"Номер {phone} привязан к вашему Telegram-аккаунту @{sender.get('username') or 'без username'}.",
             {"remove_keyboard": True})
        show_status(cid, profile[0], bool(profile[1]))
        return
    command = (message.get("text") or "").split(maxsplit=1)[0].split("@", 1)[0]
    if command == "/retry" and profile and profile[0] == "rejected":
        with db() as con:
            changed = con.execute("UPDATE partners SET status='pending' WHERE telegram_id=? AND status='rejected'", (uid,)).rowcount
        if profile[1]:
            if changed:
                notify_admin(uid, repeated=True)
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
