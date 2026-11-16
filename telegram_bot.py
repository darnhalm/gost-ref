#!/usr/bin/env python3
"""Private Telegram interface for the protected gost-ref MCP service.

The bot exposes catalog metadata and GOST formatting.  Its optional local
Academia adapter searches public result links and can save a user-selected,
already accessible document without receiving the Anna provider key.
"""

from __future__ import annotations

import asyncio
import hmac
import html
import json
import logging
import os
import re
import secrets
import time
from collections import OrderedDict, defaultdict, deque
from contextvars import ContextVar
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from academia_local import AcademiaError, AcademiaItem, AcademiaLocal

LOGGER = logging.getLogger("gost-ref-telegram")
MAX_UPDATE_BYTES = 1_048_576
MAX_QUERY_CHARS = 300
MAX_MESSAGE_CHARS = 4000
WARM_BUTTON_TEXT = "🔥 Прогреть поиск"


class BotError(RuntimeError):
    """A safe, user-facing problem with a request."""


@dataclass(frozen=True)
class Settings:
    webhook_secret: str
    gost_ref_url: str
    gost_ref_api_key: str
    allowed_user_ids: frozenset[int]
    telegram_bot_token: str = ""
    request_timeout: float = 75.0
    rate_limit: int = 10
    rate_window: int = 60
    academia_download_enabled: bool = False
    academia_downloader_dir: str = ""
    academia_output_dir: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        required = {
            "TELEGRAM_WEBHOOK_SECRET": os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip(),
            "GOST_REF_URL": os.environ.get("GOST_REF_URL", "").strip(),
            "GOST_REF_API_KEY": os.environ.get("GOST_REF_API_KEY", "").strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"missing required environment: {', '.join(missing)}")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", required["TELEGRAM_WEBHOOK_SECRET"]):
            raise RuntimeError(
                "TELEGRAM_WEBHOOK_SECRET must contain only A-Z, a-z, 0-9, _ and -"
            )

        raw_ids = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").strip()
        try:
            allowed = frozenset(
                int(value.strip()) for value in raw_ids.split(",") if value.strip()
            )
        except ValueError as exc:
            raise RuntimeError("TELEGRAM_ALLOWED_USER_IDS must contain integers") from exc
        if any(value <= 0 for value in allowed):
            raise RuntimeError("Telegram user IDs must be positive integers")

        url = required["GOST_REF_URL"].rstrip("/")
        if urlparse(url).scheme not in {"http", "https"}:
            raise RuntimeError("GOST_REF_URL must be an HTTP(S) URL")
        return cls(
            webhook_secret=required["TELEGRAM_WEBHOOK_SECRET"],
            gost_ref_url=url,
            gost_ref_api_key=required["GOST_REF_API_KEY"],
            allowed_user_ids=allowed,
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            request_timeout=float(os.environ.get("TELEGRAM_REQUEST_TIMEOUT", "75")),
            rate_limit=int(os.environ.get("TELEGRAM_RATE_LIMIT", "10")),
            rate_window=int(os.environ.get("TELEGRAM_RATE_WINDOW", "60")),
            academia_download_enabled=os.environ.get(
                "ACADEMIA_DOWNLOAD_ENABLED", ""
            ).lower() in {"1", "true", "yes"},
            academia_downloader_dir=os.environ.get(
                "ACADEMIA_DOWNLOADER_DIR",
                "~/.codex/skill-runtimes/academiadl-py",
            ),
            academia_output_dir=os.environ.get(
                "ACADEMIA_OUTPUT_DIR", "~/Downloads/Academia",
            ),
        )


