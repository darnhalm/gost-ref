#!/usr/bin/env python3
"""Small stdio MCP server for link-only Academia.edu search."""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.parse
from html.parser import HTMLParser
from typing import Any

import httpx


class ResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self.href = ""
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and "result__a" in (values.get("class") or "").split():
            self.href = values.get("href") or ""
            self.text = []

    def handle_data(self, data: str) -> None:
        if self.href:
            self.text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href:
            self.results.append((self.href, " ".join(self.text)))
            self.href = ""
            self.text = []


def clean_academia_url(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    if "uddg=" in value:
        value = (urllib.parse.parse_qs(parsed.query).get("uddg") or [value])[0]
        parsed = urllib.parse.urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in {"academia.edu", "www.academia.edu"}:
        return ""
    if not re.fullmatch(r"/\d{4,}(?:/[^?#]+)?/?", parsed.path):
        return ""
    return urllib.parse.urlunparse(
        ("https", "www.academia.edu", parsed.path.rstrip("/"), "", "", "")
    )


def search_academia(query: str, limit: int = 5) -> dict[str, Any]:
    query = " ".join(str(query or "").split())
    if not query or len(query) > 300:
        raise ValueError("query must contain 1-300 characters")
    limit = max(1, min(int(limit), 10))
    response = httpx.post(
        "https://html.duckduckgo.com/html/",
        data={"q": f"site:academia.edu/ {query}"},
        headers={"User-Agent": "Mozilla/5.0 (compatible; academia-search-mcp/0.1)"},
        timeout=25,
        follow_redirects=True,
    )
    response.raise_for_status()
    body = response.text
    parser = ResultParser()
    parser.feed(body)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, raw_title in parser.results:
        url = clean_academia_url(html.unescape(href))
        if not url or url in seen:
            continue
        title = html.unescape(" ".join(raw_title.split()))
        title = re.sub(r"^\(PDF\)\s*", "", title, flags=re.I)
        title = re.sub(r"\s*[|–-]\s*Academia(?:\.edu)?\s*$", "", title, flags=re.I)
        if not title:
            title = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1].replace("_", " ")
        results.append({"title": title[:400], "url": url})
        seen.add(url)
        if len(results) >= limit:
            break
    return {
        "query": query,
        "results": results,
        "result_count": len(results),
        "status": "candidates",
        "notice": (
            "Кандидаты из веб-поиска. Перед цитированием откройте страницу "
            "и сверьте заглавие и автора. Файлы не скачивались."
        ),
    }


TOOLS = [{
    "name": "search_academia",
    "description": (
        "Найти публичные страницы документов Academia.edu по названию, автору "
        "или теме. Возвращает только карточки-кандидаты и ссылки; не скачивает файлы."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 300},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}
        },
        "required": ["query"],
        "additionalProperties": False
    }
}]


def response(request_id: Any, result: Any = None, error: dict | None = None) -> None:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(message: dict[str, Any]) -> None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        response(request_id, {
            "protocolVersion": message.get("params", {}).get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "academia-search", "version": "0.1.0"},
        })
    elif method == "ping":
        response(request_id, {})
    elif method == "tools/list":
        response(request_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") != "search_academia":
            response(request_id, error={"code": -32601, "message": "unknown tool"})
            return
        try:
            arguments = params.get("arguments") or {}
            data = search_academia(arguments.get("query", ""), arguments.get("limit", 5))
            response(request_id, {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                "structuredContent": data,
                "isError": False,
            })
        except Exception as exc:  # noqa: BLE001 — convert to bounded MCP error
            response(request_id, {
                "content": [{"type": "text", "text": f"Поиск не выполнен: {type(exc).__name__}"}],
                "isError": True,
            })
    elif request_id is not None:
        response(request_id, error={"code": -32601, "message": "method not found"})


def main() -> None:
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if isinstance(message, dict):
                handle(message)
        except json.JSONDecodeError:
            continue


if __name__ == "__main__":
    main()
