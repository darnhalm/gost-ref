"""Link-only discovery of Academia.edu document pages through web search."""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse, urlunparse

MAX_QUERY_CHARS = 300
SEARCH_URL = "https://html.duckduckgo.com/html/"


class AcademiaSearchError(RuntimeError):
    pass


class _ResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and "result__a" in (values.get("class") or "").split():
            self._href = values.get("href") or ""
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.results.append((self._href, " ".join(self._text)))
            self._href = ""
            self._text = []


def _document_url(value: str) -> str:
    value = html.unescape(str(value or "").strip())
    parsed = urlparse(value)
    if "uddg=" in value:
        value = (parse_qs(parsed.query).get("uddg") or [value])[0]
        parsed = urlparse(value)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {
        "academia.edu", "www.academia.edu",
    }:
        return ""
    if not re.fullmatch(r"/\d{4,}(?:/[^?#]+)?/?", parsed.path):
        return ""
    return urlunparse(
        ("https", "www.academia.edu", parsed.path.rstrip("/"), "", "", "")
    )


def _post_html(query: str) -> str:
    data = urllib.parse.urlencode({"q": f"site:academia.edu/ {query}"}).encode()
    request = urllib.request.Request(
        SEARCH_URL,
        data=data,
        headers={"User-Agent": "Mozilla/5.0 (compatible; gost-ref/1.1)"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8", "replace")


def search(query: str, limit: int = 5) -> dict:
    """Return document-page candidates and never download document content."""
    query = " ".join(str(query or "").split())
    if not query or len(query) > MAX_QUERY_CHARS:
        raise AcademiaSearchError(f"query must contain 1-{MAX_QUERY_CHARS} characters")
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise AcademiaSearchError("limit must be an integer") from exc
    if not 1 <= limit <= 10:
        raise AcademiaSearchError("limit must be between 1 and 10")

    try:
        body = _post_html(query)
    except (OSError, urllib.error.URLError) as exc:
        raise AcademiaSearchError("web search provider unavailable") from exc

    parser = _ResultParser()
    parser.feed(body)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, raw_title in parser.results:
        url = _document_url(href)
        if not url or url in seen:
            continue
        title = html.unescape(" ".join(raw_title.split()))
        title = re.sub(r"^\(PDF\)\s*", "", title, flags=re.I)
        title = re.sub(r"\s*[|–-]\s*Academia(?:\.edu)?\s*$", "", title, flags=re.I)
        if not title:
            title = urlparse(url).path.rsplit("/", 1)[-1].replace("_", " ")
        results.append({"title": title[:400], "url": url})
        seen.add(url)
        if len(results) >= limit:
            break
    return {
        "query": query,
        "results": results,
        "result_count": len(results),
        "provider": "web search restricted to academia.edu",
        "status": "candidates",
        "notice": (
            "Кандидаты из веб-поиска. Перед цитированием откройте страницу "
            "и сверьте заглавие и автора. Файлы не скачивались."
        ),
    }
