"""Извлечение выходных данных из PDF.

Титульный лист, оборот титула и последняя страница книги несут почти всё, что
нужно для описания: авторов, город, издательство, год, ISBN, УДК/ББК, объём.
У статей то же обычно лежит в шапке первой страницы и в /Info или XMP.

Модуль ничего не решает за человека: он возвращает и «сырые» куски текста,
и подсказки-кандидаты, помеченные тем, откуда они взяты.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", message=".*ARC4.*")

from .text import tidy


def _pypdf(path: str):
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        from PyPDF2 import PdfReader  # type: ignore
    return PdfReader(path)


def extract(path: str, head_pages: int = 3, tail_pages: int = 2,
            max_chars: int = 6000) -> dict[str, Any]:
    """Возвращает метаданные документа, тексты ключевых страниц и подсказки."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(str(p))

    reader = _pypdf(str(p))
    n = len(reader.pages)

    info: dict[str, Any] = {}
    try:
        raw_info = reader.metadata or {}
        for key, value in raw_info.items():
            k = str(key).lstrip("/")
            v = tidy(value)
            if v:
                info[k] = v
    except Exception:  # noqa: BLE001
        pass

    xmp: dict[str, Any] = {}
    try:
        meta = reader.xmp_metadata
        if meta is not None:
            for attr in ("dc_title", "dc_creator", "dc_description", "dc_publisher",
                         "dc_identifier", "dc_date", "dc_language", "dc_subject"):
                value = getattr(meta, attr, None)
                if value:
                    xmp[attr] = value if not isinstance(value, dict) else dict(value)
    except Exception:  # noqa: BLE001
        pass

    def page_text(idx: int) -> str:
        try:
            return tidy(reader.pages[idx].extract_text() or "")
        except Exception:  # noqa: BLE001
            return ""

    head_idx = list(range(min(head_pages, n)))
    tail_idx = [i for i in range(max(0, n - tail_pages), n) if i not in head_idx]

    head = {f"p{i + 1}": page_text(i)[:max_chars] for i in head_idx}
    tail = {f"p{i + 1}": page_text(i)[:max_chars] for i in tail_idx}

    corpus = " ".join(list(head.values()) + list(tail.values()))
    return {
        "file": p.name,
        "pages_total": n,
        "info": info,
        "xmp": xmp,
        "head_pages": head,
        "tail_pages": tail,
        "hints": hints(corpus, info, n),
    }


# --------------------------------------------------------------------------
# Подсказки
# --------------------------------------------------------------------------

_ISBN_RE = re.compile(r"ISBN[\s:]*((?:97[89][\-\s]?)?[\d\-\s]{9,17}[\dXx])", re.I)
_ISSN_RE = re.compile(r"ISSN[\s:]*(\d{4}[-–]\d{3}[\dXx])", re.I)
_UDC_RE = re.compile(r"УДК[\s:]*([\d.()\-+:/']{3,40})", re.I)
_BBK_RE = re.compile(r"ББК[\s:]*(\d{1,3}(?:\.\d+)*\s*[А-Яа-я]?\d*)", re.I)
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;)\]<>]+)")
_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
_TIRAGE_RE = re.compile(r"Тираж[\s:]*([\d\s]{2,10})\s*экз", re.I)
_SIGNED_RE = re.compile(r"Подписано в печать[\s:]*([\d.]{6,12})", re.I)
_PUBLISHER_RE = re.compile(
    r"(Изд-во[^\n,;]{2,60}|Издательство[^\n,;]{2,60}|"
    r"[«\"][^»\"]{2,50}[»\"]\s*(?:,|$))", re.I)

_CITIES = [
    "Москва", "Санкт-Петербург", "СПб", "Ленинград", "Казань", "Новосибирск",
    "Екатеринбург", "Нижний Новгород", "Ростов-на-Дону", "Томск", "Самара",
    "Воронеж", "Красноярск", "Уфа", "Пермь", "Волгоград", "Саратов", "Омск",
]


def hints(text: str, info: dict[str, Any] | None = None, pages_total: int = 0) -> dict[str, Any]:
    """Кандидаты в поля. Ничего не утверждает — только показывает найденное."""
    info = info or {}
    out: dict[str, Any] = {}

    def first(pattern: re.Pattern, key: str, transform=None):
        m = pattern.search(text)
        if m:
            value = tidy(m.group(1))
            out[key] = transform(value) if transform else value

    first(_ISBN_RE, "isbn", lambda s: re.sub(r"\s+", "", s))
    first(_ISSN_RE, "issn")
    first(_UDC_RE, "udc")
    first(_BBK_RE, "bbk")
    first(_DOI_RE, "doi")
    first(_TIRAGE_RE, "tirage")
    first(_SIGNED_RE, "signed_to_print")

    m = _PUBLISHER_RE.search(text)
    if m:
        out["publisher_candidate"] = tidy(m.group(1)).strip(" ,«»\"")

    cities = [c for c in _CITIES if re.search(rf"\b{re.escape(c)}\b", text)]
    if cities:
        out["city_candidates"] = cities[:3]

    years = sorted(set(_YEAR_RE.findall(text)))
    if years:
        out["year_candidates"] = years[-4:]

    if info.get("Title"):
        out["title_from_metadata"] = info["Title"]
    if info.get("Author"):
        out["authors_from_metadata"] = info["Author"]
    if pages_total:
        out["total_pages_from_file"] = str(pages_total)
        out["total_pages_warning"] = (
            "Число страниц PDF-файла НЕ равно объёму издания: "
            "в описании указывают номер последней нумерованной страницы."
        )

    out["_reliability"] = (
        "Поля /Info в PDF часто заполнены конвертером и содержат мусор "
        "(«Microsoft Word - диплом.doc»). Приоритет — текст титульного листа "
        "и оборота титула, а не метаданные файла."
    )
    return out
