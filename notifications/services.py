"""Small HTTP client for the Telegram Bot API."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings


class TelegramConfigurationError(RuntimeError):
    """Raised when Telegram credentials are not configured."""


class TelegramDeliveryError(RuntimeError):
    """Raised when Telegram rejects a message or cannot be reached."""


def send_telegram_message(text):
    """Send a plain-text message to the configured Telegram chat."""
    bot_token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not bot_token or not chat_id:
        raise TelegramConfigurationError(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable notifications."
        )

    request = Request(
        url=f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=urlencode({"chat_id": chat_id, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise TelegramDeliveryError(
            f"Telegram returned HTTP {error.code}."
        ) from None
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        # The exception may contain the request URL, which includes the bot token.
        raise TelegramDeliveryError("Telegram request failed.") from None

    if not isinstance(result, dict) or not result.get("ok"):
        raise TelegramDeliveryError("Telegram rejected the notification.")

    return result.get("result", {}).get("message_id")
