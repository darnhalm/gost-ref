"""ГОСТ Р 7.0.108-2022. Библиографические ссылки на электронные документы,
размещённые в информационно-телекоммуникационных сетях.

Введён 01.06.2022, действует ВМЕСТЕ с ГОСТ Р 7.0.5-2008: 7.0.5 остаётся общим
стандартом ссылки, а 7.0.108 уточняет правила для сетевых документов.

Пунктуация та же, что в 7.0.5 — области через точку, без тире.
Обязательны: заголовок (при наличии автора), основное заглавие, URL и дата
обращения. Факультативны: вид документа, формат, DOI, сведения об
ответственности, примечание об обновлении.

DOI приводят либо на составную часть, либо на документ в целом — не на оба.
Для сетевых периодических изданий вместо даты обращения может указываться
дата публикации, если она приведена в самом издании.
"""

from __future__ import annotations

from .model import Reference
from .text import (
    normalize_designation_dash,
    title_with_designation,
    city_short, end_sentence, heading_list, is_latin, join_sentences, labels,
    responsibility_list, role_group, tidy, today, with_subtitle,
)

STANDARD = "ГОСТ Р 7.0.108-2022"


def _responsibility(ref: Reference) -> str:
    groups: list[str] = []
    if not ref.use_author_heading and ref.primary_authors:
        groups.append(responsibility_list(ref.primary_authors, max_named=3))
    if ref.editors:
        groups.append(role_group(ref.editors, "под ред."))
    if ref.translators:
        groups.append(role_group(ref.translators, "пер."))
    return " ; ".join(g for g in groups if g)


def _opening(ref: Reference) -> str:
    head = heading_list(ref.primary_authors, comma=False) if ref.use_author_heading else ""
    if ref.type == "standard" and normalize_designation_dash(tidy(ref.doc_number)):
        # У стандарта обозначение стоит впереди заглавия, а не после него.
        title = f"{normalize_designation_dash(tidy(ref.doc_number))}. {with_subtitle(ref.title, ref.subtitle)}"
    else:
        title = title_with_designation(ref.title, ref.subtitle,
                                       ref.doc_number, ref.adopted)
    if ref.material_designation:
        title = f"{title} : {tidy(ref.material_designation)}"
    resp = _responsibility(ref)
    if resp:
        title = f"{title} / {resp}"
    return f"{head} {title}".strip() if head else title


def _numbering(ref: Reference) -> str:
    lb = labels(is_latin(ref.title or ref.container))
    bits = []
    if ref.volume:
        bits.append(f"{lb['vol']} {tidy(ref.volume)}")
    if ref.part:
        bits.append(f"{lb['part']} {tidy(ref.part)}")
    if ref.issue:
        bits.append(f"{lb['issue']} {tidy(ref.issue)}")
    return ", ".join(bits)


def _locator(ref: Reference) -> list[str]:
    """URL с датой обращения либо датой публикации; DOI — факультативно."""
    out: list[str] = []
    url = tidy(ref.url)
    if not url:
        return out
    if ref.publication_date and not ref.access_date:
        out.append(f"URL: {url}")
        out.append(f"Дата публикации: {ref.publication_date}")
    else:
        stamp = ref.access_date or today()
        out.append(f"URL: {url} (дата обращения: {stamp})")
        if ref.publication_date:
            out.append(f"Дата публикации: {ref.publication_date}")
    return out


def format(ref: Reference) -> str:
    if not tidy(ref.url):
        # Стандарт распространяется только на документы в сетях.
        # Для несетевого источника действует общий ГОСТ Р 7.0.5-2008.
        from . import std_7_0_5
        return std_7_0_5.format(ref)

    opening = _opening(ref)
    container = with_subtitle(ref.container, ref.container_subtitle)
    if container:
        opening = f"{opening} // {container}"

    parts: list[str] = [opening]

    if ref.type in ("website",) and not ref.container:
        parts.append(city_short(ref.city))

    parts.append(tidy(ref.year))
    parts.append(_numbering(ref))
    if ref.pages:
        parts.append(f"{labels(is_latin(ref.title or ref.container))['pages']} {ref.pages}")
    if ref.duration:
        parts.append(tidy(ref.duration))
    if ref.update_note:
        parts.append(tidy(ref.update_note))
    if ref.doi:
        parts.append(f"DOI {ref.doi}")
    parts.extend(_locator(ref))
    if ref.note:
        parts.append(tidy(ref.note))

    return end_sentence(join_sentences([p for p in parts if p]))
