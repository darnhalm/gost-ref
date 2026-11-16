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


def parse_marc21_text(url: str, marc_text: str) -> dict:
    """Parse human-readable MARC21 field listing, without network access.

    Supports lines such as '245 10 $a Title : $b subtitle / $c author'.
    Keeps the legacy HTML parser available as fallback.
    """
    rid = record_id_from_url(url)
    tags = {}
    for raw in str(marc_text or "").splitlines():
        line = raw.strip()
        match = re.match(r"^(?:=)?(\\d{3})\\s+(?:[0-9 #\\\\]{0,2}\\s+)?(.*)$", line)
        if match:
            tags.setdefault(match.group(1), []).append(match.group(2))
    def subfields(tag):
        for line in tags.get(tag, []):
            found = re.findall(r"(?:\\$|\\|)([a-z0-9])\\s*([^$|]+)", line, re.I)
            if found:
                yield {k.lower(): " ".join(v.split()).rstrip(" /:;,.") for k, v in found}
    fields = {}
    for item in subfields("245"):
        if item.get("a"):
            fields["title"] = item["a"]
            if item.get("b"):
                fields["subtitle"] = item["b"]
            if item.get("c"):
                fields["responsibility"] = item["c"]
            break
    for tag in ("100", "110", "111"):
        for item in subfields(tag):
            if item.get("a"):
                fields["author"] = item["a"]
                break
        if "author" in fields:
            break
    for tag in ("264", "260"):
        for item in subfields(tag):
            for key, name in (("a", "city"), ("b", "publisher"), ("c", "year")):
                if item.get(key) and name not in fields:
                    fields[name] = item[key]
        if any(x in fields for x in ("city", "publisher", "year")):
            break
    for item in subfields("300"):
        if item.get("a"):
            fields["extent"] = item["a"]
            break
    for item in subfields("020"):
        if item.get("a"):
            fields["isbn"] = item["a"]
            break
    return {"provider": "РГБ", "record_id": rid, "record_url": record_url(rid),
            "fields": fields, "format": "marc21_text", "verified": False,
            "verification_required": "Confirm parsed fields against the official record and title page."}


def parse_record_with_fallback(url: str, marc_text: str = "", html: str = "") -> dict:
    """Prefer MARC21 only when it yields a title; otherwise preserve legacy HTML."""
    if marc_text:
        try:
            candidate = parse_marc21_text(url, marc_text)
            if candidate["fields"].get("title"):
                candidate["parser_used"] = "marc21"
                return candidate
        except (TypeError, ValueError):
            pass
    candidate = parse_record_html(url, html or "")
    candidate["parser_used"] = "html_fallback"
    return candidate
