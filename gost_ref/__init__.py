"""gost-ref — формирование библиографических ссылок и записей по ГОСТ.

Поддерживаемые стандарты:
  7.0.5    ГОСТ Р 7.0.5-2008   — библиографическая ссылка (подстрочные сноски)
  7.0.100  ГОСТ Р 7.0.100-2018 — библиографическая запись (список литературы, ВАК)
  7.1      ГОСТ 7.1-2003       — прежний стандарт записи
  7.0.108  ГОСТ Р 7.0.108-2022 — ссылки на сетевые электронные документы
"""

from .api import (
    STANDARDS, build_list, cited_from, format_all, format_and_check,
    format_pair, format_reference, ibid, op_cit, reformat, resolve_standard,
    see_also, short_form,
)
from .model import Person, Reference, SOURCE_TYPES
from .parse import parse
from .validate import validate

__version__ = "1.0.0"

__all__ = [
    "Person", "Reference", "SOURCE_TYPES", "STANDARDS",
    "format_reference", "format_all", "format_and_check", "format_pair",
    "build_list",
    "parse", "reformat", "validate", "resolve_standard",
    "ibid", "op_cit", "short_form", "cited_from", "see_also",
]
