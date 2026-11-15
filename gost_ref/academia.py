"""Link-only discovery of Academia.edu document pages through web search."""

from __future__ import annotations

import base64
import html
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse, urlunparse

MAX_QUERY_CHARS = 300
SEARCH_URL = "https://html.duckduckgo.com/html/"
BING_URL = "https://www.bing.com/search"
YAHOO_URL = "https://search.yahoo.com/search"
READER_URL = "https://r.jina.ai/http://html.duckduckgo.com/html/"
ACADEMIA_READER_URL = "https://r.jina.ai/https://www.academia.edu/search"


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


class _BingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self._in_heading = False
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "h2":
            self._in_heading = True
        elif tag == "a" and self._in_heading:
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
        elif tag == "h2":
            self._in_heading = False


def _document_url(value: str) -> str:
    value = html.unescape(str(value or "").strip())
    parsed = urlparse(value)
    if "uddg=" in value:
        value = (parse_qs(parsed.query).get("uddg") or [value])[0]
        parsed = urlparse(value)
    if (parsed.hostname or "").lower().endswith("bing.com"):
        encoded = (parse_qs(parsed.query).get("u") or [""])[0]
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        if encoded:
            try:
                padding = "=" * (-len(encoded) % 4)
                value = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
                parsed = urlparse(value)
            except (ValueError, UnicodeDecodeError):
                return ""
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


def _get_bing_html(query: str) -> str:
    url = BING_URL + "?" + urllib.parse.urlencode({
        "q": f"site:academia.edu/ {query}", "cc": "US", "setlang": "en-US",
    })
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; gost-ref/1.1)"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8", "replace")


def _get_yahoo_html(query: str) -> str:
    url = YAHOO_URL + "?" + urllib.parse.urlencode({
        "p": f"site:academia.edu/ {query}",
    })
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; gost-ref/1.1)"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8", "replace")


def _get_reader_markdown(query: str) -> str:
    url = READER_URL + "?" + urllib.parse.urlencode({
        "q": f"site:academia.edu/ {query}",
    })
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; gost-ref/1.1)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def _get_academia_reader_markdown(query: str) -> str:
    url = ACADEMIA_READER_URL + "?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; gost-ref/1.1)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def _markdown_results(body: str) -> list[tuple[str, str]]:
    return [
        (href, title)
        for title, href in re.findall(
            r"\[([^\]\n]{4,500})\]\((https://duckduckgo\.com/l/\?uddg=[^)\s]+)\)",
            body,
            flags=re.I,
        )
    ]


def _academia_markdown_results(body: str) -> list[tuple[str, str]]:
    return [
        (href, title)
        for title, href in re.findall(
            r"\[([^\]\n]{4,500})\]\((https://www\.academia\.edu/[^)\s]+)\)",
            body,
            flags=re.I,
        )
    ]


def _embedded_results(body: str) -> list[tuple[str, str]]:
    """Extract result links without depending on a search engine's CSS classes."""
    decoded = html.unescape(body).replace(r"\/", "/")
    for _ in range(2):
        decoded = urllib.parse.unquote(decoded)

    results: list[tuple[str, str]] = []
    for href, label in re.findall(
        r'''<a\b[^>]*\bhref=["']([^"']+)["'][^>]*>(.*?)</a\s*>''',
        decoded,
        flags=re.I | re.S,
    ):
        title = re.sub(r"<[^>]+>", " ", label)
        results.append((href, title))

    for href in re.findall(
        r"https://(?:www\.)?academia\.edu/\d{4,}(?:/[^\s\"'<>?#&)]*)?",
        decoded,
        flags=re.I,
    ):
        results.append((href, ""))

    for encoded in re.findall(r"[?&]u=(a1[A-Za-z0-9_-]{20,})", decoded):
        results.append((f"https://www.bing.com/ck/a?u={encoded}", ""))
    return results


def _collect(raw_results: list[tuple[str, str]], limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, raw_title in raw_results:
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
    return results


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

    diagnostics: list[dict[str, object]] = []
    try:
        body = _post_html(query)
        diagnostics.append({"provider": "duckduckgo", "bytes": len(body)})
    except (OSError, urllib.error.URLError) as exc:
        body = ""
        diagnostics.append({
            "provider": "duckduckgo", "error": type(exc).__name__,
        })

    parser = _ResultParser()
    parser.feed(body)
    results = _collect(parser.results + _embedded_results(body), limit)
    if not results:
        try:
            bing_body = _get_bing_html(query)
            diagnostics.append({"provider": "bing", "bytes": len(bing_body)})
        except (OSError, urllib.error.URLError) as exc:
            bing_body = ""
            diagnostics.append({"provider": "bing", "error": type(exc).__name__})
        bing_parser = _BingParser()
        bing_parser.feed(bing_body)
        results = _collect(bing_parser.results + _embedded_results(bing_body), limit)
    if not results:
        try:
            yahoo_body = _get_yahoo_html(query)
            yahoo_raw = _embedded_results(yahoo_body)
            diagnostics.append({
                "provider": "yahoo",
                "bytes": len(yahoo_body),
                "links": len(yahoo_raw),
            })
        except (OSError, urllib.error.URLError) as exc:
            yahoo_raw = []
            diagnostics.append({"provider": "yahoo", "error": type(exc).__name__})
        results = _collect(yahoo_raw, limit)
    if not results:
        try:
            academia_body = _get_academia_reader_markdown(query)
            academia_raw = _academia_markdown_results(academia_body)
            diagnostics.append({
                "provider": "academia-reader",
                "bytes": len(academia_body),
                "links": len(academia_raw),
            })
        except (OSError, urllib.error.URLError) as exc:
            academia_body = ""
            academia_raw = []
            diagnostics.append({
                "provider": "academia-reader", "error": type(exc).__name__,
            })
        results = _collect(academia_raw, limit)
    if not results:
        try:
            reader_body = _get_reader_markdown(query)
            reader_raw = _markdown_results(reader_body)
            diagnostics.append({
                "provider": "duckduckgo-reader",
                "bytes": len(reader_body),
                "links": len(reader_raw),
            })
        except (OSError, urllib.error.URLError) as exc:
            reader_body = ""
            reader_raw = []
            diagnostics.append({
                "provider": "duckduckgo-reader", "error": type(exc).__name__,
            })
        results = _collect(reader_raw, limit)
    response = {
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
    if not results:
        response["diagnostics"] = diagnostics
    return response
