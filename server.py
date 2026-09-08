#!/usr/bin/env python3
"""MCP-сервер gost-ref: библиографические ссылки и записи по ГОСТ.

Тонкая обёртка над пакетом `gost_ref`. Вся логика стандартов живёт там —
здесь только объявление инструментов, чтобы к ядру можно было обратиться
из любого MCP-клиента.

Запуск (stdio):
    python server.py
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from gost_ref import api, lookup, pdfmeta
from gost_ref.model import SOURCE_TYPES, Reference
from gost_ref.text import today

mcp = FastMCP("gost-ref")

_STANDARD_NAMES = {
    "7.0.5": "ГОСТ Р 7.0.5-2008 — библиографическая ссылка (подстрочные сноски)",
    "7.0.100": "ГОСТ Р 7.0.100-2018 — библиографическая запись (список литературы, ВАК)",
    "7.1": "ГОСТ 7.1-2003 — прежний стандарт библиографической записи",
    "7.0.108": "ГОСТ Р 7.0.108-2022 — ссылки на сетевые электронные документы",
}

_FIELDS_HELP = """\
Поля описания (передавайте только известные, ничего не выдумывая):
  type      — тип источника, см. list_source_types
  authors   — «Иванов И. И.», список строк или список {surname, initials, given}
  editors / translators / compilers — те же форматы
  title, subtitle, parallel_title
  organization — учреждение в сведениях об ответственности
  edition   — «2-е изд., перераб. и доп.»
  container, container_subtitle — журнал, сборник, сайт (то, что после «//»)
  city, publisher, year
  volume, issue, part, pages («45-52»), total_pages («250»)
  series, isbn, issn, doi
  url, access_date, publication_date, update_note
  medium    — print | electronic (по умолчанию выводится из наличия URL)
  specialty, specialty_name, degree, institution — для диссертаций
  doc_number, adopted, status, jurisdiction — для стандартов и нормативных актов
  archive, archive_ref — для архивных документов
  material_designation, duration, note
"""


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Справка
# --------------------------------------------------------------------------

@mcp.tool()
def list_source_types() -> str:
    """Типы источников и полный список полей описания.

    Вызовите это первым, если не уверены, какой `type` и какие поля передавать.
    """
    return _dump({
        "standards": _STANDARD_NAMES,
        "source_types": SOURCE_TYPES,
        "fields_help": _FIELDS_HELP,
        "today": today(),
    })


# --------------------------------------------------------------------------
# Форматирование
# --------------------------------------------------------------------------

@mcp.tool()
def format_reference(fields: dict, standard: str = "7.0.100",
                     nbsp: bool = False, content_type: bool = False) -> str:
    """Собрать ссылку или запись по одному стандарту и проверить результат.

    fields   — поля описания (list_source_types покажет какие)
    standard — 7.0.5 | 7.0.100 | 7.1 | 7.0.108
    nbsp     — неразрывные пробелы в инициалах и после «С.», «№» (для Word)
    content_type — только для 7.0.100. Область вида содержания
      («Текст : непосредственный») отключена в профиле проекта.
      Вид содержания и средство доступа — условно-обязательные элементы
      (4.4.2, 5.10.4, 5.10.8); включайте согласно требованиям описания.

    Возвращает готовую строку, разобранные поля и список замечаний.
    В ответе `type_label` — тип источника по-русски; покажите его пользователю
    вместе со ссылкой, чтобы было видно, чем именно её сочли.
    """
    return _dump(api.format_and_check(fields, standard=standard, nbsp=nbsp,
                                      content_type=content_type))


@mcp.tool()
def format_footnote_and_record(fields: dict, record_standard: str = "7.0.100",
                               nbsp: bool = False,
                               content_type: bool = False) -> str:
    """Обе формы одного источника сразу: подстрочная сноска и запись для списка.

    ЭТО ОСНОВНОЙ ИНСТРУМЕНТ для работы над диссертацией или статьёй: в тексте
    нужна сноска, в списке литературы — запись, поля у них одни и те же.
    Спрашивать «сноска или список» не нужно — отдавайте обе.

    record_standard — 7.0.100 (по умолчанию) или 7.1, если этого требует совет.
    Сноска всегда по 7.0.5-2008; для сетевого документа применяется
    уточняющий 7.0.108-2022.

    content_type — вывод области «Текст : непосредственный» в записи.
    По умолчанию отключён настройкой проекта, а не нормой о факультативности.
    """
    return _dump(api.format_pair(fields, record_standard=record_standard,
                                 nbsp=nbsp, content_type=content_type))


@mcp.tool()
def format_all_standards(fields: dict, nbsp: bool = False,
                         content_type: bool = False) -> str:
    """Одни и те же данные во всех четырёх стандартах — для сверки и выбора."""
    return _dump({
        "names": _STANDARD_NAMES,
        "results": api.format_all(fields, nbsp=nbsp, content_type=content_type),
    })


@mcp.tool()
def reformat_reference(raw: str, standard: str = "7.0.100",
                       nbsp: bool = False, autofix: bool = True,
                       type_override: str = "", content_type: bool = False) -> str:
    """Переоформить готовую (кривую) строку ссылки по стандарту.

    raw — ссылка «как есть» из текста. Разбор эвристический: всё, что не
    опозналось, попадает в `leftovers` и `parse_notes` — проверьте их глазами,
    прежде чем вставлять результат в работу.

    type_override — задать тип вручную, если определитель ошибся
    (например 'chapter' вместо 'article'). Список типов — list_source_types.

    В ответе `type_label` — тип по-русски, `type_detection` — почему он выбран
    и с какой уверенностью. ОБЯЗАТЕЛЬНО покажите это пользователю вместе с
    готовой строкой: при уверенности ниже высокой он должен иметь возможность
    поправить тип.
    """
    return _dump(api.reformat(raw, standard=standard, nbsp=nbsp,
                              autofix=autofix, type_override=type_override,
                              content_type=content_type))


@mcp.tool()
def parse_reference(raw: str) -> str:
    """Разобрать строку ссылки на поля, ничего не форматируя.

    Полезно, когда нужно достать данные и дополнить их из внешних баз
    перед сборкой описания. В ответе `type_detection` показывает, каким
    был определён тип источника, почему и насколько уверенно.
    """
    from gost_ref.parse import parse as _parse
    return _dump(_parse(raw))


@mcp.tool()
def validate_reference(fields: dict | None = None, rendered: str = "",
                       standard: str = "7.0.100") -> str:
    """Проверить описание и/или готовую строку на типовые ошибки.

    Ловит в том числе главную системную ошибку списков по ГОСТ Р 7.0.100-2018:
    «Текст : электронный» у печатного издания и URL без даты обращения.
    """
    from gost_ref.validate import check_string, validate as _validate
    key = api.resolve_standard(standard)
    if fields:
        return _dump(_validate(fields, standard=key, rendered=rendered))
    return _dump({"standard": key, "issues": check_string(rendered, standard=key)})


@mcp.tool()
def build_bibliography(items: list[dict], standard: str = "7.0.100",
                       sort: str = "alpha", numbered: bool = True,
                       nbsp: bool = False, content_type: bool = False) -> str:
    """Собрать список литературы целиком.

    items — массив описаний. sort: alpha (кириллица, затем латиница) | none.
    Возвращает готовый текст списка и отчёт по каждой записи.
    """
    return _dump(api.build_list(items, standard=standard, sort=sort,
                                numbered=numbered, nbsp=nbsp, content_type=content_type))


@mcp.tool()
def repeat_reference(mode: str, authors: str = "", pages: str = "",
                     fields: dict | None = None, standard: str = "7.0.5") -> str:
    """Повторная или вторичная ссылка по ГОСТ Р 7.0.5-2008.

    mode:
      ibid        — «Там же. С. 25.» (та же работа подряд)
      op_cit      — «Иванов И. И. Указ. соч. С. 364.» (нужны authors)
      short       — «Иванов И. И. Начало заглавия … С. 212.» (нужны fields)
      cited_from  — «Цит. по: …» (нужны fields источника-посредника)
      see_also    — «См. также: …»
    """
    mode = (mode or "").strip().lower()
    if mode == "ibid":
        return api.ibid(pages)
    if mode == "op_cit":
        return api.op_cit(authors, pages)
    if mode == "short":
        return api.short_form(fields or {}, pages)
    if mode == "cited_from":
        return api.cited_from(fields or {}, standard=standard)
    if mode == "see_also":
        return api.see_also(fields or {}, standard=standard)
    return _dump({"error": f"неизвестный режим «{mode}»",
                  "modes": ["ibid", "op_cit", "short", "cited_from", "see_also"]})


# --------------------------------------------------------------------------
# Внешние данные
# --------------------------------------------------------------------------

@mcp.tool()
def lookup_metadata(query: str, kind: str = "auto") -> str:
    """Найти метаданные источника во внешних базах.

    query — DOI, ISBN или заглавие.
    kind  — auto | doi | isbn | title

    Открытые базы: Crossref, DataCite, OpenAlex, OpenLibrary, Google Books,
    КиберЛенинка. У РИНЦ (eLibrary), РГБ, НЭБ и фонда Росстандарта открытого
    API нет — в `manual_checks` возвращаются ссылки для проверки вручную.

    Каждое найденное поле сопровождается `source`: перед тем как ставить
    описание в работу, сверьте данные по этому источнику.
    """
    try:
        return _dump(lookup.enrich(query, kind=kind))
    except lookup.LookupError as exc:
        return _dump({
            "error": str(exc),
            "manual_checks": lookup.manual_check_links(query),
        })


@mcp.tool()
def read_pdf_metadata(path: str, head_pages: int = 3, tail_pages: int = 2) -> str:
    """Достать выходные данные из PDF: метаданные файла, титул, оборот титула,
    последнюю страницу и кандидатов в поля (ISBN, УДК, ББК, DOI, год, город).

    Ничего не решает за вас: /Info в PDF часто заполнен конвертером, поэтому
    приоритет — текст титульного листа. Число страниц файла НЕ равно объёму
    издания.
    """
    try:
        return _dump(pdfmeta.extract(path, head_pages=head_pages, tail_pages=tail_pages))
    except Exception as exc:  # noqa: BLE001
        return _dump({"error": f"{type(exc).__name__}: {exc}", "path": path})


@mcp.tool()
def check_links(query: str) -> str:
    """Ссылки на базы без открытого API — РИНЦ, РГБ, НЭБ, фонд Росстандарта.

    Для проверки статуса ГОСТа передайте его обозначение.
    Сопоставьте статус редакции с целью цитирования.
    """
    return _dump(lookup.manual_check_links(query))


if __name__ == "__main__":
    mcp.run()
