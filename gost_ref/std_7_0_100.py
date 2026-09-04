"""ГОСТ Р 7.0.100-2018. Библиографическая запись. Библиографическое описание.

Стандарт для списка литературы (в том числе для ВАК). Области отделяются
« . — », заголовок записи содержит запятую после фамилии, место издания
приводится ПОЛНОСТЬЮ, обязательна область вида содержания
(«Текст : непосредственный» / «Текст : электронный»).
"""

from __future__ import annotations

import re

from .model import Reference
from .text import (
    normalize_designation_dash,
    title_with_designation,
    EM_DASH, city_full, end_sentence, is_latin, join_areas, labels,
    responsibility_list, role_group, tidy, with_subtitle,
)

STANDARD = "ГОСТ Р 7.0.100-2018"
AREA = f". {EM_DASH} "


# --------------------------------------------------------------------------
# Блоки
# --------------------------------------------------------------------------

# Область вида содержания и средства доступа факультативна: ГОСТ Р 7.0.100-2018
# делит элементы на обязательные, условно обязательные и факультативные, и эта
# область в обязательные не входит. Многие советы её требуют, многие — нет,
# поэтому вывод переключается, а не зашит.
CONTENT_TYPE = False


def _content_type(ref: Reference) -> str:
    """Область вида содержания. Главный источник системных ошибок в списках."""
    if not CONTENT_TYPE:
        return ""
    if ref.material_designation:
        return tidy(ref.material_designation)
    return "Текст : электронный" if ref.is_electronic else "Текст : непосредственный"


def _heading(ref: Reference) -> str:
    """Заголовок записи — только при одном–трёх авторах, с запятой."""
    if not ref.use_author_heading:
        return ""
    return ref.primary_authors[0].heading(comma=True)


def _responsibility(ref: Reference, full_names: bool = False) -> str:
    """Сведения об ответственности: первая группа после « / », далее через « ; »."""
    groups: list[str] = []
    if ref.primary_authors:
        if full_names:
            groups.append("; ".join(p.full() for p in ref.primary_authors))
        else:
            groups.append(responsibility_list(ref.primary_authors, max_named=4))
    if ref.editors:
        groups.append(role_group(ref.editors, "под редакцией"))
    if ref.compilers:
        groups.append(role_group(ref.compilers, "составитель"))
    if ref.translators:
        groups.append(role_group(ref.translators, "перевод"))
    if ref.organization:
        groups.append(tidy(ref.organization))
    return " ; ".join(g for g in groups if g)


def _title_area(ref: Reference, full_names: bool = False) -> str:
    """Заголовок + область заглавия и сведений об ответственности."""
    head = _heading(ref)
    title = with_subtitle(ref.title, ref.subtitle)
    if ref.parallel_title:
        title = f"{title} = {tidy(ref.parallel_title)}"
    resp = _responsibility(ref, full_names=full_names)
    body = f"{title} / {resp}" if resp else title
    return f"{head} {body}".strip() if head else body


def _imprint(ref: Reference) -> str:
    """«Москва : Наука, 2005» — место издания без сокращений."""
    city = city_full(ref.city)
    pub = tidy(ref.publisher)
    year = tidy(ref.year)
    left = f"{city} : {pub}" if city and pub else (city or pub)
    if left and year:
        return f"{left}, {year}"
    return left or year


def _extent(ref: Reference) -> str:
    if ref.total_pages:
        return f"{ref.total_pages} {labels(is_latin(ref.title))['extent']}"
    return ""


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
    out: list[str] = []
    if ref.url:
        url = tidy(ref.url)
        if ref.access_date:
            out.append(f"URL: {url} (дата обращения: {ref.access_date})")
        else:
            out.append(f"URL: {url}")
    if ref.doi:
        out.append(f"DOI {ref.doi}")
    return out


def _identifiers(ref: Reference) -> list[str]:
    out = []
    if ref.isbn:
        out.append(f"ISBN {tidy(ref.isbn)}")
    if ref.issn:
        out.append(f"ISSN {tidy(ref.issn)}")
    return out


def _container_area(ref: Reference) -> str:
    container = with_subtitle(ref.container, ref.container_subtitle)
    if ref.container_editors:
        container = f"{container} / {role_group(ref.container_editors, 'под редакцией')}"
    return container


# --------------------------------------------------------------------------
# Типы
# --------------------------------------------------------------------------

def _monograph(ref: Reference) -> list[str]:
    """Книга, монография, учебное пособие, многотомник."""
    return [
        _title_area(ref),
        tidy(ref.edition),
        _imprint(ref),
        _extent(ref),
        f"({tidy(ref.series)})" if ref.series else "",
        *_identifiers(ref),
        *(_access(ref) if ref.is_electronic else []),
        _content_type(ref),
    ]


