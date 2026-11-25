"""Pure Telegram webhook message handler; never calls Telegram from the VPS."""
from server.settings import admin_id, app_url


def response_for(update):
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
        return {"method": "sendMessage", "chat_id": sender["id"],
                "text": "Номер сохранён. Откройте кабинет через /app.",
                "reply_markup": {"remove_keyboard": True}}
    command = (message.get("text") or "").split(maxsplit=1)[0].split("@", 1)[0]
    if command in {"/start", "/app"}:
        url = app_url()
        if not url:
            return None
        is_owner = sender["id"] == admin_id()
        destination = url.rstrip("/") + "/admin/" if is_owner else url
        return {
            "method": "sendMessage",
            "chat_id": sender["id"],
            "text": "The Affiliates Partners. Откройте административную панель:" if is_owner else "The Affiliates Partners. Откройте личный кабинет:",
            "reply_markup": {"keyboard": [
                [{"text": "Открыть кабинет", "web_app": {"url": destination}}],
                [{"text": "Поделиться номером", "request_contact": True}]
            ], "resize_keyboard": True},
        }
    if command == "/help":
        return {
            "method": "sendMessage",
            "chat_id": sender["id"],
            "text": "Команды: /start — открыть кабинет; /app — Mini App; /help — помощь.",
        }
    return None
