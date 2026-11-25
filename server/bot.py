"""Pure Telegram webhook message handler; never calls Telegram from the VPS."""
from server.settings import admin_id, app_url


def response_for(update, *, has_contact=False):
    if not isinstance(update, dict):
        return None
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    if type(sender.get("id")) is not int or sender["id"] != chat.get("id"):
        return None
    if chat.get("type") != "private":
        return None
    contact = message.get("contact")
    if isinstance(contact, dict):
        if contact.get("user_id") != sender["id"]:
            return {"method": "sendMessage", "chat_id": sender["id"],
                    "text": "Отправьте свой контакт кнопкой «Поделиться номером», а не чужой номер."}
        is_owner = sender["id"] == admin_id()
        return {"method": "sendMessage", "chat_id": sender["id"],
                "text": ("Номер сохранён. Откройте админ-панель кнопкой «Админ-панель» "
                         "слева от поля ввода сообщений." if is_owner else
                         "Номер сохранён. Откройте приложение кнопкой «Кабинет» "
                         "слева от поля ввода сообщений."),
                "reply_markup": {"remove_keyboard": True}}
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    command = text.split(maxsplit=1)[0].split("@", 1)[0]
    if command in {"/start", "/app"}:
        url = app_url()
        if not url:
            return None
        is_owner = sender["id"] == admin_id()
        if not has_contact and not is_owner:
            return {"method": "sendMessage", "chat_id": sender["id"],
                    "text": "Для доступа к кабинету поделитесь своим номером телефона кнопкой ниже.",
                    "reply_markup": {"keyboard": [[{"text": "Поделиться контактом", "request_contact": True}]],
                                     "resize_keyboard": True, "one_time_keyboard": True}}
        return {
            "method": "sendMessage",
            "chat_id": sender["id"],
            "text": ("Откройте админ-панель кнопкой «Админ-панель» "
                     "слева от поля ввода сообщений." if is_owner else
                     "Откройте приложение кнопкой «Кабинет» "
                     "слева от поля ввода сообщений."),
            "reply_markup": {"remove_keyboard": True},
        }
    if command == "/help":
        return {
            "method": "sendMessage",
            "chat_id": sender["id"],
            "text": "Команды: /start — открыть кабинет; /app — Mini App; /help — помощь.",
        }
    return None
