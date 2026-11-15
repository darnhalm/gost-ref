#!/usr/bin/env python3
"""Long-polling runner for the private Telegram catalog bot on macOS."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from telegram_bot import BotError, Settings, TelegramBot

LOGGER = logging.getLogger("gost-ref-telegram-polling")


class TelegramAPI:
    """Small asynchronous client for the Telegram Bot API."""

    def __init__(self, token: str):
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(65.0, connect=10.0),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def call(self, method: str, payload: dict[str, Any]) -> Any:
        response = await self.client.post(f"{self.base_url}/{method}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API rejected {method}")
        return data.get("result")

    async def updates(self, offset: int | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": 50,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = await self.call("getUpdates", payload)
        return result if isinstance(result, list) else []


class PollingRunner:
    def __init__(self, bot: TelegramBot, api: TelegramAPI):
        self.bot = bot
        self.api = api

    async def handle(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        callback_id = callback.get("id") if isinstance(callback, dict) else None
        if callback_id:
            try:
                await self.api.call(
                    "answerCallbackQuery", {"callback_query_id": callback_id},
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("callback acknowledgement failed: %s", type(exc).__name__)

        reply_token = self.bot.direct_reply.set(None)
        try:
            try:
                await self.bot.process(update)
            except BotError as exc:
                await self.bot._send_error(update, str(exc))  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("update failed: %s", type(exc).__name__)
                await self.bot._send_error(  # noqa: SLF001
                    update, "Сервис временно недоступен. Попробуйте позже.",
                )
            reply = self.bot.direct_reply.get()
        finally:
            self.bot.direct_reply.reset(reply_token)

        if reply is not None:
            method, payload = reply
            await self.api.call(method, payload)


async def run() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("missing TELEGRAM_BOT_TOKEN")
    api = TelegramAPI(token)
    runner = PollingRunner(TelegramBot(Settings.from_env()), api)
    offset: int | None = None
    delay = 1
    try:
        await api.call("deleteWebhook", {"drop_pending_updates": False})
        LOGGER.info("polling started")
        while True:
            try:
                for update in await api.updates(offset):
                    await runner.handle(update)
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                        LOGGER.info("processed update %s", update_id)
                delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("polling error: %s", type(exc).__name__)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
    finally:
        await api.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs complete request URLs; Telegram embeds the token in that URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        LOGGER.info("polling stopped")


if __name__ == "__main__":
    main()
