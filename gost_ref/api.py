"""Единый вход: форматирование, разбор, список, повторные ссылки."""

from __future__ import annotations

import re
from typing import Any, Iterable

from . import std_7_0_5, std_7_0_100, std_7_0_108, std_7_1
from .model import SOURCE_TYPES, Reference, type_label
from .parse import parse as parse_raw
from .text import apply_nbsp, heading_list, normalize_pages, tidy
from .validate import validate as validate_ref

STANDARDS: dict[str, Any] = {
    "7.0.5": std_7_0_5,
    "7.0.100": std_7_0_100,
    "7.1": std_7_1,
    "7.0.108": std_7_0_108,
}

ALIASES = {
    "гост р 7.0.5-2008": "7.0.5", "7.0.5-2008": "7.0.5", "сноска": "7.0.5",
    "подстрочная": "7.0.5", "ссылка": "7.0.5",
    "гост р 7.0.100-2018": "7.0.100", "7.0.100-2018": "7.0.100",
    "список": "7.0.100", "вак": "7.0.100", "запись": "7.0.100",
    "гост 7.1-2003": "7.1", "7.1-2003": "7.1",
    "гост р 7.0.108-2022": "7.0.108", "7.0.108-2022": "7.0.108",
    "электронные": "7.0.108",
}


def resolve_standard(name: str) -> str:
    key = tidy(name).lower()
    if key in STANDARDS:
        return key
    return ALIASES.get(key, "7.0.100")


# --------------------------------------------------------------------------
# Форматирование
# --------------------------------------------------------------------------

def format_reference(data: Any, standard: str = "7.0.100", nbsp: bool = False,
                     content_type: bool = False) -> str:
    """Собирает строку по одному стандарту.

    content_type действует только для 7.0.100: False убирает факультативную
    область вида содержания («Текст : непосредственный»), если совет или
    редакция её не требуют.
    """
    ref = data if isinstance(data, Reference) else Reference.from_dict(data)
    key = resolve_standard(standard)
    if key == "7.0.100":
        out = STANDARDS[key].format(ref, content_type=content_type)
    else:
        out = STANDARDS[key].format(ref)
    return apply_nbsp(out) if nbsp else out


def format_all(data: Any, nbsp: bool = False) -> dict[str, str]:
    """Одни и те же данные во всех четырёх стандартах — удобно для сверки."""
    ref = data if isinstance(data, Reference) else Reference.from_dict(data)
    return {key: format_reference(ref, key, nbsp=nbsp) for key in STANDARDS}


def format_and_check(data: Any, standard: str = "7.0.100", nbsp: bool = False,
                     content_type: bool = False) -> dict[str, Any]:
    ref = data if isinstance(data, Reference) else Reference.from_dict(data)
    key = resolve_standard(standard)
    rendered = format_reference(ref, key, nbsp=nbsp, content_type=content_type)
    report = validate_ref(ref, standard=key, rendered=rendered)
    return {
        "standard": key,
        "reference": rendered,
        "type": ref.type,
        "type_label": type_label(ref.type),
        "fields": ref.to_dict(),
        **report,
    }


def format_pair(data: Any, record_standard: str = "7.0.100",
                nbsp: bool = False, content_type: bool = False) -> dict[str, Any]:
    """Обе формы одного источника сразу: подстрочная сноска и запись для списка.

    В диссертации нужны обе, а поля у них одни и те же — спрашивать «сноска
    или список» незачем. Сноска всегда по ГОСТ Р 7.0.5-2008 (для сетевого
    документа его уточняет 7.0.108-2022); запись — по 7.0.100-2018, либо по
    7.1-2003, если этого требует совет.
    """
    ref = data if isinstance(data, Reference) else Reference.from_dict(data)
    record_key = resolve_standard(record_standard)
    if record_key not in ("7.0.100", "7.1"):
        record_key = "7.0.100"
    footnote_key = "7.0.108" if ref.url else "7.0.5"

    footnote = format_reference(ref, footnote_key, nbsp=nbsp)
    record = format_reference(ref, record_key, nbsp=nbsp, content_type=content_type)

    return {
        "footnote": {
            "standard": footnote_key,
            "text": footnote,
            **{k: v for k, v in validate_ref(ref, standard=footnote_key,
                                             rendered=footnote).items()
               if k != "standard"},
        },
        "record": {
            "standard": record_key,
            "text": record,
            **{k: v for k, v in validate_ref(ref, standard=record_key,
                                             rendered=record).items()
               if k != "standard"},
        },
        "type": ref.type,
        "type_label": type_label(ref.type),
        "fields": ref.to_dict(),
    }


# --------------------------------------------------------------------------
# Разбор
# --------------------------------------------------------------------------

