#!/usr/bin/env python3
"""MCP-сервер gost-ref: библиографические ссылки и записи по ГОСТ.

Тонкая обёртка над пакетом `gost_ref`. Вся логика стандартов живёт там —
здесь только объявление инструментов и способ запуска, чтобы к одному и тому
же ядру можно было обратиться из любого MCP-клиента.

Два режима одного файла:

    python server.py                               # stdio, как раньше
    python server.py --transport streamable-http   # remote MCP по HTTP

В remote-режиме сервер слушает $HOST:$PORT (по умолчанию 0.0.0.0:8080),
отдаёт MCP на /mcp и health на /health. Состояние между запросами не
хранится: инструменты — чистые функции над переданными полями, поэтому
контейнер можно убивать и размножать свободно.
"""

from __future__ import annotations

import argparse
import functools
import hmac
import json
import os
import sys
from pathlib import Path
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


async def _offload(fn, *args, **kwargs):
    """Блокирующий вызов — в поток, чтобы не держать цикл событий.

    FastMCP выполняет синхронные инструменты прямо в event loop. Сборка
    строки по ГОСТу занимает доли миллисекунды и этому не мешает, а вот
    сетевой lookup и чтение PDF — занимают секунды, и на общем сервере
    остановили бы всех остальных клиентов. Семантика инструмента не
    меняется: та же функция с теми же аргументами, только в рабочем потоке.
    """
    import anyio  # приходит вместе с mcp

    return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))


# --------------------------------------------------------------------------
# Режим работы
#
# Ядро `gost_ref` одинаково в обоих режимах. Различаются только внешние
# границы: доступ к файловой системе и потолки на размер запроса. Значения
# ставятся один раз при старте, во время обработки запроса не меняются —
# несколько экземпляров контейнера ведут себя одинаково.
# --------------------------------------------------------------------------

_PDF_MODE = "local"          # local (stdio) | sandbox | disabled
_PDF_DIR: Path | None = None
_PDF_MAX_BYTES = 64 * 1024 * 1024
_MAX_ITEMS = 0               # 0 — без ограничения (локальный режим)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _resolve_pdf_path(path: str) -> Path:
    """Путь к PDF с учётом режима запуска.

    stdio  — как раньше: сервер работает на машине пользователя с его же
             правами, ограничивать нечего.
    remote — либо запрещено вовсе, либо только внутри GOST_REF_PDF_DIR.
             `resolve()` снимает символические ссылки и `..`, поэтому выйти
             из каталога подстановкой пути нельзя.
    """
    if _PDF_MODE == "local":
        return Path(path).expanduser()

    if _PDF_MODE == "disabled" or _PDF_DIR is None:
        raise PermissionError(
            "чтение PDF по пути отключено в удалённом режиме. "
            "Оформляйте по данным титульного листа, DOI или ISBN "
            "(lookup_metadata), либо запустите сервер с GOST_REF_PDF_DIR."
        )

    base = _PDF_DIR.resolve()
    raw = Path(path)
    candidate = (raw if raw.is_absolute() else base / raw).resolve()
    if candidate != base and not candidate.is_relative_to(base):
        raise PermissionError(f"путь вне разрешённого каталога {base}")
    if not candidate.is_file():
        raise FileNotFoundError(str(candidate))
    size = candidate.stat().st_size
    if size > _PDF_MAX_BYTES:
        raise ValueError(f"файл больше допустимых {_PDF_MAX_BYTES} байт ({size})")
    return candidate


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
    if _MAX_ITEMS and len(items or []) > _MAX_ITEMS:
        return _dump({
            "error": f"за один вызов принимается не больше {_MAX_ITEMS} описаний",
            "received": len(items or []),
            "hint": "разбейте список на части — сортировка внутри части сохраняется",
        })
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
async def lookup_metadata(query: str, kind: str = "auto") -> str:
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
        return _dump(await _offload(lookup.enrich, query, kind=kind))
    except Exception as exc:  # noqa: BLE001 — сеть не должна ронять сервер
        return _dump({
            "error": f"{type(exc).__name__}: {exc}",
            "manual_checks": lookup.manual_check_links(query),
        })


