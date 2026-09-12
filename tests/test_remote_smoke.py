"""Smoke-тест удалённого режима: HTTP-обвязка, не библиография.

Проверяет ровно то, что добавила serverless-сборка, и ничего сверх того:
поднимается ли сервер, отвечает ли health, требуется ли токен, проходит ли
handshake MCP, работает ли основной вызов и выдерживает ли сервер
одновременные независимые запросы.

Правильность самих записей по ГОСТ проверяют tests/test_gost.py — здесь
сравнивается только то, что HTTP отдаёт тот же результат, что и ядро.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx", reason="нужен httpx (pip install -e '.[dev]')")
pytest.importorskip("mcp", reason="нужен MCP SDK (pip install -e '.[server]')")

ROOT = Path(__file__).resolve().parent.parent
API_KEY = "test-secret-token"
ACCEPT = "application/json, text/event-stream"

SAMPLE = {
    "type": "article",
    "authors": "Козаченко Ю. В.",
    "title": "Заглавие статьи",
    "container": "Аспирант и соискатель",
    "year": "2018",
    "issue": "2 (104)",
    "pages": "19-21",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    """Сервер как отдельный процесс — так же, как его запустит контейнер."""
    port = _free_port()
    env = {
        **os.environ,
        "GOST_REF_API_KEY": API_KEY,
        "GOST_REF_JSON_RESPONSE": "1",   # без SSE ответ разбирается проще
        "PYTHONPATH": str(ROOT),
    }
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "server.py"), "--transport", "streamable-http",
         "--host", "127.0.0.1", "--port", str(port)],
        env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if proc.poll() is not None:
            pytest.fail(f"сервер не поднялся: {proc.communicate()[1].decode()[:800]}")
        try:
            if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("health не ответил за 10 с")

    yield base
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()


def _call(base: str, method: str, params: dict | None = None,
          token: str | None = API_KEY, timeout: float = 30) -> httpx.Response:
    """Один запрос stateless-режима: без mcp-session-id и без initialized."""
    headers = {"Content-Type": "application/json", "Accept": ACCEPT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return httpx.post(f"{base}/mcp", json=payload, headers=headers, timeout=timeout)


def _result(response: httpx.Response) -> dict:
    assert response.status_code == 200, response.text
    body = response.text
    if body.lstrip().startswith("event:") or "\ndata:" in body:  # SSE
        body = next(line[5:] for line in body.splitlines() if line.startswith("data:"))
    data = json.loads(body)
    assert "error" not in data, data["error"]
    return data["result"]


# --------------------------------------------------------------------------

def test_health_open_and_stateless(server):
    """Health отвечает без токена и не заводит сессию."""
    response = httpx.get(f"{server}/health", timeout=5)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "gost-ref"}


def test_mcp_requires_token(server):
    response = _call(server, "tools/list", token=None)
    assert response.status_code == 401
    assert "bearer" in response.headers.get("www-authenticate", "").lower()

    response = _call(server, "tools/list", token="wrong-token")
    assert response.status_code == 401


def test_initialize_and_tools_list(server):
    result = _result(_call(server, "initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "smoke", "version": "0"},
    }))
    assert result["serverInfo"]["name"] == "gost-ref"

    names = {tool["name"] for tool in _result(_call(server, "tools/list"))["tools"]}
    assert names == {
        "list_source_types", "format_reference", "format_footnote_and_record",
        "format_all_standards", "reformat_reference", "parse_reference",
        "validate_reference", "build_bibliography", "repeat_reference",
        "lookup_metadata", "read_pdf_metadata", "check_links",
    }


def test_format_footnote_and_record_matches_core(server):
    """Основной вызов по HTTP даёт ровно то же, что прямой вызов ядра."""
    from gost_ref import api

    result = _result(_call(server, "tools/call", {
        "name": "format_footnote_and_record", "arguments": {"fields": SAMPLE},
    }))
    over_http = json.loads(result["content"][0]["text"])
    assert over_http == api.format_pair(SAMPLE)
    assert over_http["footnote"]["text"]
    assert over_http["record"]["text"]


def test_read_pdf_metadata_refuses_arbitrary_paths(server):
    """В remote-режиме без GOST_REF_PDF_DIR произвольный файл не читается."""
    for path in ("/etc/passwd", "../../etc/passwd", str(ROOT / "server.py")):
        result = _result(_call(server, "tools/call", {
            "name": "read_pdf_metadata", "arguments": {"path": path},
        }))
        answer = json.loads(result["content"][0]["text"])
        assert "error" in answer, answer
        assert "root:" not in json.dumps(answer)


def test_concurrent_independent_requests(server):
    """Десять параллельных запросов не перемешиваются между собой."""
    years = [str(2010 + i) for i in range(10)]

    def one(year: str) -> str:
        result = _result(_call(server, "tools/call", {
            "name": "format_reference",
            "arguments": {"fields": {**SAMPLE, "year": year}},
        }))
        return json.loads(result["content"][0]["text"])["reference"]

    with ThreadPoolExecutor(max_workers=10) as pool:
        rendered = list(pool.map(one, years))

    assert len(set(rendered)) == 10
    for year, line in zip(years, rendered):
        assert year in line


def test_http_mode_refuses_to_start_without_key():
    """Публичный HTTP без GOST_REF_API_KEY не поднимается."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("GOST_REF_API_KEY", "GOST_REF_ALLOW_ANONYMOUS")}
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "server.py"), "--transport", "streamable-http",
         "--port", str(_free_port())],
        env=env, cwd=str(ROOT), capture_output=True, timeout=60,
    )
    assert proc.returncode == 2
    assert "GOST_REF_API_KEY" in proc.stderr.decode()
