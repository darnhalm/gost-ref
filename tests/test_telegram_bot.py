"""Telegram webhook tests; no real Telegram, MCP, or credentials are used."""

from __future__ import annotations

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient

from academia_local import AcademiaItem
from telegram_bot import Settings, create_app


class FakeGateway:
    def __init__(self):
        self.mcp_calls = []

    async def mcp(self, name, arguments):
        self.mcp_calls.append((name, arguments))
        if name == "search_catalog":
            return {
                "total": 22,
                "more_pages": True,
                "results": [{
                    "id": "isbndb:9780892362509",
                    "record_url": "https://example.invalid/record",
                    "fields": {
                        "title": "Historical & Philosophical Issues",
                        "authors": "Nicholas Stanley Price",
                        "publisher": "Getty Conservation Institute",
                        "year": "1996",
                    },
                }],
            }
        if name == "get_catalog_record":
            return {
                "id": arguments["record_id"],
                "fields": {
                    "type": "book",
                    "title": "Historical & Philosophical Issues",
                    "authors": "Nicholas Stanley Price",
                    "year": "1996",
                    "isbn": "9780892362509",
                },
                "identifiers": {"isbn13": ["9780892362509"]},
                "record_url": "https://example.invalid/record",
                "hash": "must-not-appear",
            }
        if name == "format_footnote_and_record":
            return {
                "footnote": {"text": "Price N. Historical issues. 1996."},
                "record": {"text": "Price N. Historical issues. — 1996."},
            }
        if name == "lookup_metadata":
            return {
                "fields": {
                    "type": "article",
                    "title": "Digital heritage in digital museums",
                    "authors": "Cary Karp",
                    "year": "2004",
                    "container": "Museum International",
                },
                "source": "OpenAlex, https://api.openalex.org/works/1",
            }
        raise AssertionError(name)


class FakeAcademia:
    download_available = True

    async def search(self, query, limit=5):
        return [AcademiaItem(
            title="Digital heritage in digital museums",
            url="https://www.academia.edu/49699327/Digital_heritage_in_digital_museums",
        )]


@pytest.fixture()
def bot():
    settings = Settings(
        webhook_secret="webhook-secret",
        gost_ref_url="https://protected.invalid",
        gost_ref_api_key="api-key",
        allowed_user_ids=frozenset({42}),
    )
    gateway = FakeGateway()
    return TestClient(create_app(settings, gateway, FakeAcademia())), gateway


def _update(text="/search 9780892362509", user_id=42, update_id=1):
    return {
        "update_id": update_id,
        "message": {
            "message_id": 7,
            "from": {"id": user_id},
            "chat": {"id": user_id},
            "text": text,
        },
    }


def _post(client, update, secret="webhook-secret"):
    return client.post(
        "/telegram/webhook", json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
    )


def test_webhook_rejects_wrong_secret(bot):
    client, gateway = bot
    response = _post(client, _update(), secret="wrong")
    assert response.status_code == 403
    assert gateway.mcp_calls == []


def test_search_uses_protected_catalog_and_builds_buttons(bot):
    client, gateway = bot
    response = _post(client, _update())
    assert response.status_code == 200
    assert gateway.mcp_calls == [(
        "search_catalog", {"query": "9780892362509", "page": 1, "limit": 5},
    )]
    payload = response.json()
    assert payload["method"] == "sendMessage"
    assert "Historical &amp; Philosophical Issues" in payload["text"]
    keyboard = payload["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0]["callback_data"] == "d:isbndb:9780892362509"
    assert keyboard[0][1]["callback_data"] == "g:isbndb:9780892362509"
    assert keyboard[0][2] == {
        "text": "1. Источник", "url": "https://example.invalid/record",
    }
    assert any(row[0].get("callback_data") == "p:2" for row in keyboard)
    assert keyboard[-1][0]["text"] == "Найти тексты в Academia.edu"


def test_plain_text_is_a_search(bot):
    client, gateway = bot
    _post(client, _update("Name of a book", update_id=2))
    assert gateway.mcp_calls[-1] == (
        "search_catalog", {"query": "Name of a book", "page": 1, "limit": 5},
    )


def test_unauthorized_user_can_only_get_own_id(bot):
    client, gateway = bot
    response = _post(client, _update("/id", user_id=99, update_id=3))
    assert "<code>99</code>" in response.json()["text"]
    assert gateway.mcp_calls == []

    response = _post(client, _update("secret title", user_id=99, update_id=4))
    assert "Доступ к поиску закрыт" in response.json()["text"]
    assert gateway.mcp_calls == []


def test_gost_callback_never_exposes_download_data(bot):
    client, gateway = bot
    update = {
        "update_id": 5,
        "callback_query": {
            "id": "callback-1",
            "from": {"id": 42},
            "data": "g:isbndb:9780892362509",
            "message": {"message_id": 8, "chat": {"id": 42}, "text": "details"},
        },
    }
    response = _post(client, update)
    assert [name for name, _ in gateway.mcp_calls] == [
        "get_catalog_record", "format_footnote_and_record",
    ]
    text = response.json()["text"]
    assert "Сноска" in text and "Список литературы" in text
    assert "must-not-appear" not in text


def test_details_include_source_page_button(bot):
    client, _gateway = bot
    update = {
        "update_id": 6,
        "callback_query": {
            "id": "callback-2",
            "from": {"id": 42},
            "data": "d:isbndb:9780892362509",
            "message": {"message_id": 9, "chat": {"id": 42}},
        },
    }
    response = _post(client, update)
    payload = response.json()
    assert "Страница источника" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][-1] == {
        "text": "Страница источника",
        "url": "https://example.invalid/record",
    }


def test_health_does_not_disclose_ids_or_tokens(bot):
    client, _gateway = bot
    assert client.get("/health").json() == {
        "status": "ok",
        "service": "gost-ref-telegram",
        "allowlist_configured": True,
    }


def test_academia_search_returns_candidate_links(bot):
    client, gateway = bot
    response = _post(client, _update("/academia museum heritage", update_id=7))
    payload = response.json()
    assert gateway.mcp_calls == []
    assert "Digital heritage in digital museums" in payload["text"]
    row = payload["reply_markup"]["inline_keyboard"][0]
    assert row[0]["url"].startswith("https://www.academia.edu/49699327/")
    assert row[1]["callback_data"].startswith("ag:")
