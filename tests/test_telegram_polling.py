from __future__ import annotations

import pytest

from telegram_bot import Settings, TelegramBot
from telegram_polling import PollingRunner
from test_telegram_bot import FakeGateway, _update


class FakeTelegramAPI:
    def __init__(self):
        self.calls = []

    async def call(self, method, payload):
        self.calls.append((method, payload))
        return True


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_polling_runner_sends_direct_reply():
    settings = Settings(
        webhook_secret="local-polling",
        gost_ref_url="https://protected.invalid",
        gost_ref_api_key="api-key",
        allowed_user_ids=frozenset({42}),
    )
    telegram = FakeTelegramAPI()
    runner = PollingRunner(TelegramBot(settings, gateway=FakeGateway()), telegram)

    await runner.handle(_update("/id", update_id=20))

    assert telegram.calls[0][0] == "sendMessage"
    assert "<code>42</code>" in telegram.calls[0][1]["text"]


@pytest.mark.anyio
async def test_polling_runner_acknowledges_callback():
    settings = Settings(
        webhook_secret="local-polling",
        gost_ref_url="https://protected.invalid",
        gost_ref_api_key="api-key",
        allowed_user_ids=frozenset({42}),
    )
    telegram = FakeTelegramAPI()
    runner = PollingRunner(TelegramBot(settings, gateway=FakeGateway()), telegram)
    update = {
        "update_id": 21,
        "callback_query": {
            "id": "callback-1",
            "from": {"id": 42},
            "data": "d:isbndb:9780892362509",
            "message": {"message_id": 8, "chat": {"id": 42}},
        },
    }

    await runner.handle(update)

    assert telegram.calls[0] == (
        "answerCallbackQuery", {"callback_query_id": "callback-1"},
    )
    assert telegram.calls[-1][0] == "sendMessage"
