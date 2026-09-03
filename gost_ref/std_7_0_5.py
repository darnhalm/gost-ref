"""ГОСТ Р 7.0.5-2008. Библиографическая ссылка.

Подстрочные, внутритекстовые и затекстовые ссылки. Области разделяются точкой,
тире между областями не ставится, город приводится сокращённо, сведения об
ответственности при одном–трёх авторах опускаются — их несёт заголовок.
"""

from __future__ import annotations

from .model import Reference
from .text import (
    city_short, end_sentence, heading_list, is_latin, join_sentences, labels,
    responsibility_list, role_group, tidy, with_subtitle,
)

STANDARD = "ГОСТ Р 7.0.5-2008"


# --------------------------------------------------------------------------
# Блоки
# --------------------------------------------------------------------------

def _responsibility(ref: Reference) -> str:
    """Сведения об ответственности после « / »."""
    groups: list[str] = []
    if not ref.use_author_heading and ref.primary_authors:
        groups.append(responsibility_list(ref.primary_authors, max_named=3))
    if ref.editors:
        groups.append(role_group(ref.editors, "под ред."))
    if ref.compilers:
        groups.append(role_group(ref.compilers, "сост."))
    if ref.translators:
        groups.append(role_group(ref.translators, "пер."))
    return " ; ".join(g for g in groups if g)


def _title_block(ref: Reference) -> str:
    block = with_subtitle(ref.title, ref.subtitle)
    resp = _responsibility(ref)
    if resp:
        block = f"{block} / {resp}"
    return block


def _opening(ref: Reference) -> str:
    """Заголовок + заглавие."""
    head = heading_list(ref.primary_authors, comma=False) if ref.use_author_heading else ""
    block = _title_block(ref)
    return f"{head} {block}".strip() if head else block


def _imprint(ref: Reference) -> str:
    """«М. : Наука, 2005» / «М., 2005» / «2005»."""
    city = city_short(ref.city)
    pub = tidy(ref.publisher)
    year = tidy(ref.year)
    if city and pub:
        left = f"{city} : {pub}"
    else:
        left = city or pub
    if left and year:
        return f"{left}, {year}"
    return left or year


def _extent(ref: Reference) -> str:
    lb = labels(is_latin(ref.title, ref.container))
    if ref.pages:
        return f"{lb['pages']} {ref.pages}"
    if ref.total_pages:
        return f"{ref.total_pages} {lb['extent']}"
    return ""


def _numbering(ref: Reference) -> str:
    """«Т. 5, № 3», «№ 2», «Vol. 58, No. 3»."""
    lb = labels(is_latin(ref.title, ref.container))
    bits = []
    if ref.volume:
        bits.append(f"{lb['vol']} {tidy(ref.volume)}")
    if ref.part:
        bits.append(f"{lb['part']} {tidy(ref.part)}")
    if ref.issue:
        bits.append(f"{lb['issue']} {tidy(ref.issue)}")
    return ", ".join(bits)


def _access(ref: Reference) -> list[str]:
    """URL, дата обращения / дата публикации, DOI."""
    out: list[str] = []
    if ref.doi:
        out.append(f"DOI {ref.doi}")
    if ref.url:
        url = tidy(ref.url)
        if ref.access_date:
            out.append(f"URL: {url} (дата обращения: {ref.access_date})")
        else:
            out.append(f"URL: {url}")
        if ref.publication_date:
            out.append(f"Дата публикации: {ref.publication_date}")
    return out


def _container_block(ref: Reference) -> str:
    return with_subtitle(ref.container, ref.container_subtitle)


# --------------------------------------------------------------------------
# Типы
# --------------------------------------------------------------------------

def _book(ref: Reference) -> list[str]:
    return [_opening(ref), tidy(ref.edition), _imprint(ref), _extent(ref)]


def _component(ref: Reference) -> list[str]:
    head = _opening(ref)
    container = _container_block(ref)
    if ref.container_editors:
        container = f"{container} / {role_group(ref.container_editors, 'под ред.')}"
    first = f"{head} // {container}" if container else head
    if ref.type == "article":
        tail = [tidy(ref.year), _numbering(ref), _extent(ref)]
    else:
        tail = [_imprint(ref), _numbering(ref), _extent(ref)]
    return [first, *tail]


def _web(ref: Reference) -> list[str]:
    head = with_subtitle(ref.title, ref.subtitle)
    if ref.primary_authors and ref.use_author_heading:
        head = f"{heading_list(ref.primary_authors, comma=False)} {head}".strip()
    container = _container_block(ref)
    first = f"{head} // {container}" if container else head
    return [first, tidy(ref.year), _numbering(ref), _extent(ref)]


def _dissertation(ref: Reference) -> list[str]:
    kind = "автореф. дис." if ref.type == "abstract" else "дис."
    qual = f"{kind} ... {tidy(ref.degree)}" if ref.degree else kind
    if ref.specialty:
        qual = f"{qual} : {tidy(ref.specialty)}"
    title = with_subtitle(ref.title, ref.subtitle)
    head = heading_list(ref.primary_authors, comma=False)
    opening = f"{head} {title} : {qual}".strip() if head else f"{title} : {qual}"
    return [opening, _imprint(ref), _extent(ref)]


def _standard(ref: Reference) -> list[str]:
    number = tidy(ref.doc_number)
    title = with_subtitle(ref.title, ref.subtitle)
    opening = f"{number}. {title}" if number else title
    if ref.status:
        opening = f"{opening} : {tidy(ref.status)}"
    return [opening, _imprint(ref), _extent(ref)]


def _law(ref: Reference) -> list[str]:
    title = with_subtitle(ref.title, ref.subtitle)
    if ref.doc_number:
        title = f"{title} : {tidy(ref.doc_number)}"
    if ref.adopted:
        title = f"{title} : {tidy(ref.adopted)}"
    container = _container_block(ref)
    first = f"{title} // {container}" if container else title
    return [first, tidy(ref.year), _numbering(ref), _extent(ref)]


def _treaty(ref: Reference) -> list[str]:
    title = with_subtitle(ref.title, ref.subtitle)
    if ref.adopted:
        title = f"{title} ({tidy(ref.adopted)})"
    container = _container_block(ref)
    first = f"{title} // {container}" if container else title
    return [first, _imprint(ref), _extent(ref)]


def _archive(ref: Reference) -> list[str]:
    head = tidy(ref.archive)
    parts = [head, tidy(ref.archive_ref)]
    if ref.title:
        parts.insert(0, _opening(ref))
    return parts


_DISPATCH = {
    "book": _book,
    "chapter": _component,
    "article": _component,
    "preprint": _component,
    "webpage": _web,
    "website": _web,
    "media": _web,
    "dissertation": _dissertation,
    "abstract": _dissertation,
    "standard": _standard,
    "law": _law,
    "treaty": _treaty,
    "archive": _archive,
}


def format(ref: Reference) -> str:
    builder = _DISPATCH.get(ref.type, _book)
    parts = [p for p in builder(ref) if p]
    if ref.duration:
        parts.append(tidy(ref.duration))
    if ref.update_note:
        parts.append(tidy(ref.update_note))
    parts.extend(_access(ref))
    if ref.note:
        parts.append(tidy(ref.note))
    return end_sentence(join_sentences(parts))
