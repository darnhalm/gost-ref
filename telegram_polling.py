#!/usr/bin/env python3
"""Long-polling runner for the private Telegram catalog bot on macOS."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import signal
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

    async def send_local_document(
        self, chat_id: int, path: str, caption: str = "",
    ) -> Any:
        document = Path(path).expanduser().resolve()
        if not document.is_file():
            raise RuntimeError("local document is missing")
        with document.open("rb") as stream:
            response = await self.client.post(
                f"{self.base_url}/sendDocument",
                data={"chat_id": str(chat_id), "caption": caption},
                files={"document": (document.name, stream, "application/pdf")},
                timeout=httpx.Timeout(900.0, connect=10.0),
            )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError("Telegram API rejected sendDocument")
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
            if method == "sendLocalDocument":
                path = str(payload["path"])
                try:
                    await self.api.send_local_document(
                        int(payload["chat_id"]), path, str(payload.get("caption") or ""),
                    )
                finally:
                    if payload.get("cleanup"):
                        Path(path).unlink(missing_ok=True)
            else:
                await self.api.call(method, payload)


async def restore_cloud_webhook(
    api: TelegramAPI,
    url: str,
    secret: str,
) -> bool:
    """Restore the cloud webhook after the optional local fallback stops."""
    url = str(url or "").strip()
    secret = str(secret or "").strip()
    if not url or not secret:
        return False
    await api.call("setWebhook", {
        "url": url,
        "secret_token": secret,
        "allowed_updates": ["message", "callback_query"],
    })
    return True


async def notify_local_started(
    api: TelegramAPI,
    user_ids: frozenset[int],
) -> int:
    """Tell allowlisted users that this Mac now handles Telegram updates."""
    delivered = 0
    for user_id in sorted(user_ids):
        try:
            await api.call("sendMessage", {
                "chat_id": user_id,
                "text": (
                    "🖥 <b>Локальный режим запущен.</b>\n"
                    "Telegram-поиск теперь обрабатывается на этом Mac. "
                    "При остановке скрипта бот автоматически вернётся в облако."
                ),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "local start notification failed for user %s: %s",
                user_id,
                type(exc).__name__,
            )
    return delivered


async def run() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("missing TELEGRAM_BOT_TOKEN")
    api = TelegramAPI(token)
    settings = Settings.from_env()
    runner = PollingRunner(TelegramBot(settings), api)
    restore_url = os.environ.get("TELEGRAM_RESTORE_WEBHOOK_URL", "").strip()
    restore_secret = os.environ.get(
        "TELEGRAM_RESTORE_WEBHOOK_SECRET", "",
    ).strip()
    offset: int | None = None
    delay = 1
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    handled_signals = []
    if task is not None:
        for signum in (signal.SIGTERM, signal.SIGHUP):
            try:
                loop.add_signal_handler(signum, task.cancel)
                handled_signals.append(signum)
            except (NotImplementedError, RuntimeError):
                pass
    try:
        await api.call("deleteWebhook", {"drop_pending_updates": False})
        notified = await notify_local_started(api, settings.allowed_user_ids)
        LOGGER.info("local start notification delivered to %s user(s)", notified)
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
        if restore_url and restore_secret:
            try:
                await asyncio.shield(restore_cloud_webhook(
                    api, restore_url, restore_secret,
                ))
                LOGGER.info("cloud webhook restored")
            except Exception as exc:  # noqa: BLE001
                LOGGER.error(
                    "cloud webhook restore failed: %s", type(exc).__name__,
                )
        for signum in handled_signals:
            loop.remove_signal_handler(signum)
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
    except asyncio.CancelledError:
        LOGGER.info("polling stopped; cloud mode requested")
    except KeyboardInterrupt:
        LOGGER.info("polling stopped")


if __name__ == "__main__":
    main()
