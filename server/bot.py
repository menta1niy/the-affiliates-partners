"""Pure Telegram webhook message handler; never calls Telegram from the VPS."""
from server.settings import app_url


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
    command = (message.get("text") or "").split(maxsplit=1)[0].split("@", 1)[0]
    if command in {"/start", "/app"}:
        url = app_url()
        if not url:
            return None
        return {
            "method": "sendMessage",
            "chat_id": sender["id"],
            "text": "The Affiliates Partners. Откройте личный кабинет:",
            "reply_markup": {
                "inline_keyboard": [[{"text": "Открыть кабинет", "web_app": {"url": url}}]]
            },
        }
    if command == "/help":
        return {
            "method": "sendMessage",
            "chat_id": sender["id"],
            "text": "Команды: /start — открыть кабинет; /app — Mini App; /help — помощь.",
        }
    return None
