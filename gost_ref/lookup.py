"""Поиск недостающих метаданных во внешних базах.

Каждая функция возвращает {'fields': {...}, 'source': '...', 'raw': {...}}
и НИКОГДА не додумывает поля: чего нет в ответе базы — того нет в результате.
Поле `source` обязательно, чтобы каждый факт можно было проверить руками.

Открытые базы, работающие без ключа:
  Crossref   — DOI, научные статьи и книги с DOI
  OpenAlex   — то же плюс метаданные организаций и цитирования
  OpenLibrary / Google Books — ISBN, книги
  CyberLeninka — русскоязычная научная периодика
  DataCite   — DOI датасетов, препринтов, диссертаций

РИНЦ (eLibrary.ru) открытого API не имеет и закрыт от автоматических запросов.
`elibrary_search_url()` строит ссылку для ручной проверки — по ней запись
сверяется глазами или браузерным инструментом. То же для РГБ и Гостов.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "gost-ref/1.0 (bibliographic formatter; mailto:noreply@example.org)"
TIMEOUT = 20


class LookupError(RuntimeError):
    pass


def _get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        raise LookupError(f"{type(exc).__name__}: {exc}") from exc


def _post_json(url: str, payload: dict) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        raise LookupError(f"{type(exc).__name__}: {exc}") from exc


def _clean_text(value: str) -> str:
    """Снимает HTML-разметку и переносы строк, которыми грешат ответы баз."""
    s = re.sub(r"<[^>]+>", "", str(value or ""))
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", s).strip()


def _clean_doi(doi: str) -> str:
    return re.sub(r"^(?:doi:?\s*|https?://(?:dx\.)?doi\.org/)", "", str(doi or "").strip(), flags=re.I)


# --------------------------------------------------------------------------
# Crossref
# --------------------------------------------------------------------------

def by_doi(doi: str) -> dict[str, Any]:
    """Метаданные по DOI из Crossref; при неудаче — DataCite."""
    clean = _clean_doi(doi)
    if not clean:
        raise LookupError("пустой DOI")
    url = f"https://api.crossref.org/works/{urllib.parse.quote(clean)}"
    try:
        data = _get_json(url)
        return {
            "fields": _from_crossref(data.get("message", {})),
            "source": f"Crossref, {url}",
            "raw": data.get("message", {}),
        }
    except LookupError:
        return by_datacite(clean)


def by_crossref_title(query: str) -> dict[str, Any]:
    """Поиск по заглавию в Crossref (`query.bibliographic`).

    OpenAlex тянет из Crossref, но не всё и с задержкой, поэтому Crossref
    спрашиваем напрямую как второй независимый индекс.
    """
    q = str(query or "").strip()
    if not q:
        raise LookupError("пустой запрос")
    url = ("https://api.crossref.org/works?rows=5&select=DOI,title,author,"
           "container-title,issued,volume,issue,page,ISSN,type,publisher&"
           "query.bibliographic=" + urllib.parse.quote(q))
    data = _get_json(url)
    items = ((data or {}).get("message") or {}).get("items") or []
    if not items:
        raise LookupError("ничего не найдено")

    results = [{"fields": _from_crossref(item), "doi": item.get("DOI")}
               for item in items]
    return {"fields": results[0]["fields"], "source": f"Crossref, {url}",
            "candidates": results, "raw": items[0]}


_TEXT_FIELDS = ("title", "subtitle", "container", "publisher", "city")


def _sanitize(fields: dict[str, Any]) -> dict[str, Any]:
    for key in _TEXT_FIELDS:
        if fields.get(key):
            fields[key] = _clean_text(fields[key])

    people = []
    for person in fields.get("authors") or []:
        if isinstance(person, str):
            people.append(_person_from_name(person))
            continue
        for key in ("surname", "given"):
            if person.get(key):
                person[key] = _clean_text(person[key])
        if person.get("surname") and not person.get("given") and " " in person["surname"]:
            people.append(_person_from_name(person["surname"]))
        else:
            people.append(person)
    if people:
        fields["authors"] = people

    # «Заглавие: подзаголовок» из зарубежных баз разносим по областям
    title = fields.get("title") or ""
    if title and not fields.get("subtitle") and re.search(r"\S:\s+\S", title):
        head, tail = re.split(r":\s+", title, maxsplit=1)
        if len(head) > 10 and len(tail) > 3:
            fields["title"] = head.strip()
            fields["subtitle"] = tail.strip()
    return fields


def _person_from_name(name: str) -> dict[str, str]:
    """«Вязинкин Алексей Юрьевич» → {surname, given}; «Megan Rancier» → тоже."""
    from .model import Person
    p = Person.parse(_clean_text(name))
    out = {"surname": p.surname}
    if p.given:
        out["given"] = p.given
    if p.initials:
        out["initials"] = p.initials
    return out


def _from_crossref(item: dict) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    kind = (item.get("type") or "").lower()
    if "journal-article" in kind or "proceedings-article" in kind:
        fields["type"] = "article"
    elif "book-chapter" in kind:
        fields["type"] = "chapter"
    elif "book" in kind or "monograph" in kind:
        fields["type"] = "book"
    elif "dissertation" in kind:
        fields["type"] = "dissertation"
    else:
        fields["type"] = "article"

    authors = []
    for a in item.get("author") or []:
        family = a.get("family") or ""
        given = a.get("given") or ""
        if family:
            authors.append({"surname": family, "given": given})
        elif a.get("name"):
            authors.append({"surname": a["name"]})
    if authors:
        fields["authors"] = authors

    titles = item.get("title") or []
    if titles:
        fields["title"] = titles[0]
    subtitles = item.get("subtitle") or []
    if subtitles:
        fields["subtitle"] = subtitles[0]

    containers = item.get("container-title") or []
    if containers:
        fields["container"] = containers[0]

    if item.get("publisher") and fields["type"] in ("book", "chapter"):
        fields["publisher"] = item["publisher"]
    if item.get("publisher-location"):
        fields["city"] = item["publisher-location"]

    parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    if parts and parts[0]:
        fields["year"] = str(parts[0])

    if item.get("volume"):
        fields["volume"] = str(item["volume"])
    if item.get("issue"):
        fields["issue"] = str(item["issue"])
    if item.get("page"):
        fields["pages"] = str(item["page"])
    if item.get("DOI"):
        fields["doi"] = item["DOI"]
    isbns = item.get("ISBN") or []
    if isbns:
        fields["isbn"] = isbns[0]
    issns = item.get("ISSN") or []
    if issns:
        fields["issn"] = issns[0]
    return _sanitize(fields)


def by_datacite(doi: str) -> dict[str, Any]:
    clean = _clean_doi(doi)
    url = f"https://api.datacite.org/dois/{urllib.parse.quote(clean)}"
    data = _get_json(url)
    attrs = (data.get("data") or {}).get("attributes", {})
    fields: dict[str, Any] = {"doi": clean}
    titles = attrs.get("titles") or []
    if titles:
        fields["title"] = titles[0].get("title", "")
    authors = []
    for c in attrs.get("creators") or []:
        if c.get("familyName"):
            authors.append({"surname": c["familyName"], "given": c.get("givenName", "")})
        elif c.get("name"):
            authors.append({"surname": c["name"]})
    if authors:
        fields["authors"] = authors
    if attrs.get("publisher"):
        fields["publisher"] = attrs["publisher"]
    if attrs.get("publicationYear"):
        fields["year"] = str(attrs["publicationYear"])
    if attrs.get("url"):
        fields["url"] = attrs["url"]
    return {"fields": _sanitize(fields), "source": f"DataCite, {url}", "raw": attrs}


# --------------------------------------------------------------------------
# OpenAlex
# --------------------------------------------------------------------------

def by_openalex(query: str) -> dict[str, Any]:
    """Поиск по заглавию или DOI в OpenAlex."""
    q = str(query or "").strip()
    if not q:
        raise LookupError("пустой запрос")
    if re.match(r"^10\.\d{4,9}/", _clean_doi(q)):
        url = f"https://api.openalex.org/works/doi:{urllib.parse.quote(_clean_doi(q))}"
        item = _get_json(url)
        items = [item]
    else:
        url = ("https://api.openalex.org/works?per-page=5&search="
               + urllib.parse.quote(q))
        items = (_get_json(url) or {}).get("results", [])
    if not items:
        raise LookupError("ничего не найдено")

    results = []
    for item in items:
        fields: dict[str, Any] = {}
        if item.get("title"):
            fields["title"] = item["title"]
        authors = []
        for a in item.get("authorships") or []:
            name = ((a.get("author") or {}).get("display_name") or "").strip()
            if name:
                bits = name.split()
                authors.append({"surname": bits[-1], "given": " ".join(bits[:-1])})
        if authors:
            fields["authors"] = authors
        loc = (item.get("primary_location") or {}).get("source") or {}
        if loc.get("display_name"):
            fields["container"] = loc["display_name"]
        if loc.get("issn_l"):
            fields["issn"] = loc["issn_l"]
        if item.get("publication_year"):
            fields["year"] = str(item["publication_year"])
        bib = item.get("biblio") or {}
        if bib.get("volume"):
            fields["volume"] = bib["volume"]
        if bib.get("issue"):
            fields["issue"] = bib["issue"]
        if bib.get("first_page") and bib.get("last_page"):
            fields["pages"] = f"{bib['first_page']}-{bib['last_page']}"
        if item.get("doi"):
            fields["doi"] = _clean_doi(item["doi"])
        fields["type"] = "article"
        results.append({"fields": _sanitize(fields), "openalex_id": item.get("id")})

    return {"fields": results[0]["fields"], "source": f"OpenAlex, {url}",
            "candidates": results, "raw": items[0]}


# --------------------------------------------------------------------------
# ISBN
# --------------------------------------------------------------------------

def by_isbn(isbn: str) -> dict[str, Any]:
    """OpenLibrary, при неудаче — Google Books."""
    clean = re.sub(r"[^0-9Xx]", "", str(isbn or ""))
    if not clean:
        raise LookupError("пустой ISBN")
    url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{clean}&format=json&jscmd=data"
    try:
        data = _get_json(url)
        item = data.get(f"ISBN:{clean}")
        if item:
            fields: dict[str, Any] = {"type": "book", "isbn": isbn}
            if item.get("title"):
                fields["title"] = item["title"]
            if item.get("subtitle"):
                fields["subtitle"] = item["subtitle"]
            authors = []
            for a in item.get("authors") or []:
                bits = (a.get("name") or "").split()
                if bits:
                    authors.append({"surname": bits[-1], "given": " ".join(bits[:-1])})
            if authors:
                fields["authors"] = authors
            pubs = item.get("publishers") or []
            if pubs:
                fields["publisher"] = pubs[0].get("name", "")
            places = item.get("publish_places") or []
            if places:
                fields["city"] = places[0].get("name", "")
            if item.get("publish_date"):
                m = re.search(r"(1[5-9]\d{2}|20\d{2})", item["publish_date"])
                if m:
                    fields["year"] = m.group(1)
            if item.get("number_of_pages"):
                fields["total_pages"] = str(item["number_of_pages"])
            return {"fields": _sanitize(fields), "source": f"OpenLibrary, {url}", "raw": item}
    except LookupError:
        pass

    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean}"
    data = _get_json(url)
    items = data.get("items") or []
    if not items:
        raise LookupError("ISBN не найден ни в OpenLibrary, ни в Google Books")
    info = items[0].get("volumeInfo", {})
    fields = {"type": "book", "isbn": isbn}
    if info.get("title"):
        fields["title"] = info["title"]
    if info.get("subtitle"):
        fields["subtitle"] = info["subtitle"]
    authors = []
    for name in info.get("authors") or []:
        bits = name.split()
        authors.append({"surname": bits[-1], "given": " ".join(bits[:-1])})
    if authors:
        fields["authors"] = authors
    if info.get("publisher"):
        fields["publisher"] = info["publisher"]
    if info.get("publishedDate"):
        m = re.search(r"(1[5-9]\d{2}|20\d{2})", info["publishedDate"])
        if m:
            fields["year"] = m.group(1)
    if info.get("pageCount"):
        fields["total_pages"] = str(info["pageCount"])
    return {"fields": _sanitize(fields), "source": f"Google Books, {url}", "raw": info}


# --------------------------------------------------------------------------
# Русскоязычные базы
# --------------------------------------------------------------------------

def by_cyberleninka(query: str) -> dict[str, Any]:
    """Полнотекстовый поиск по русскоязычной периодике КиберЛенинки."""
    q = str(query or "").strip()
    if not q:
        raise LookupError("пустой запрос")
    data = _post_json("https://cyberleninka.ru/api/search",
                      {"mode": "articles", "q": q, "size": 5, "from": 0})
    items = data.get("articles") or []
    if not items:
        raise LookupError("в КиберЛенинке ничего не найдено")
    item = items[0]
    fields: dict[str, Any] = {"type": "article"}
    if item.get("name"):
        fields["title"] = re.sub(r"<[^>]+>", "", item["name"])
    if item.get("authors"):
        fields["authors"] = [{"surname": a} for a in item["authors"]]
    if item.get("journal"):
        fields["container"] = item["journal"]
    if item.get("year"):
        fields["year"] = str(item["year"])
    if item.get("link"):
        fields["url"] = f"https://cyberleninka.ru{item['link']}"
        fields["medium"] = "electronic"
    return {"fields": _sanitize(fields), "source": "CyberLeninka, https://cyberleninka.ru/api/search",
            "candidates": items, "raw": item}


def elibrary_search_url(query: str) -> str:
    """РИНЦ автоматических запросов не принимает — ссылка для ручной сверки."""
    return ("https://elibrary.ru/querybox.asp?scope=newquery&q="
            + urllib.parse.quote(str(query or "")))


def rsl_search_url(query: str) -> str:
    """Электронный каталог Российской государственной библиотеки."""
    return "https://search.rsl.ru/ru/search#q=" + urllib.parse.quote(str(query or ""))


def rusneb_search_url(query: str) -> str:
    """Национальная электронная библиотека."""
    return "https://rusneb.ru/search/?q=" + urllib.parse.quote(str(query or ""))


def protect_gost_url(designation: str) -> str:
    """Официальный фонд стандартов Росстандарта — проверка статуса ГОСТа."""
    return "https://protect.gost.ru/search.aspx?search=" + urllib.parse.quote(str(designation or ""))


MANUAL_SOURCES = {
    "РИНЦ / eLibrary": elibrary_search_url,
    "РГБ": rsl_search_url,
    "НЭБ": rusneb_search_url,
    "Росстандарт (статус ГОСТа)": protect_gost_url,
}


def manual_check_links(query: str) -> dict[str, str]:
    """Ссылки на базы без открытого API — для проверки глазами или браузером."""
    return {name: builder(query) for name, builder in MANUAL_SOURCES.items()}


# --------------------------------------------------------------------------
# Единая точка входа
# --------------------------------------------------------------------------

def enrich(query: str, kind: str = "auto") -> dict[str, Any]:
    """Подбирает базу по виду запроса и возвращает поля + источник.

    kind: auto | doi | isbn | title
    """
    q = str(query or "").strip()
    if not q:
        raise LookupError("пустой запрос")

    if kind == "auto":
        if re.search(r"10\.\d{4,9}/", q):
            kind = "doi"
        elif re.fullmatch(r"[\d\-\s]{10,20}[\dXx]?", q):
            kind = "isbn"
        else:
            kind = "title"

    attempts: list[str] = []
    if kind == "doi":
        order = [by_doi, by_openalex]
    elif kind == "isbn":
        order = [by_isbn]
    else:
        order = [by_openalex, by_crossref_title, by_cyberleninka]

    for fn in order:
        try:
            result = fn(q)
            result["manual_checks"] = manual_check_links(q)
            result["attempts"] = attempts
            return result
        except LookupError as exc:
            attempts.append(f"{fn.__name__}: {exc}")

    return {
        "fields": {},
        "source": "",
        "attempts": attempts,
        "manual_checks": manual_check_links(q),
        "note": "Автоматически ничего не найдено. Проверьте по ссылкам в manual_checks.",
    }
