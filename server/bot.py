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


def queue_admin_notification(con, uid, repeated=False):
    """Queue an alert within the transaction that changes registration state."""
    kind = "Повторная заявка" if repeated else "Новая заявка"
    message = f"{kind} партнёра: Telegram ID {uid}. Проверьте заявку в админ-панели."
    con.execute("""CREATE TABLE IF NOT EXISTS bot_outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
        message TEXT NOT NULL, created_at INTEGER NOT NULL)""")
    con.execute("INSERT INTO bot_outbox(chat_id,message,created_at) VALUES(?,?,?)",
                (ADMIN_ID, message, int(time.time())))


def notify_admin(uid, repeated=False):
    """Enqueue a standalone alert (registration handlers enqueue in their transaction)."""
    with db() as con:
        queue_admin_notification(con, uid, repeated)
    flush_outbox()


def flush_outbox():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS bot_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            message TEXT NOT NULL, created_at INTEGER NOT NULL)""")
        pending = con.execute("SELECT id,chat_id,message FROM bot_outbox ORDER BY id LIMIT 20").fetchall()
    for event_id, chat_id, message in pending:
        try:
            send(chat_id, message)
        except (urllib.error.URLError, RuntimeError, TimeoutError, OSError):
            print("Admin registration notification deferred", flush=True)
            return
        with db() as con:
            con.execute("DELETE FROM bot_outbox WHERE id=?", (event_id,))


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
                if first_registration:
                    queue_admin_notification(con, uid)
        if existing:
            return send(cid, "Этот номер уже привязан к другому Telegram-аккаунту. Обратитесь к администратору.")
        if first_registration:
            flush_outbox()
        with db() as con:
            profile = con.execute("SELECT status,phone FROM partners WHERE telegram_id=?", (uid,)).fetchone()
        send(cid, f"Номер {phone} привязан к вашему Telegram-аккаунту @{sender.get('username') or 'без username'}.",
             {"remove_keyboard": True})
        show_status(cid, profile[0], bool(profile[1]))
        return
    command = (message.get("text") or "").split(maxsplit=1)[0].split("@", 1)[0]
    if command == "/retry" and profile and profile[0] == "rejected":
        if not profile[1]:
            return send(cid, "Для повторной заявки подтвердите собственный контакт, затем отправьте /retry.", CONTACT_BUTTON)
        with db() as con:
            changed = con.execute("""UPDATE partners SET status='pending'
                WHERE telegram_id=? AND status='rejected' AND phone<>''""", (uid,)).rowcount
            if changed:
                queue_admin_notification(con, uid, repeated=True)
        if changed:
            flush_outbox()
            send(cid, "Повторная заявка отправлена на рассмотрение.", {"remove_keyboard": True})
        else:
            with db() as con:
                current = con.execute("SELECT status,phone FROM partners WHERE telegram_id=?", (uid,)).fetchone()
            show_status(cid, current[0] if current else None, bool(current and current[1]))
    elif command in ("/start", "/retry"):
        show_status(cid, profile[0] if profile else None, bool(profile and profile[1]))


def process_update(update, offset):
    next_offset = update["update_id"] + 1
    if offset is not None and next_offset <= offset:
        return offset
    if "message" in update:
        handle(update["message"])
    with db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS bot_cursor (name TEXT PRIMARY KEY, next_update_id INTEGER NOT NULL)")
        con.execute("INSERT INTO bot_cursor(name,next_update_id) VALUES('polling',?) "
                    "ON CONFLICT(name) DO UPDATE SET next_update_id=excluded.next_update_id",
                    (next_offset,))
    return next_offset


def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    with db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS bot_cursor (name TEXT PRIMARY KEY, next_update_id INTEGER NOT NULL)")
        cursor = con.execute("SELECT next_update_id FROM bot_cursor WHERE name='polling'").fetchone()
    offset = cursor[0] if cursor else None
    print("Bot polling started. Do not run another process using this token.", flush=True)
    while True:
        try:
            flush_outbox()
            data = {"timeout": 30, "allowed_updates": ["message"]}
            if offset is not None:
                data["offset"] = offset
            for update in api("getUpdates", data):
                offset = process_update(update, offset)
        except (urllib.error.URLError, RuntimeError, TimeoutError) as err:
            print("Polling retry:", type(err).__name__, flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