class Gateway:
    """HTTP boundary for the protected MCP service."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def warm(self) -> float:
        """Wake the protected MCP container and return elapsed seconds."""
        started = time.monotonic()
        timeout = min(self.settings.request_timeout, 25.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{self.settings.gost_ref_url}/health")
        if response.status_code != 200:
            raise RuntimeError(f"gost-ref health returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("gost-ref health returned invalid JSON") from exc
        if payload.get("status") != "ok":
            raise RuntimeError("gost-ref health is not ready")
        return time.monotonic() - started

    async def mcp(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-API-Key": self.settings.gost_ref_api_key,
        }
        async with httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
            response = await client.post(
                f"{self.settings.gost_ref_url}/mcp", json=payload, headers=headers,
            )
        if response.status_code != 200:
            raise RuntimeError(f"gost-ref returned HTTP {response.status_code}")

        body = response.text
        if body.lstrip().startswith("event:") or "\ndata:" in body:
            body = next(
                (line[5:] for line in body.splitlines() if line.startswith("data:")),
                "",
            )
        rpc = json.loads(body)
        if rpc.get("error"):
            raise RuntimeError("gost-ref returned an MCP error")
        content = rpc.get("result", {}).get("content", [])
        if not content or not isinstance(content[0].get("text"), str):
            raise RuntimeError("gost-ref returned no text result")
        result = json.loads(content[0]["text"])
        if not isinstance(result, dict):
            raise RuntimeError("gost-ref returned a non-object result")
        if result.get("error"):
            raise BotError("Каталожный сервис временно не дал результат. Попробуйте позже.")
        return result


class TelegramOutboundAPI:
    """Send cloud webhook results through Telegram after immediate acknowledgement."""

    def __init__(self, token: str):
        self.base_url = f"https://api.telegram.org/bot{token}"

    async def call(self, method: str, payload: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{self.base_url}/{method}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API rejected {method}")
        return data.get("result")


class RateLimiter:
    def __init__(self, limit: int, window: int):
        self.limit = max(1, limit)
        self.window = max(1, window)
        self.events: dict[int, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def allow(self, user_id: int) -> bool:
        now = time.monotonic()
        async with self.lock:
            events = self.events[user_id]
            while events and events[0] <= now - self.window:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


def _escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _display(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item)
    return str(value or "")


def _short(value: Any, limit: int = 240) -> str:
    text = " ".join(_display(value).split())
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def _safe_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _callback(prefix: str, value: str) -> str:
    data = f"{prefix}:{value}"
    return data if len(data.encode("utf-8")) <= 64 else ""


def _query_from_search_message(message: dict[str, Any]) -> str:
    text = str(message.get("text") or "")
    first = text.splitlines()[0] if text else ""
    marker = "🔎 Поиск: "
    return first[len(marker):].strip() if first.startswith(marker) else ""


class TelegramBot:
    def __init__(
        self,
        settings: Settings,
        gateway: Gateway | None = None,
        academia: AcademiaLocal | None = None,
        telegram_api: TelegramOutboundAPI | None = None,
    ):
        self.settings = settings
        self.gateway = gateway or Gateway(settings)
        self.telegram_api = telegram_api or (
            TelegramOutboundAPI(settings.telegram_bot_token)
            if settings.telegram_bot_token else None
        )
        self.rate = RateLimiter(settings.rate_limit, settings.rate_window)
        self.direct_reply: ContextVar[tuple[str, dict[str, Any]] | None] = ContextVar(
            "telegram_direct_reply", default=None,
        )
        self.seen_updates: OrderedDict[
            int, tuple[str, dict[str, Any]] | None
        ] = OrderedDict()
        self.academia = academia or AcademiaLocal(
            settings.academia_downloader_dir or "~/.codex/skill-runtimes/academiadl-py",
            settings.academia_output_dir or "~/Downloads/Academia",
        )
        self.academia_items: OrderedDict[str, AcademiaItem] = OrderedDict()
        self.academia_queries: OrderedDict[str, str] = OrderedDict()

    async def health(self, _request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "service": "gost-ref-telegram",
            "allowlist_configured": bool(self.settings.allowed_user_ids),
        })

    async def webhook(self, request: Request):
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(supplied, self.settings.webhook_secret):
            return PlainTextResponse("forbidden", status_code=403)
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            return PlainTextResponse("bad content length", status_code=400)
        if length > MAX_UPDATE_BYTES:
            return PlainTextResponse("too large", status_code=413)
        body = await request.body()
        if len(body) > MAX_UPDATE_BYTES:
            return PlainTextResponse("too large", status_code=413)
        try:
            update = json.loads(body)
        except json.JSONDecodeError:
            return PlainTextResponse("bad json", status_code=400)
        if not isinstance(update, dict):
            return PlainTextResponse("bad update", status_code=400)

        update_id = update.get("update_id")
        if isinstance(update_id, int):
            if update_id in self.seen_updates:
                return self._webhook_response(self.seen_updates[update_id])
        if self.telegram_api is not None:
            if isinstance(update_id, int):
                self.seen_updates[update_id] = None
                while len(self.seen_updates) > 1000:
                    self.seen_updates.popitem(last=False)
            return PlainTextResponse(
                "ok",
                background=BackgroundTask(self._process_outbound, update),
            )
        reply_token = self.direct_reply.set(None)
        try:
            await self.process(update)
        except BotError as exc:
            await self._send_error(update, str(exc))
        except Exception as exc:  # noqa: BLE001 — do not leak exception details
            LOGGER.error("update failed: %s", type(exc).__name__)
            await self._send_error(update, "Сервис временно недоступен. Попробуйте позже.")
        reply = self.direct_reply.get()
        self.direct_reply.reset(reply_token)
        if isinstance(update_id, int):
            self.seen_updates[update_id] = reply
            while len(self.seen_updates) > 1000:
                self.seen_updates.popitem(last=False)
        return self._webhook_response(reply)

    async def _process_outbound(self, update: dict[str, Any]) -> None:
        """Process an acknowledged cloud update and deliver its result separately."""
        if self.telegram_api is None:
            return
        callback = update.get("callback_query")
        callback_id = callback.get("id") if isinstance(callback, dict) else None
        if callback_id:
            try:
                await self.telegram_api.call(
                    "answerCallbackQuery", {"callback_query_id": callback_id},
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "callback acknowledgement failed: %s", type(exc).__name__,
                )

        reply_token = self.direct_reply.set(None)
        try:
            try:
                await self.process(update)
            except BotError as exc:
                await self._send_error(update, str(exc))
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("background update failed: %s", type(exc).__name__)
                await self._send_error(
                    update, "Сервис временно недоступен. Попробуйте позже.",
                )
            reply = self.direct_reply.get()
        finally:
            self.direct_reply.reset(reply_token)

        if reply is None:
            return
        method, payload = reply
        if method == "sendLocalDocument":
            LOGGER.error("cloud mode refused local document delivery")
            return
        try:
            await self.telegram_api.call(method, payload)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Telegram delivery failed: %s", type(exc).__name__)

    @staticmethod
    def _webhook_response(reply: tuple[str, dict[str, Any]] | None):
        if reply is None:
            return PlainTextResponse("ok")
        method, payload = reply
        return JSONResponse({"method": method, **payload})

    async def _emit(self, method: str, payload: dict[str, Any]) -> None:
        """Ask Telegram to execute one Bot API method from the webhook response."""
        self.direct_reply.set((method, payload))

    async def process(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        message = update.get("message")
        source = callback if isinstance(callback, dict) else message
        if not isinstance(source, dict):
            return
        sender = source.get("from") or {}
        user_id = sender.get("id")
        if not isinstance(user_id, int):
            return

        if isinstance(message, dict):
            text = str(message.get("text") or "").strip()
            if self._command(text)[0] == "/id":
                await self._send(message["chat"]["id"], f"Ваш Telegram ID: <code>{user_id}</code>")
                return

        if user_id not in self.settings.allowed_user_ids:
            chat_id = self._chat_id(update)
            if chat_id is not None:
                await self._send(
                    chat_id,
                    "Доступ к поиску закрыт. Отправьте <code>/id</code> владельцу бота.",
                )
            return
        if not await self.rate.allow(user_id):
            raise BotError("Слишком много запросов. Подождите минуту.")

        if isinstance(callback, dict):
            await self._callback(callback)
        elif isinstance(message, dict):
            await self._message(message)

    @staticmethod
    def _command(text: str) -> tuple[str, str]:
        if not text.startswith("/"):
            return "", text
        head, _, tail = text.partition(" ")
        return head.split("@", 1)[0].lower(), tail.strip()

    async def _message(self, message: dict[str, Any]) -> None:
        chat_id = message["chat"]["id"]
        text = str(message.get("text") or "").strip()
        command, value = self._command(text)
        if command in {"/start", "/help"}:
            await self._send(chat_id, self._help(), main_menu=True)
        elif command == "/warm" or text == WARM_BUTTON_TEXT:
            await self._warm(chat_id)
        elif command == "/search":
            if not value:
                raise BotError("Использование: /search название, автор или ISBN")
            await self._search(chat_id, value, 1)
        elif command == "/book":
            if not value:
                raise BotError("Использование: /book catalog:id")
            await self._details(chat_id, value)
        elif command == "/academia":
            if not value:
                raise BotError("Использование: /academia тема, название или автор")
            await self._academia_search(chat_id, value)
        elif command == "/academia_get":
            if not value:
                raise BotError("Использование: /academia_get https://www.academia.edu/…")
            await self._academia_download_url(chat_id, value)
        elif command:
            raise BotError("Неизвестная команда. Используйте /help.")
        elif text:
            await self._search(chat_id, text, 1)

    async def _warm(self, chat_id: int) -> None:
        elapsed = await self.gateway.warm()
        await self._send(
            chat_id,
            "✅ <b>Поиск готов.</b> MCP-контейнер отвечает "
            f"(прогрев: {elapsed:.1f} с). Можно отправлять запрос.",
            main_menu=True,
        )

    async def _callback(self, callback: dict[str, Any]) -> None:
        data = str(callback.get("data") or "")
        message = callback.get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        if chat_id is None:
            return
        prefix, _, value = data.partition(":")
        if prefix == "p" and value.isdigit():
            query = _query_from_search_message(message)
            if not query:
                raise BotError("Не удалось восстановить запрос. Отправьте его ещё раз.")
            await self._search(
                chat_id, query, int(value),
                edit_message_id=message.get("message_id"),
            )
        elif prefix == "d" and value:
            await self._details(chat_id, value)
        elif prefix == "g" and value:
            await self._gost(chat_id, value)
        elif prefix == "as" and value:
            query = self.academia_queries.get(value)
            if not query:
                raise BotError("Поисковый запрос устарел. Отправьте его ещё раз.")
            await self._academia_search(chat_id, query)
        elif prefix == "ag" and value:
            await self._academia_gost(chat_id, value)
        elif prefix == "ax" and value:
            await self._academia_download(chat_id, value)

    async def _search(
        self, chat_id: int, query: str, page: int,
        *, edit_message_id: int | None = None,
    ) -> None:
        query = " ".join(query.split())
        if not query or len(query) > MAX_QUERY_CHARS:
            raise BotError(f"Запрос должен содержать от 1 до {MAX_QUERY_CHARS} символов.")
        result = await self.gateway.mcp(
            "search_catalog", {"query": query, "page": page, "limit": 5},
        )
        items = result.get("results") or []
        lines = [f"🔎 Поиск: {_escape(query)}", f"Найдено: {_escape(result.get('total', 0))}"]
        keyboard: list[list[dict[str, str]]] = []
        if not items:
            lines.append("\nСовпадений не найдено.")
        for index, item in enumerate(items, 1):
            fields = item.get("fields") or {}
            title = _short(fields.get("title"), 180) or "Без заглавия"
            authors = _short(fields.get("authors"), 200)
            details = ", ".join(
                value for value in (
                    _short(fields.get("publisher"), 120),
                    _short(fields.get("year"), 30),
                    _short(fields.get("edition"), 120),
                ) if value
            )
            lines.append(f"\n<b>{index}. {_escape(title)}</b>")
            if authors:
                lines.append(_escape(authors))
            if details:
                lines.append(_escape(details))
            record_id = str(item.get("id") or "")
            detail_data = _callback("d", record_id)
            gost_data = _callback("g", record_id)
            source_url = _safe_url(item.get("record_url"))
            row = []
            if detail_data:
                row.append({"text": f"{index}. Подробнее", "callback_data": detail_data})
            if gost_data:
                row.append({"text": f"{index}. ГОСТ", "callback_data": gost_data})
            if source_url:
                row.append({"text": f"{index}. Источник", "url": source_url})
            if row:
                keyboard.append(row)

        pages = []
        if page > 1:
            pages.append({"text": "← Назад", "callback_data": f"p:{page - 1}"})
        if result.get("more_pages"):
            pages.append({"text": "Дальше →", "callback_data": f"p:{page + 1}"})
        if pages:
            keyboard.append(pages)
        query_token = self._remember_query(query)
        keyboard.append([{
            "text": "Найти тексты в Academia.edu",
            "callback_data": f"as:{query_token}",
        }])
        lines.append("\n<i>Это кандидаты. Перед цитированием сверьте карточку издания.</i>")
        payload = self._message_payload(chat_id, "\n".join(lines), keyboard)
        if edit_message_id is not None:
            payload["message_id"] = edit_message_id
            await self._emit("editMessageText", payload)
        else:
            await self._emit("sendMessage", payload)

    async def _details(self, chat_id: int, record_id: str) -> None:
        result = await self.gateway.mcp("get_catalog_record", {"record_id": record_id})
        fields = result.get("fields") or {}
        identifiers = result.get("identifiers") or {}
        lines = [f"📚 <b>{_escape(_short(fields.get('title'), 300) or 'Без заглавия')}</b>"]
        for label, key in (
            ("Авторы", "authors"), ("Издательство", "publisher"),
            ("Год", "year"), ("Издание", "edition"), ("Язык", "language"),
            ("ISBN", "isbn"),
        ):
            value = _short(fields.get(key), 400)
            if value:
                lines.append(f"<b>{label}:</b> {_escape(value)}")
        extra_ids = []
        for key, values in identifiers.items():
            value = _short(values, 200)
            if value and key not in {"isbn10", "isbn13"}:
                extra_ids.append(f"{key}: {value}")
        if extra_ids:
            lines.append(f"<b>Идентификаторы:</b> {_escape('; '.join(extra_ids))}")
        url = _safe_url(result.get("record_url"))
        if url:
            lines.append(f'<a href="{_escape(url)}">Страница источника</a> — сверьте издание')
        lines.append(f"<b>ID:</b> <code>{_escape(result.get('id') or record_id)}</code>")
        gost_data = _callback("g", str(result.get("id") or record_id))
        buttons = []
        if gost_data:
            buttons.append({"text": "Оформить по ГОСТ", "callback_data": gost_data})
        if url:
            buttons.append({"text": "Страница источника", "url": url})
        keyboard = [buttons] if buttons else []
        await self._send(chat_id, "\n".join(lines), keyboard)

    async def _gost(self, chat_id: int, record_id: str) -> None:
        record = await self.gateway.mcp("get_catalog_record", {"record_id": record_id})
        pair = await self.gateway.mcp(
            "format_footnote_and_record", {"fields": record.get("fields") or {}},
        )
        footnote = _short((pair.get("footnote") or {}).get("text") or "—", 1700)
        bibliography = _short((pair.get("record") or {}).get("text") or "—", 1700)
        text = (
            "📝 <b>Сноска</b>\n"
            f"{_escape(footnote)}\n\n"
            "📖 <b>Список литературы</b>\n"
            f"{_escape(bibliography)}\n\n"
            "<i>Проверьте карточку издания перед использованием.</i>"
        )
        await self._send(chat_id, text)

    def _remember_query(self, query: str) -> str:
        token = secrets.token_urlsafe(8)
        self.academia_queries[token] = query
        while len(self.academia_queries) > 200:
            self.academia_queries.popitem(last=False)
        return token

    def _remember_academia(self, item: AcademiaItem) -> str:
        token = secrets.token_urlsafe(8)
        self.academia_items[token] = item
        while len(self.academia_items) > 300:
            self.academia_items.popitem(last=False)
        return token

    async def _academia_search(self, chat_id: int, query: str) -> None:
        query = " ".join(query.split())
        if not query or len(query) > MAX_QUERY_CHARS:
            raise BotError(f"Запрос должен содержать от 1 до {MAX_QUERY_CHARS} символов.")
        try:
            items = await self.academia.search(query, limit=5)
        except AcademiaError as exc:
            raise BotError(str(exc)) from exc
        lines = [f"🎓 Поиск в Academia.edu: {_escape(query)}"]
        keyboard: list[list[dict[str, str]]] = []
        if not items:
            lines.append("\nПрямых страниц документов в веб-выдаче не найдено.")
        for index, item in enumerate(items, 1):
            token = self._remember_academia(item)
            lines.append(f"\n<b>{index}. {_escape(_short(item.title, 240))}</b>")
            if item.authors:
                lines.append(_escape(_short(item.authors, 180)))
            row = [
                {"text": f"{index}. Источник", "url": item.url},
                {"text": f"{index}. ГОСТ", "callback_data": f"ag:{token}"},
            ]
            if self.settings.academia_download_enabled and self.academia.download_available:
                row.append({"text": f"{index}. Скачать", "callback_data": f"ax:{token}"})
            keyboard.append(row)
        keyboard.append([{
            "text": "Открыть поиск Academia.edu",
            "url": f"https://www.academia.edu/search?q={quote_plus(query)}",
        }])
        lines.append(
            "\n<i>Это кандидаты из веб-поиска. Кнопка ГОСТ отдельно проверяет "
            "название по научным базам.</i>"
        )
        await self._send(chat_id, "\n".join(lines), keyboard)

    @staticmethod
    def _title_similarity(left: str, right: str) -> float:
        def clean(value: str) -> str:
            return re.sub(r"[^\w]+", " ", value.casefold()).strip()
        return SequenceMatcher(None, clean(left), clean(right)).ratio()

    async def _academia_gost(self, chat_id: int, token: str) -> None:
        item = self.academia_items.get(token)
        if not item:
            raise BotError("Результат устарел. Повторите поиск Academia.")
        lookup = await self.gateway.mcp(
            "lookup_metadata", {"query": item.title, "kind": "title"},
        )
        fields = lookup.get("fields") or {}
        found_title = str(fields.get("title") or "")
        if not found_title or self._title_similarity(item.title, found_title) < 0.62:
            await self._send(
                chat_id,
                "⚠️ Метаданных недостаточно для надёжного ГОСТ. Откройте источник "
                "и пришлите DOI, ISBN или первую страницу документа.",
                [[{"text": "Открыть Academia.edu", "url": item.url}]],
            )
            return
        pair = await self.gateway.mcp("format_footnote_and_record", {"fields": fields})
        footnote = _short((pair.get("footnote") or {}).get("text") or "—", 1600)
        bibliography = _short((pair.get("record") or {}).get("text") or "—", 1600)
        source_name = str(lookup.get("source") or "научная база").split(",", 1)[0]
        await self._send(
            chat_id,
            "📝 <b>Сноска</b>\n"
            f"{_escape(footnote)}\n\n"
            "📖 <b>Список литературы</b>\n"
            f"{_escape(bibliography)}\n\n"
            f"<i>Метаданные: {_escape(source_name)}. Название совпало; "
            "автора и издание всё равно сверьте на странице документа.</i>",
            [[{"text": "Открыть Academia.edu", "url": item.url}]],
        )

    async def _academia_download(self, chat_id: int, token: str) -> None:
        item = self.academia_items.get(token)
        if not item:
            raise BotError("Результат устарел. Повторите поиск Academia.")
        await self._academia_download_url(chat_id, item.url, title=item.title)

    async def _academia_download_url(
        self, chat_id: int, url: str, *, title: str = "Документ Academia.edu",
    ) -> None:
        if not self.settings.academia_download_enabled:
            raise BotError("Скачивание включается только в локальном режиме на Mac.")
        try:
            path = await self.academia.download(url)
        except AcademiaError as exc:
            raise BotError(str(exc)) from exc
        await self._emit("sendLocalDocument", {
            "chat_id": chat_id,
            "path": str(path),
            "caption": _short(title, 900),
            "cleanup": True,
        })

    async def _send_error(self, update: dict[str, Any], text: str) -> None:
        chat_id = self._chat_id(update)
        if chat_id is not None:
            await self._send(chat_id, f"⚠️ {_escape(text)}")

    @staticmethod
    def _chat_id(update: dict[str, Any]) -> int | None:
        message = update.get("message")
        if not isinstance(message, dict):
            message = (update.get("callback_query") or {}).get("message")
        chat_id = (message or {}).get("chat", {}).get("id")
        return chat_id if isinstance(chat_id, int) else None

    @staticmethod
    def _help() -> str:
        return (
            "<b>Поиск библиографических данных</b>\n\n"
            "Отправьте название, автора или ISBN обычным сообщением либо:\n"
            "<code>/search запрос</code> — найти издания\n"
            "<code>/warm</code> — прогреть поиск перед работой\n"
            "<code>/book catalog:id</code> — открыть запись\n"
            "<code>/academia запрос</code> — найти страницы Academia.edu\n"
            "<code>/academia_get URL</code> — локально сохранить доступный документ\n"
            "<code>/id</code> — показать ваш Telegram ID\n\n"
            "Бот ищет метаданные, открывает страницу источника и оформляет ГОСТ. "
            "Сохранение Academia работает только при ручном запуске на Mac."
        )

    @staticmethod
    def _message_payload(
        chat_id: int, text: str, keyboard: list[list[dict[str, str]]] | None = None,
        *, main_menu: bool = False,
    ) -> dict[str, Any]:
        if len(text) > MAX_MESSAGE_CHARS:
            cutoff = text.rfind("\n", 0, MAX_MESSAGE_CHARS - 40)
            text = text[:cutoff if cutoff > 0 else MAX_MESSAGE_CHARS - 40]
            text += "\n<i>Сообщение сокращено.</i>"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        elif main_menu:
            payload["reply_markup"] = {
                "keyboard": [[{"text": WARM_BUTTON_TEXT}]],
                "resize_keyboard": True,
                "is_persistent": True,
            }
        return payload

    async def _send(
        self, chat_id: int, text: str,
        keyboard: list[list[dict[str, str]]] | None = None,
        *, main_menu: bool = False,
    ) -> None:
        await self._emit(
            "sendMessage",
            self._message_payload(chat_id, text, keyboard, main_menu=main_menu),
        )


def create_app(
    settings: Settings | None = None,
    gateway: Gateway | None = None,
    academia: AcademiaLocal | None = None,
    telegram_api: TelegramOutboundAPI | None = None,
) -> Starlette:
    bot = TelegramBot(
        settings or Settings.from_env(),
        gateway=gateway,
        academia=academia,
        telegram_api=telegram_api,
    )
    app = Starlette(routes=[
        Route("/health", bot.health, methods=["GET"]),
        Route("/telegram/webhook", bot.webhook, methods=["POST"]),
    ])
    app.state.bot = bot
    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    uvicorn.run(
        create_app(),
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
