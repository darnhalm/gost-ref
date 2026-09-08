"""Командная строка — то же ядро без MCP.

    echo '{"type":"book","authors":"Лихачев Д. С.","title":"Русская культура",
           "city":"СПб.","publisher":"Искусство","year":"2007","total_pages":"440"}' \\
      | gost-ref format --standard 7.0.100

    gost-ref pair < source.json          # сноска и запись сразу
    gost-ref reformat --standard 7.0.5 "Иванов И.И. Заглавие. М., 2020. 100 с."
    gost-ref pdf ~/книга.pdf
    gost-ref lookup 10.5406/ethnomusicology.58.3.0379
    gost-ref list --standard 7.0.100 < sources.json
"""

from __future__ import annotations

import argparse
import json
import sys

from . import api


def _read_json(path: str | None):
    raw = sys.stdin.read() if not path or path == "-" else open(path, encoding="utf-8").read()
    return json.loads(raw)


def _out(data) -> None:
    if isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gost-ref", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    # Общие флаги вешаем на подкоманды, а не только на корень: иначе
    # «gost-ref format -s 7.0.100» падает — argparse ждёт их до подкоманды.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--standard", "-s", default="7.0.100",
                        help="7.0.5 | 7.0.100 | 7.1 | 7.0.108")
    common.add_argument("--nbsp", action="store_true",
                        help="неразрывные пробелы для Word")
    common.add_argument("--content-type", dest="content_type", action="store_true",
                        help="вывести область вида содержания и средства доступа "
                             "для 7.0.100; в профиле проекта она отключена")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("format", parents=[common], help="описание из JSON → строка")
    p.add_argument("file", nargs="?", help="файл JSON или - для stdin")

    p = sub.add_parser("pair", parents=[common],
                       help="описание из JSON → сноска и запись для списка сразу")
    p.add_argument("file", nargs="?")
    p.add_argument("--record", default="7.0.100", choices=["7.0.100", "7.1"],
                   help="стандарт записи для списка литературы")

    p = sub.add_parser("all", parents=[common], help="описание из JSON → все четыре стандарта")
    p.add_argument("file", nargs="?")

    p = sub.add_parser("reformat", parents=[common], help="кривая строка → строка по стандарту")
    p.add_argument("text")
    p.add_argument("--type", dest="type_override", default="",
                   help="задать тип вручную, если определитель ошибся "
                        "(book, chapter, article, dissertation, abstract, "
                        "standard, law, treaty, website, webpage, archive, "
                        "media, preprint)")

    p = sub.add_parser("parse", parents=[common], help="кривая строка → поля")
    p.add_argument("text")

    p = sub.add_parser("list", parents=[common], help="массив описаний из JSON → список литературы")
    p.add_argument("file", nargs="?")
    p.add_argument("--sort", default="alpha", choices=["alpha", "none"])

    p = sub.add_parser("lookup", parents=[common], help="метаданные по DOI, ISBN или заглавию")
    p.add_argument("query")
    p.add_argument("--kind", default="auto", choices=["auto", "doi", "isbn", "title"])

    p = sub.add_parser("pdf", parents=[common], help="выходные данные из PDF")
    p.add_argument("path")

    args = parser.parse_args(argv)

    if args.cmd == "format":
        _out(api.format_and_check(_read_json(args.file), args.standard,
                                  nbsp=args.nbsp, content_type=args.content_type))
    elif args.cmd == "pair":
        _out(api.format_pair(_read_json(args.file), record_standard=args.record,
                             nbsp=args.nbsp, content_type=args.content_type))
    elif args.cmd == "all":
        _out(api.format_all(_read_json(args.file), nbsp=args.nbsp,
                            content_type=args.content_type))
    elif args.cmd == "reformat":
        _out(api.reformat(args.text, args.standard, nbsp=args.nbsp,
                          type_override=args.type_override, content_type=args.content_type))
    elif args.cmd == "parse":
        from .parse import parse
        _out(parse(args.text))
    elif args.cmd == "list":
        _out(api.build_list(_read_json(args.file), args.standard,
                            sort=args.sort, nbsp=args.nbsp, content_type=args.content_type))
    elif args.cmd == "lookup":
        from . import lookup
        try:
            _out(lookup.enrich(args.query, kind=args.kind))
        except lookup.LookupError as exc:
            _out({"error": str(exc), "manual_checks": lookup.manual_check_links(args.query)})
            return 1
    elif args.cmd == "pdf":
        from . import pdfmeta
        _out(pdfmeta.extract(args.path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
