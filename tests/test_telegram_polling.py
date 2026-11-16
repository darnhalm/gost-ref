from __future__ import annotations

import pytest

pytest.importorskip("httpx")
pytest.importorskip("starlette")

from telegram_bot import Settings, TelegramBot
from telegram_polling import PollingRunner, restore_cloud_webhook
from test_telegram_bot import FakeGateway, _update


class FakeTelegramAPI:
    def __init__(self):
        self.calls = []

    async def call(self, method, payload):
        self.calls.append((method, payload))
        return True

    async def send_local_document(self, chat_id, path, caption=""):
        self.calls.append(("sendLocalDocument", {
            "chat_id": chat_id, "path": path, "caption": caption,
        }))
        return True


class FakeAcademiaDownload:
    download_available = True

    def __init__(self, path):
        self.path = path

    async def download(self, _url):
        return self.path


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


@pytest.mark.anyio
async def test_polling_runner_uploads_and_cleans_local_academia_pdf(tmp_path):
    document = tmp_path / "paper.pdf"
    document.write_bytes(b"%PDF-1.4\n")
    settings = Settings(
        webhook_secret="local-polling",
        gost_ref_url="https://protected.invalid",
        gost_ref_api_key="api-key",
        allowed_user_ids=frozenset({42}),
        academia_download_enabled=True,
    )
    telegram = FakeTelegramAPI()
    bot = TelegramBot(
        settings, gateway=FakeGateway(), academia=FakeAcademiaDownload(document),
    )
    runner = PollingRunner(bot, telegram)

    await runner.handle(_update(
        "/academia_get https://www.academia.edu/49699327/Test", update_id=22,
    ))

    assert telegram.calls[-1][0] == "sendLocalDocument"
    assert telegram.calls[-1][1]["path"] == str(document)
    assert not document.exists()


@pytest.mark.anyio
async def test_restore_cloud_webhook_after_local_fallback():
    telegram = FakeTelegramAPI()

    restored = await restore_cloud_webhook(
        telegram,
        "https://gateway.example/telegram/webhook",
        "webhook-secret",
    )

    assert restored is True
    assert telegram.calls == [("setWebhook", {
        "url": "https://gateway.example/telegram/webhook",
        "secret_token": "webhook-secret",
        "allowed_updates": ["message", "callback_query"],
    })]


@pytest.mark.anyio
async def test_restore_cloud_webhook_skips_missing_configuration():
    telegram = FakeTelegramAPI()

    assert await restore_cloud_webhook(telegram, "", "") is False
    assert telegram.calls == []
