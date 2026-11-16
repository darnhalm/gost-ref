"""Conservative RSL catalog adapter: browser search and verified record extraction.

No undocumented RSL API, scraping of search results, or automatic verification.
"""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import quote, urlparse

RECORD_RE = re.compile(r"^/ru/record/([0-9]{8,12})/?$")
BASE = "https://search.rsl.ru"


def search_instructions(title: str = "", author: str = "", isbn: str = "") -> dict:
    """Return official RSL professional-search expression for a browser user."""
    terms = []
    for field, value in (("title", title), ("author", author), ("isbn", isbn)):
        value = " ".join(str(value or "").split())
        if value:
            if any(ch in value for ch in "\r\n"):
                raise ValueError("invalid query")
            terms.append(f'{field}:"{value.replace(chr(34), "")}"' if field != "isbn" else f"isbn:{value}")
    if not terms:
        raise ValueError("provide title, author or ISBN")
    query = " ".join(terms)
    return {"provider": "РГБ", "query": query, "url": BASE + "/ru/search",
            "status": "browser_search_required", "verified": False,
            "instructions": "Open the official RSL search and paste query into Professional Search."}


def record_url(record_id: str) -> str:
    if not re.fullmatch(r"[0-9]{8,12}", str(record_id)):
        raise ValueError("invalid RSL record id")
    return f"{BASE}/ru/record/{record_id}"


def record_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "search.rsl.ru":
        raise ValueError("not an official HTTPS RSL record URL")
    match = RECORD_RE.fullmatch(parsed.path)
    if not match or parsed.query or parsed.fragment:
        raise ValueError("invalid RSL record URL")
    return match.group(1)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("p", "div", "tr", "td", "th", "h1", "h2", "h3", "br"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag in ("p", "div", "tr", "td", "th", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def parse_record_html(url: str, html: str) -> dict:
    """Extract labeled candidate fields; require human confirmation of the page."""
    rid = record_id_from_url(url)
    parser = _Text()
    parser.feed(html)
    lines = [" ".join(x.split()) for x in "".join(parser.parts).splitlines()]
    lines = [x for x in lines if x]
    labels = {"Заглавие": "title", "Выходные данные": "imprint",
              "Физическое описание": "extent", "Язык": "language",
              "Шифр хранения": "shelfmark"}
    fields = {}
    for i, line in enumerate(lines):
        for label, key in labels.items():
            if line == label and i + 1 < len(lines):
                fields.setdefault(key, lines[i + 1])
            elif line.startswith(label + " ") and len(line) > len(label) + 1:
                fields.setdefault(key, line[len(label):].strip())
    return {"provider": "РГБ", "record_id": rid, "record_url": record_url(rid),
            "fields": fields, "verified": False,
            "verification_required": "Open the record in a browser; confirm title, author and edition against the actual page and title leaf."}
