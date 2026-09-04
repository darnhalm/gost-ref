"""Проверка описания на типовые ошибки.

Отдельно проверяются данные (полнота и непротиворечивость) и готовая строка
(предписанные знаки). Каждая находка имеет уровень:
  error   — запись не соответствует стандарту, правку требуют
  warning — почти наверняка ошибка, но бывают исключения
  note    — стоит перепроверить руками
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from .model import Reference
from .text import has_wrong_designation_dash, tidy


def _issue(level: str, code: str, message: str, fix: str = "") -> dict[str, str]:
    out = {"level": level, "code": code, "message": message}
    if fix:
        out["fix"] = fix
    return out


# --------------------------------------------------------------------------
# Проверка данных
# --------------------------------------------------------------------------

def check_fields(ref: Reference, standard: str = "7.0.100") -> list[dict[str, str]]:
    found: list[dict[str, str]] = []

    if not ref.title:
        found.append(_issue("error", "no-title", "Нет основного заглавия."))

    if not ref.primary_authors and ref.type in ("book", "article", "chapter", "dissertation", "abstract"):
        found.append(_issue("note", "no-author",
                            "Автор не указан. Для сборников и справочников это норма, "
                            "для статьи и монографии — обычно пропуск."))

    # Вид содержания против наличия URL
    if ref.url and ref.medium == "print":
        found.append(_issue("error", "medium-conflict",
                            "Указан URL, но вид содержания «непосредственный».",
                            "Либо medium=electronic, либо уберите URL."))
    if not ref.url and ref.medium == "electronic" and ref.type not in ("website", "webpage"):
        found.append(_issue("error", "electronic-no-url",
                            "Вид содержания «электронный», но URL отсутствует.",
                            "Это та самая системная ошибка списков: «Текст : электронный» "
                            "ставят печатным изданиям."))

    if ref.url and not ref.access_date and not ref.publication_date:
        found.append(_issue("warning", "no-access-date",
                            "URL без даты обращения. Дата обращения обязательна "
                            "по 7.0.5, 7.0.100 и 7.0.108, но на практике её "
                            "опускают, поэтому это замечание, а не ошибка.",
                            "Добавьте access_date в формате ДД.ММ.ГГГГ."))

    if ref.access_date:
        try:
            d = datetime.strptime(ref.access_date, "%d.%m.%Y").date()
            if d > date.today():
                found.append(_issue("error", "future-date",
                                    f"Дата обращения {ref.access_date} в будущем."))
        except ValueError:
            found.append(_issue("error", "bad-date",
                                f"Дата обращения «{ref.access_date}» не в формате ДД.ММ.ГГГГ."))

    if not ref.year and ref.type not in ("website", "webpage", "archive"):
        found.append(_issue("warning", "no-year", "Не указан год."))

    if ref.type == "book":
        if not ref.city:
            found.append(_issue("warning", "no-city",
                                "Не указано место публикации — обязательный элемент "
                                "(ГОСТ Р 7.0.100-2018, таблица 1)."))
        if not ref.publisher and standard in ("7.0.100", "7.1"):
            found.append(_issue("warning", "no-publisher",
                                "Не указано имя издателя — обязательный элемент записи "
                                "(ГОСТ Р 7.0.100-2018, таблица 1). В подстрочной ссылке "
                                "по 7.0.5 его допустимо опустить."))
        if not ref.total_pages:
            found.append(_issue("warning", "no-extent",
                                "Не указан объём («250 с.») — обязательный элемент "
                                "(ГОСТ Р 7.0.100-2018, таблица 1)."))

    if ref.type == "article":
        if not ref.container:
            found.append(_issue("error", "no-container", "Статья без названия журнала."))
        if not ref.pages:
            found.append(_issue("warning", "no-pages", "Статья без страниц («С. 45–52»)."))
        if not ref.issue and not ref.volume:
            found.append(_issue("warning", "no-issue", "Не указаны том или номер."))

    if ref.type in ("dissertation", "abstract"):
        if not ref.specialty:
            found.append(_issue("warning", "no-specialty",
                                "Не указан шифр специальности (например 24.00.01)."))
        if not ref.degree:
            found.append(_issue("warning", "no-degree", "Не указана искомая степень."))

    if ref.type == "standard" and not ref.doc_number:
        found.append(_issue("error", "no-designation",
                            "У стандарта нет обозначения («ГОСТ Р 7.0.100-2018»)."))

    if ref.type == "standard":
        found.append(_issue("note", "check-status",
                            "Проверьте действующий статус стандарта в фонде Росстандарта: "
                            "protect.gost.ru — отменённый ГОСТ в списке считается ошибкой."))

    if ref.type == "standard" and tidy(ref.doc_number) \
            and not re.match(r"^(ГОСТ|ОСТ|СТО|СТБ|ПНСТ|ISO|IEC|EN|DIN)\b",
                             tidy(ref.doc_number), re.I):
        found.append(_issue("warning", "designation-no-index",
                            "В обозначении нет индекса документа: ожидается "
                            "«ГОСТ Р 7.0.5-2008», а не «7.0.5-2008». Без индекса "
                            "ссылка не опознаётся как ссылка на стандарт."))

    if has_wrong_designation_dash(ref.doc_number):
        found.append(_issue("warning", "designation-dash",
                            "В обозначении стоял не дефис-минус — приведено к нему. "
                            "Обозначение стандарта — идентификатор: во всех примерах самого "
                            "ГОСТ Р 1.5-2012 (п. 7.1) и в перечнях Росстандарта напечатан "
                            "дефис-минус, и поиск в фонде Росстандарта и РИНЦ находит документ "
                            "только по нему. Слово «тире» в п. 7.1 расходится с его же "
                            "примерами — поэтому это замечание, а не ошибка."))

    if len(ref.primary_authors) > 3 and standard in ("7.0.100", "7.1"):
        found.append(_issue("note", "many-authors",
                            "Четыре и более авторов: заголовок записи не применяется, "
                            "описание начинается с заглавия."))

    if ref.doi and ref.url and "doi.org" in ref.url:
        found.append(_issue("note", "doi-duplicate",
                            "DOI продублирован в URL — достаточно одного элемента."))

    if standard == "7.0.108" and ref.doi and ref.pages and ref.container:
        found.append(_issue("note", "doi-scope",
                            "ГОСТ Р 7.0.108-2022: DOI приводят либо на составную часть, "
                            "либо на документ в целом, но не на оба сразу."))

    return found


# --------------------------------------------------------------------------
# Проверка готовой строки
# --------------------------------------------------------------------------

_STRING_CHECKS = (
    (r"\d\s*-\s*\d{2,}\s*\.\s*$", "warning", "hyphen-pages",
     "Диапазон страниц через дефис вместо короткого тире «–»."),
    (r"[А-ЯЁ]\.[А-ЯЁ]\.", "warning", "initials-no-space",
     "Инициалы без пробела: «И.И.» вместо «И. И.»."),
    # « ; » и « : » — предписанные знаки ГОСТа, пробел слева у них законный.
    # Многоточие в «дис. ... канд. наук» — тоже.
    (r"\s+,|\s+\.(?!\.)", "warning", "space-before-punct",
     "Пробел перед запятой или точкой."),
    (r"\S:\S", "warning", "colon-no-spaces",
     "Двоеточие без пробелов. В предписанной пунктуации ГОСТа оно окружено пробелами: « : »."),
    # Двоеточие без пробела слева. Служебные метки, где это норма
    # (URL:, дата обращения:, DOI, Режим доступа:), исключены явно.
    (r"(?<!URL)(?<!обращения)(?<!публикации)(?<!доступа)(?<!ISBN)(?<!ISSN)"
     r"(?<!DOI)(?<!\d)(?<=[^\s:]):\s",
     "warning", "colon-no-space-before",
     "Двоеточие без пробела слева («М.: Наука»). Предписанный знак — « : » с пробелами "
     "с обеих сторон: «М. : Наука»."),
    (r"[А-ЯЁ]\.\s*[А-ЯЁ]\.\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.", "note", "authors-no-comma",
     "Авторы в заголовке, похоже, разделены пробелом, а не запятой: "
     "«Пантелеев А. С., Звездин А. Л.»."),
    (r"//\S", "warning", "slashes-no-space", "После «//» нужен пробел."),
    (r"\S//", "warning", "slashes-no-space-before", "Перед «//» нужен пробел."),
    (r"\s{2,}", "note", "double-space", "Двойной пробел."),
    (r"(?<!\[)\bи\s+др\.", "warning", "et-al-no-brackets",
     "«и др.» без квадратных скобок. Предписанная форма — «[и др.]»: скобки "
     "показывают, что сведения взяты не из предписанного источника."),
    (r"(?:\s-\s.*){2,}", "warning", "hyphen-as-area-dash",
     "Области разделены дефисом « - » вместо тире. Ходовая ошибка онлайн-"
     "генераторов: в записи по 7.0.100 нужен « — », по 7.1 — « – », "
     "а в подстрочной ссылке разделителем служит точка."),
    (r"URL\s*:\s*\S+\s*$", "note", "url-no-access",
     "URL в конце без даты обращения."),
)


_URL_MASK_RE = re.compile(r"(?:https?://|www\.)\S+|10\.\d{4,9}/\S+")


def _mask_urls(text: str) -> str:
    """URL и DOI живут по своим правилам пунктуации: «http://», «//», «10.5406/».
    Проверять их знаками ГОСТа нельзя — иначе каждая сетевая ссылка ложно
    подсвечивается. Заменяем на нейтральную заглушку той же длины."""
    return _URL_MASK_RE.sub(lambda m: "u" * len(m.group(0)), text)


def check_string(s: str, standard: str = "7.0.100") -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    text = str(s or "")
    masked = _mask_urls(text)

    for pattern, level, code, message in _STRING_CHECKS:
        if re.search(pattern, masked):
            found.append(_issue(level, code, message))

    if standard == "7.0.100":
        if "—" not in masked:
            found.append(_issue("note", "no-area-dash",
                                "Области не разделены « . — ». Это допустимо: п. 4.6.4 "
                                "ГОСТ Р 7.0.100-2018 разрешает заменять знак «точка и тире» "
                                "точкой, если области выделены шрифтом или начинаются "
                                "с новой строки."))
        if not re.search(r"Текст\s*:|Изображение\s*:|Видео\s*:|Аудио\s*:", masked):
            found.append(_issue("note", "no-content-type",
                                "Нет области вида содержания «Текст : непосредственный». "
                                "По ГОСТ Р 7.0.100-2018 она факультативна — стандарт "
                                "делит элементы на обязательные, условно обязательные и "
                                "факультативные, и эта область в обязательные не входит. "
                                "Ставить её или нет, определяют требования совета "
                                "или редакции."))
        if re.search(r"(?:^|[.—]\s)(М\.|СПб\.|Л\.)\s*:", masked):
            found.append(_issue("warning", "abbreviated-city",
                                "Место издания сокращено. В записи по ГОСТ Р 7.0.100-2018 "
                                "его принято приводить полностью — «Москва», а не «М.»; "
                                "прямого запрета в тексте стандарта нет, но все примеры "
                                "и методики библиотек дают полную форму."))

    if standard in ("7.0.5", "7.0.108"):
        if "—" in masked or "–" in re.sub(r"\d\s*–\s*\d", "", masked):
            found.append(_issue("warning", "area-dash-in-reference",
                                "В библиографической ссылке тире между областями не ставится — "
                                "это признак записи по 7.0.100, попавшей в сноску."))
        if re.search(r"Текст\s*:\s*(непосредственный|электронный)", masked):
            found.append(_issue("warning", "content-type-in-reference",
                                "Область вида содержания относится к библиографической ЗАПИСИ "
                                "(7.0.100), в подстрочной ссылке она лишняя."))

    if not text.rstrip().endswith((".", ")")):
        found.append(_issue("warning", "no-final-dot", "Нет завершающей точки."))

    return found


def validate(data: Any, standard: str = "7.0.100", rendered: str = "") -> dict[str, Any]:
    ref = data if isinstance(data, Reference) else Reference.from_dict(data)
    issues = check_fields(ref, standard=standard)
    if rendered:
        issues += check_string(rendered, standard=standard)
    return {
        "standard": standard,
        "ok": not any(i["level"] == "error" for i in issues),
        "errors": [i for i in issues if i["level"] == "error"],
        "warnings": [i for i in issues if i["level"] == "warning"],
        "notes": [i for i in issues if i["level"] == "note"],
    }