def _component(ref: Reference) -> list[str]:
    """Составная часть: область вида содержания стоит ПЕРЕД « // »."""
    head = join_areas_local([_title_area(ref), _content_type(ref)])
    container = _container_area(ref)
    opening = f"{head} // {container}" if container else head

    if ref.type == "article":
        tail = [tidy(ref.year), _numbering(ref)]
    else:
        tail = [_imprint(ref), _numbering(ref)]
    if ref.pages:
        tail.append(f"{labels(is_latin(ref.title, ref.container))['pages']} {ref.pages}")
    if ref.is_electronic:
        tail.extend(_access(ref))
    elif ref.doi:
        tail.append(f"DOI {ref.doi}")
    return [opening, *tail]


def _web(ref: Reference) -> list[str]:
    """Сайт целиком или отдельная страница вне периодики."""
    title = with_subtitle(ref.title, ref.subtitle or ("официальный сайт" if ref.type == "website" else ""))
    head = _heading(ref)
    resp = _responsibility(ref)
    body = f"{title} / {resp}" if resp else title
    opening = f"{head} {body}".strip() if head else body
    container = _container_area(ref)
    if container:
        opening = f"{opening} // {container}"
    return [
        opening,
        city_full(ref.city),
        tidy(ref.update_note),
        tidy(ref.duration),
        *_access(ref),
        _content_type(ref),
    ]


def _dissertation(ref: Reference) -> list[str]:
    kind = ("автореферат диссертации на соискание ученой степени"
            if ref.type == "abstract"
            else "диссертация на соискание ученой степени")
    quals: list[str] = []
    if ref.specialty:
        spec = f"специальность {tidy(ref.specialty)}"
        if ref.specialty_name:
            spec = f"{spec} «{tidy(ref.specialty_name)}»"
        quals.append(spec)
    quals.append(f"{kind} {tidy(ref.degree)}" if ref.degree else kind)

    title = with_subtitle(ref.title, ref.subtitle)
    for q in quals:
        title = f"{title} : {q}"

    resp_parts = []
    if ref.primary_authors:
        resp_parts.append(ref.primary_authors[0].full())
    if ref.institution:
        resp_parts.append(tidy(ref.institution))
    resp = " ; ".join(resp_parts)
    body = f"{title} / {resp}" if resp else title
    head = _heading(ref)
    opening = f"{head} {body}".strip() if head else body
    return [
        opening,
        _imprint(ref),
        _extent(ref),
        tidy(ref.note),
        *(_access(ref) if ref.is_electronic else []),
        _content_type(ref),
    ]


def _standard(ref: Reference) -> list[str]:
    number = normalize_designation_dash(tidy(ref.doc_number))
    title = with_subtitle(ref.title, ref.subtitle)
    opening = f"{number}. {title}" if number else title
    if ref.status:
        opening = f"{opening} : {tidy(ref.status)}"
    return [
        opening,
        _imprint(ref),
        _extent(ref),
        *(_access(ref) if ref.is_electronic else []),
        _content_type(ref),
    ]


def _law(ref: Reference) -> list[str]:
    title = title_with_designation(ref.title, ref.subtitle,
                                   ref.doc_number, ref.adopted)
    juris = tidy(ref.jurisdiction)
    opening = f"{juris} {title}" if juris else title
    container = _container_area(ref)
    if container:
        opening = join_areas_local([opening, _content_type(ref)]) + f" // {container}"
        return [opening, tidy(ref.year), _numbering(ref),
                f"С. {ref.pages}" if ref.pages else "", *_access(ref)]
    return [
        opening,
        _imprint(ref),
        _extent(ref),
        *(_access(ref) if ref.is_electronic else []),
        _content_type(ref),
    ]


def _archive(ref: Reference) -> list[str]:
    parts = []
    if ref.title:
        parts.append(_title_area(ref))
    parts.append(tidy(ref.archive))
    parts.append(tidy(ref.archive_ref))
    parts.append(_content_type(ref))
    return parts


def join_areas_local(parts) -> str:
    return join_areas(parts, EM_DASH)


_DISPATCH = {
    "book": _monograph,
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
    "treaty": _law,
    "archive": _archive,
}


def format(ref: Reference, content_type: bool = False) -> str:
    """content_type=False убирает «Текст : непосредственный» — элемент
    факультативный, и часть советов его не требует."""
    global CONTENT_TYPE
    previous, CONTENT_TYPE = CONTENT_TYPE, content_type
    try:
        builder = _DISPATCH.get(ref.type, _monograph)
        parts = [p for p in builder(ref) if p]
        return end_sentence(join_areas_local(parts))
    finally:
        CONTENT_TYPE = previous
