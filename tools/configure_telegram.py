"""Reconfigure BotFather-equivalent commands/menu via Bot API. Safe dry-run default."""
import argparse
import json
import urllib.request

from server.settings import app_url, bot_token, webhook_secret


def call(method, body):
    token = bot_token()
    if not token:
        raise SystemExit("Missing Telegram token")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(f"{method}: Telegram refused the request")
    return result.get("result")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write Bot API settings")
    args = parser.parse_args()
    url = app_url()
    if not url:
        raise SystemExit("MINI_APP_URL must start with https://")
    cmds = [
        {"command": "start", "description": "Открыть партнёрский кабинет"},
        {"command": "app", "description": "Запустить Mini App"},
        {"command": "help", "description": "Помощь по боту"},
    ]
    print("Bot menu target:", url)
    print("Webhook target:", url.rstrip("/") + "/api/telegram/webhook")
    print("Commands:", ", ".join(command["command"] for command in cmds))
    if not args.apply:
        print("DRY RUN. Pass --apply to change BotFather menu and commands.")
        return
    result = call("getMe", {})
    print("Confirmed bot:", result["username"])
    call("setMyCommands", {"commands": cmds})
    call("setChatMenuButton", {
        "menu_button": {"type": "web_app", "text": "Кабинет", "web_app": {"url": url}}
    })
    call("setWebhook", {
        "url": url.rstrip("/") + "/api/telegram/webhook",
        "secret_token": webhook_secret(),
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
    })
    info = call("getWebhookInfo", {})
    if info.get("url") != url.rstrip("/") + "/api/telegram/webhook":
        raise RuntimeError("Telegram did not confirm the webhook URL")
    print("Bot commands, menu and HTTPS webhook updated.")


if __name__ == "__main__":
    main()
