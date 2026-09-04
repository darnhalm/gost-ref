"""ГОСТ 7.1-2003. Библиографическая запись. Библиографическое описание.

Предшественник ГОСТ Р 7.0.100-2018. Отличия, которые видно в строке:
области отделяются « . – » (короткое тире), место издания сокращается,
после основного заглавия ставится общее обозначение материала [Текст],
области вида содержания («Текст : непосредственный») здесь нет.
"""

from __future__ import annotations

from .model import Reference
from .text import (
    normalize_designation_dash,
    act_designation,
    EN_DASH, city_short, end_sentence, is_latin, join_areas, labels,
    responsibility_list, role_group, tidy,
)

STANDARD = "ГОСТ 7.1-2003"
AREA = f". {EN_DASH} "


def _join(parts) -> str:
    return join_areas(parts, EN_DASH)


def _heading(ref: Reference) -> str:
    return ref.primary_authors[0].heading(comma=True) if ref.use_author_heading else ""


def _designation(ref: Reference, use: bool) -> str:
    if not use:
        return ""
    if ref.material_designation:
        return f"[{tidy(ref.material_designation)}]"
    return "[Электронный ресурс]" if ref.is_electronic else "[Текст]"


def _responsibility(ref: Reference) -> str:
    groups: list[str] = []
    if ref.primary_authors:
        groups.append(responsibility_list(ref.primary_authors, max_named=3))
    if ref.editors:
        groups.append(role_group(ref.editors, "под ред."))
    if ref.compilers:
        groups.append(role_group(ref.compilers, "сост."))
    if ref.translators:
        groups.append(role_group(ref.translators, "пер."))
    if ref.organization:
        groups.append(tidy(ref.organization))
    return " ; ".join(g for g in groups if g)


def _title_area(ref: Reference, designation: bool = True) -> str:
    title = tidy(ref.title)
    gmd = _designation(ref, designation)
    if gmd:
        title = f"{title} {gmd}"
    if ref.subtitle:
        title = f"{title} : {tidy(ref.subtitle)}"
    resp = _responsibility(ref)
    body = f"{title} / {resp}" if resp else title
    head = _heading(ref)
    return f"{head} {body}".strip() if head else body


def _imprint(ref: Reference) -> str:
    city = city_short(ref.city)
    pub = tidy(ref.publisher)
    year = tidy(ref.year)
    left = f"{city} : {pub}" if city and pub else (city or pub)
    return f"{left}, {year}" if left and year else (left or year)


def _numbering(ref: Reference) -> str:
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
    out = []
    if ref.url:
        url = tidy(ref.url)
        out.append(f"Режим доступа: {url}" if not ref.access_date
                   else f"Режим доступа: {url} (дата обращения: {ref.access_date})")
    if ref.doi:
        out.append(f"DOI {ref.doi}")
    return out


def _tail_identifiers(ref: Reference) -> list[str]:
    out = []
    if ref.series:
        out.append(f"({tidy(ref.series)})")
    if ref.isbn:
        out.append(f"ISBN {tidy(ref.isbn)}")
    if ref.issn:
        out.append(f"ISSN {tidy(ref.issn)}")
    return out


def format(ref: Reference) -> str:
    if ref.is_component:
        container = tidy(ref.container)
        if ref.container_subtitle:
            container = f"{container} : {tidy(ref.container_subtitle)}"
        if ref.container_editors:
            container = f"{container} / {role_group(ref.container_editors, 'под ред.')}"
        opening = _title_area(ref)
        if container:
            opening = f"{opening} // {container}"
        tail = [tidy(ref.year)] if ref.type == "article" else [_imprint(ref)]
        tail.append(_numbering(ref))
        if ref.pages:
            tail.append(f"{labels(is_latin(ref.title, ref.container))['pages']} {ref.pages}")
        tail.extend(_access(ref))
        return end_sentence(_join([opening, *tail]))

    if ref.type in ("dissertation", "abstract"):
        kind = "автореф. дис. ..." if ref.type == "abstract" else "дис. ..."
        qual = f"{kind} {tidy(ref.degree)}" if ref.degree else kind
        if ref.specialty:
            qual = f"{qual} : {tidy(ref.specialty)}"
        title = f"{tidy(ref.title)} {_designation(ref, True)}".strip()
        if ref.subtitle:
            title = f"{title} : {tidy(ref.subtitle)}"
        title = f"{title} : {qual}"
        head = _heading(ref)
        opening = f"{head} {title}".strip() if head else title
        extent = f"{ref.total_pages} {labels(is_latin(ref.title))['extent']}" if ref.total_pages else ""
        return end_sentence(_join([opening, _imprint(ref), extent, *_access(ref)]))

    if ref.type in ("standard", "law", "treaty"):
        title = tidy(ref.title)
        if ref.doc_number and ref.type == "standard":
            title = f"{normalize_designation_dash(tidy(ref.doc_number))}. {title}"
        gmd = _designation(ref, True)
        if gmd:
            title = f"{title} {gmd}"
        if ref.subtitle:
            title = f"{title} : {tidy(ref.subtitle)}"
        if ref.type != "standard":
            designation = act_designation(ref.doc_number, ref.adopted)
            if designation:
                title = f"{title} {designation}" if ref.subtitle \
                    else f"{title} : {designation}"
        extent = f"{ref.total_pages} {labels(is_latin(ref.title))['extent']}" if ref.total_pages else ""
        return end_sentence(_join([title, _imprint(ref), extent, *_access(ref)]))

    extent = f"{ref.total_pages} {labels(is_latin(ref.title))['extent']}" if ref.total_pages else ""
    return end_sentence(_join([
        _title_area(ref),
        tidy(ref.edition),
        _imprint(ref),
        extent,
        *_tail_identifiers(ref),
        *_access(ref),
    ]))
