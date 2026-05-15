"""
integrations/telegram_client.py
=================================
Replaces Twilio completely. Free forever.
No A2P registration. No monthly fees. No carrier BS.

Fred sends messages via Telegram Bot API.
You chat with Fred in the Telegram app.
Everything works identically to SMS — trades, photos, commands, all of it.
"""

import logging
import asyncio
from typing import Optional

import httpx

from config.settings import settings

logger = logging.getLogger("fred.telegram")


class TelegramClient:
    """
    Sends and receives messages via Telegram Bot API.
    Drop-in replacement for TwilioClient.
    """

    def __init__(self):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self._seen_update_ids: set[int] = set()
        logger.info("TelegramClient initialized")

    # ── Send message ──────────────────────────────────────────────────────────

    def send(self, message: str, alert_key: Optional[str] = None, to: Optional[str] = None) -> bool:
        """
        Send a message to the trader.
        Drop-in replacement for twilio_client.send()
        """
        chat_id = to or self.chat_id
        if not chat_id:
            logger.warning("No Telegram chat_id configured — skipping message")
            return False

        try:
            import requests
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info(f"Telegram message sent: {message[:60]}...")
                return True
            else:
                logger.error(f"Telegram send failed: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    def send_response(self, message: str, to: Optional[str] = None) -> bool:
        """Alias for send() — matches Twilio interface."""
        return self.send(message, to=to)

    async def send_async(self, message: str, chat_id: Optional[str] = None) -> bool:
        """Async version for use in async contexts."""
        cid = chat_id or self.chat_id
        if not cid:
            return False

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": cid,
                        "text": message,
                        "parse_mode": "HTML",
                    },
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram async send error: {e}")
            return False

    # ── Set webhook ───────────────────────────────────────────────────────────

    async def set_webhook(self, railway_url: str) -> bool:
        """
        Tell Telegram where to send incoming messages.
        Called once at startup.
        """
        webhook_url = f"{railway_url}/telegram/incoming"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/setWebhook",
                    json={"url": webhook_url},
                    timeout=10,
                )
                data = resp.json()
                if data.get("ok"):
                    logger.info(f"Telegram webhook set: {webhook_url}")
                    return True
                else:
                    logger.error(f"Webhook set failed: {data}")
                    return False
        except Exception as e:
            logger.error(f"Set webhook error: {e}")
            return False

    # ── Health check ──────────────────────────────────────────────────────────

    def check_connection(self) -> bool:
        """Test if bot token is valid."""
        try:
            import requests
            resp = requests.get(f"{self.base_url}/getMe", timeout=5)
            if resp.status_code == 200:
                bot = resp.json().get("result", {})
                logger.info(f"Telegram bot connected: @{bot.get('username')}")
                return True
            return False
        except Exception as e:
            logger.error(f"Telegram health check failed: {e}")
            return False


# Global singleton — replaces twilio_client
telegram_client = TelegramClient()
