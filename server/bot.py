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
        url = app_url()
        is_owner = sender["id"] == admin_id()
        destination = url.rstrip("/") + "/admin/" if is_owner else url
        return {"method": "sendMessage", "chat_id": sender["id"],
                "text": "Номер сохранён. Откройте личный кабинет:",
                "reply_markup": {"inline_keyboard": [[{
                    "text": "Открыть админ-панель" if is_owner else "Открыть личный кабинет",
                    "web_app": {"url": destination}
                }]]} if url else {"remove_keyboard": True}}
    command = (message.get("text") or "").split(maxsplit=1)[0].split("@", 1)[0]
    if command in {"/start", "/app"}:
        url = app_url()
        if not url:
            return None
        if not has_contact:
            return {"method": "sendMessage", "chat_id": sender["id"],
                    "text": "Для доступа к кабинету поделитесь своим номером телефона кнопкой ниже.",
                    "reply_markup": {"keyboard": [[{"text": "Поделиться контактом", "request_contact": True}]],
                                     "resize_keyboard": True, "one_time_keyboard": True}}
        is_owner = sender["id"] == admin_id()
        destination = url.rstrip("/") + "/admin/" if is_owner else url
        return {
            "method": "sendMessage",
            "chat_id": sender["id"],
            "text": "The Affiliates Partners. Откройте административную панель:" if is_owner else "The Affiliates Partners. Откройте личный кабинет:",
            # Inline Web App buttons provide signed initData on supported Telegram
            # clients; reply-keyboard Web Apps may open without signed credentials.
            "reply_markup": {"inline_keyboard": [[{
                "text": "Открыть админ-панель" if is_owner else "Открыть личный кабинет",
                "web_app": {"url": destination}
            }]]},
        }
    if command == "/help":
        return {
            "method": "sendMessage",
            "chat_id": sender["id"],
            "text": "Команды: /start — открыть кабинет; /app — Mini App; /help — помощь.",
        }
    return None