def reformat(raw: str, standard: str = "7.0.100", nbsp: bool = False,
             autofix: bool = True, type_override: str = "") -> dict[str, Any]:
    """Кривая строка → разобранные поля → строка по стандарту + замечания.

    type_override — задать тип источника вручную, когда определитель ошибся.
    Допустимые значения перечислены в `SOURCE_TYPES`.
    """
    parsed = parse_raw(raw)
    detection = dict(parsed.get("type_detection") or {})
    fields = dict(parsed["fields"])

    override = tidy(type_override).lower()
    if override:
        if override not in SOURCE_TYPES:
            return {
                "error": f"неизвестный тип «{type_override}»",
                "known_types": {k: v for k, v in SOURCE_TYPES.items()},
            }
        if override != fields.get("type"):
            detection = {
                "type": override,
                "label": type_label(override),
                "confidence": "задано вручную",
                "reason": f"тип указан пользователем вместо определённого "
                          f"«{type_label(fields.get('type', ''))}»",
                "alternatives": [],
            }
        fields["type"] = override

    ref = Reference.from_dict(fields)
    fixes: list[str] = []
    if autofix:
        if ref.url and ref.medium == "print":
            ref.medium = "electronic"
            fixes.append("Вид содержания исправлен на «электронный»: в записи есть URL.")
    key = resolve_standard(standard)
    rendered = STANDARDS[key].format(ref)
    if nbsp:
        rendered = apply_nbsp(rendered)
    report = validate_ref(ref, standard=key, rendered=rendered)
    out = {
        "input": tidy(raw),
        "standard": key,
        "reference": rendered,
        "type": ref.type,
        "type_label": type_label(ref.type),
        "type_detection": detection,
        "fields": ref.to_dict(),
        "leftovers": parsed["leftovers"],
        "parse_notes": parsed["notes"],
        "autofixes": fixes,
        **report,
    }
    if detection.get("confidence") != "задано вручную":
        out["how_to_override"] = (
            "Если тип определён неверно, повторите вызов с type_override — "
            "например type_override='chapter'. Полный список: " +
            ", ".join(SOURCE_TYPES)
        )
    return out


# --------------------------------------------------------------------------
# Список литературы
# --------------------------------------------------------------------------

_CYRILLIC = re.compile(r"^[«\"(\[]*[А-ЯЁа-яё]")


def _sort_key(rendered: str) -> tuple[int, str]:
    s = re.sub(r"^[«\"(\[]+", "", rendered)
    return (0 if _CYRILLIC.match(rendered) else 1, s.lower())


def build_list(items: Iterable[Any], standard: str = "7.0.100",
               sort: str = "alpha", numbered: bool = True,
               nbsp: bool = False) -> dict[str, Any]:
    """Собирает список литературы целиком.

    sort: alpha — кириллица, затем латиница (обычное требование ВАК);
          none  — сохранить порядок, в котором пришли записи.
    """
    key = resolve_standard(standard)
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        ref = item if isinstance(item, Reference) else Reference.from_dict(item)
        rendered = STANDARDS[key].format(ref)
        if nbsp:
            rendered = apply_nbsp(rendered)
        report = validate_ref(ref, standard=key, rendered=rendered)
        entries.append({
            "input_index": index,
            "reference": rendered,
            "ok": report["ok"],
            "errors": report["errors"],
            "warnings": report["warnings"],
        })

    if sort == "alpha":
        entries.sort(key=lambda e: _sort_key(e["reference"]))

    lines = []
    for i, entry in enumerate(entries, start=1):
        entry["number"] = i
        lines.append(f"{i}. {entry['reference']}" if numbered else entry["reference"])

    problems = sum(1 for e in entries if not e["ok"])
    return {
        "standard": key,
        "count": len(entries),
        "with_errors": problems,
        "text": "\n".join(lines),
        "entries": entries,
    }


# --------------------------------------------------------------------------
# Повторные и вторичные ссылки (ГОСТ Р 7.0.5-2008, раздел 6)
# --------------------------------------------------------------------------

def ibid(pages: str = "") -> str:
    """Ссылка на тот же источник подряд: «Там же. С. 25.»"""
    p = normalize_pages(pages)
    return f"Там же. С. {p}." if p else "Там же."


def op_cit(authors: Any = "", pages: str = "") -> str:
    """Повтор с другой позиции: «Иванов И. И. Указ. соч. С. 364.»"""
    from .model import as_people
    head = heading_list(as_people(authors), comma=False) if authors else ""
    p = normalize_pages(pages)
    tail = f"Указ. соч. С. {p}." if p else "Указ. соч."
    return f"{head} {tail}".strip()


def short_form(data: Any, pages: str = "") -> str:
    """Сокращённая повторная ссылка: заголовок, начало заглавия, многоточие, страницы.

    «Лисичкин В. А., Шелепин Л. А. Война после войны … С. 212.»
    """
    ref = data if isinstance(data, Reference) else Reference.from_dict(data)
    head = heading_list(ref.primary_authors, comma=False)
    words = tidy(ref.title).split()
    stub = " ".join(words[:4])
    if len(words) > 4:
        stub = f"{stub} …"
    p = normalize_pages(pages) or normalize_pages(ref.pages)
    tail = f"С. {p}." if p else ""
    return " ".join(x for x in (head, stub, tail) if x).strip()


def cited_from(secondary: Any, standard: str = "7.0.5", nbsp: bool = False) -> str:
    """Ссылка через посредника: «Цит. по: …».

    Применяется, когда первоисточник недоступен. Если он доступен — ссылаться
    надо на него, а не на пересказ.
    """
    body = format_reference(secondary, standard=standard, nbsp=nbsp)
    return f"Цит. по: {body}"


def see_also(secondary: Any, standard: str = "7.0.5", nbsp: bool = False) -> str:
    """«См. также: …» — отсылка к дополнительной литературе."""
    return f"См. также: {format_reference(secondary, standard=standard, nbsp=nbsp)}"