@mcp.tool()
async def read_pdf_metadata(path: str, head_pages: int = 3,
                            tail_pages: int = 2) -> str:
    """Достать выходные данные из PDF: метаданные файла, титул, оборот титула,
    последнюю страницу и кандидатов в поля (ISBN, УДК, ББК, DOI, год, город).

    Ничего не решает за вас: /Info в PDF часто заполнен конвертером, поэтому
    приоритет — текст титульного листа. Число страниц файла НЕ равно объёму
    издания.

    `path` — путь к файлу. При локальном запуске (stdio) это любой путь на
    вашей машине. У сервера, поднятого по HTTP, чтение либо выключено, либо
    ограничено выделенным каталогом: произвольные файлы контейнера не читаются.
    """
    try:
        resolved = _resolve_pdf_path(path)
        return _dump(await _offload(pdfmeta.extract, str(resolved),
                                    head_pages=head_pages, tail_pages=tail_pages))
    except Exception as exc:  # noqa: BLE001
        return _dump({"error": f"{type(exc).__name__}: {exc}", "path": path})


@mcp.tool()
def check_links(query: str) -> str:
    """Ссылки на базы без открытого API — РИНЦ, РГБ, НЭБ, фонд Росстандарта.

    Для проверки статуса ГОСТа передайте его обозначение.
    Сопоставьте статус редакции с целью цитирования.
    """
    return _dump(lookup.manual_check_links(query))


# --------------------------------------------------------------------------
# Health
#
# Отдельного веб-сервера под это не поднимаем: маршрут живёт в том же
# Starlette-приложении, что и /mcp, и отвечает без обращения к сети и диску.
# --------------------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health(_request):  # pragma: no cover — тривиальный маршрут
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok", "service": "gost-ref"})


# --------------------------------------------------------------------------
# Авторизация remote-режима
# --------------------------------------------------------------------------

class BearerAuthMiddleware:
    """Статический токен в заголовке — чистый ASGI, без лишних зависимостей.

    Намеренно НЕ используется OAuth-обвязка MCP SDK (`AuthSettings`): она
    публикует метаданные защищённого ресурса, и клиенты, увидев их, начинают
    OAuth-поток вместо того, чтобы отправить настроенный заголовок. Простой
    Bearer совместим с клиентами, где заголовки задаются в конфигурации
    (Claude Code `--header`, mcp-remote). Клиентам, которым нужен OAuth,
    ставят внешний шлюз — см. README.
    """

    def __init__(self, app, token: str, exempt: tuple[str, ...] = ("/health",)):
        self.app = app
        self.token = token
        self.exempt = exempt

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "") in self.exempt:
            await self.app(scope, receive, send)
            return

        presented = ""
        for name, value in scope.get("headers") or []:
            if name == b"authorization":
                raw = value.decode("latin-1")
                presented = raw[7:].strip() if raw[:7].lower() == "bearer " else ""
                break
            if name == b"x-api-key":
                presented = value.decode("latin-1").strip()

        if presented and hmac.compare_digest(presented, self.token):
            await self.app(scope, receive, send)
            return

        body = json.dumps({"error": "unauthorized"}).encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b'Bearer realm="gost-ref"'),
            ],
        })
        await send({"type": "http.response.body", "body": body})


# --------------------------------------------------------------------------
# Запуск
# --------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="server.py",
        description="MCP-сервер gost-ref: stdio локально, streamable-http удалённо.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http"],
        default=os.environ.get("GOST_REF_TRANSPORT", "stdio"),
        help="stdio (по умолчанию) или streamable-http для remote MCP",
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=_env_int("PORT", 8080),
                        help="порт HTTP; в serverless приходит из $PORT")
    parser.add_argument("--path", default=os.environ.get("GOST_REF_MCP_PATH", "/mcp"),
                        help="путь MCP-эндпоинта (по умолчанию /mcp)")
    parser.add_argument("--pdf-dir", default=os.environ.get("GOST_REF_PDF_DIR", ""),
                        help="каталог, из которого read_pdf_metadata читает файлы "
                             "в remote-режиме; без него инструмент отвечает отказом")
    parser.add_argument("--allow-anonymous", action="store_true",
                        default=os.environ.get("GOST_REF_ALLOW_ANONYMOUS", "") == "1",
                        help="разрешить HTTP без GOST_REF_API_KEY (только для разработки)")
    parser.add_argument("--json-response", action="store_true",
                        default=os.environ.get("GOST_REF_JSON_RESPONSE", "") == "1",
                        help="отвечать обычным JSON вместо SSE-потока")
    parser.add_argument("--log-level", default=os.environ.get("GOST_REF_LOG_LEVEL", "INFO"),
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    return parser.parse_args(argv)


def _apply_runtime_limits(remote: bool, pdf_dir: str) -> None:
    global _PDF_MODE, _PDF_DIR, _PDF_MAX_BYTES, _MAX_ITEMS

    lookup.TIMEOUT = _env_int("GOST_REF_LOOKUP_TIMEOUT", lookup.TIMEOUT)
    _PDF_MAX_BYTES = _env_int("GOST_REF_PDF_MAX_BYTES", _PDF_MAX_BYTES)
    _MAX_ITEMS = _env_int("GOST_REF_MAX_ITEMS", 0)

    if not remote:
        _PDF_MODE, _PDF_DIR = "local", None
        return

    if pdf_dir:
        _PDF_DIR = Path(pdf_dir).expanduser()
        _PDF_DIR.mkdir(parents=True, exist_ok=True)
        _PDF_MODE = "sandbox"
    else:
        _PDF_MODE, _PDF_DIR = "disabled", None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    remote = args.transport == "streamable-http"
    _apply_runtime_limits(remote, args.pdf_dir)

    if not remote:
        mcp.run()
        return 0

    api_key = os.environ.get("GOST_REF_API_KEY", "").strip()
    if not api_key and not args.allow_anonymous:
        print(
            "gost-ref: остановлен. Публичный HTTP без авторизации не запускается.\n"
            "  задайте GOST_REF_API_KEY=<секрет> — клиент шлёт "
            "'Authorization: Bearer <секрет>';\n"
            "  либо явно разрешите анонимный доступ флагом --allow-anonymous "
            "(GOST_REF_ALLOW_ANONYMOUS=1) — только для локальной разработки "
            "или когда доступ закрыт снаружи (IAM, VPC, шлюз).",
            file=sys.stderr,
        )
        return 2

    # Без состояния между запросами: инструменты — чистые функции над
    # переданными полями, хранить сессию нечего. Контейнер можно убить в любой
    # момент, запросы одного клиента могут попасть в разные экземпляры.
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.settings.streamable_http_path = args.path
    mcp.settings.stateless_http = True
    mcp.settings.json_response = args.json_response
    mcp.settings.log_level = args.log_level

    app = mcp.streamable_http_app()
    if api_key:
        app = BearerAuthMiddleware(app, api_key, exempt=("/health",))
        auth_note = "Bearer-токен обязателен"
    else:
        auth_note = "БЕЗ АВТОРИЗАЦИИ (--allow-anonymous)"

    print(
        f"gost-ref MCP: http://{args.host}:{args.port}{args.path} — {auth_note}; "
        f"health http://{args.host}:{args.port}/health; "
        f"PDF: {_PDF_MODE}{f' ({_PDF_DIR})' if _PDF_DIR else ''}",
        file=sys.stderr,
    )

    import uvicorn  # приходит вместе с mcp; импорт только в remote-режиме

    uvicorn.run(app, host=args.host, port=args.port,
                log_level=args.log_level.lower(), access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
