"""Текстовые утилиты: тире, города, даты, страницы, сборка областей."""

from __future__ import annotations

import re
from datetime import date

EM_DASH = "—"   # — область описания в ГОСТ Р 7.0.100-2018
EN_DASH = "–"   # – диапазоны страниц и области в ГОСТ 7.1-2003
NBSP = " "


# --------------------------------------------------------------------------
# Города
# --------------------------------------------------------------------------

CITY_ABBR = {
    "москва": "М.",
    "санкт-петербург": "СПб.",
    "ленинград": "Л.",
    "петроград": "Пг.",
    "петербург": "СПб.",
    "нижний новгород": "Н. Новгород",
    "ростов-на-дону": "Ростов н/Д",
    "лондон": "Л.",
    "london": "L.",
    "paris": "P.",
    "париж": "П.",
    "new york": "N. Y.",
    "нью-йорк": "Н.-Й.",
    "berlin": "B.",
    "киев": "Киев",
    "минск": "Минск",
}

CITY_FULL = {
    "м.": "Москва",
    "м": "Москва",
    "спб": "Санкт-Петербург",
    "л": "Ленинград",
    "мск": "Москва",
    "спб.": "Санкт-Петербург",
    "спб": "Санкт-Петербург",
    "л.": "Ленинград",
    "пг.": "Петроград",
    "н. новгород": "Нижний Новгород",
    "н.новгород": "Нижний Новгород",
    "ростов н/д": "Ростов-на-Дону",
    "ростов н/Д": "Ростов-на-Дону",
    "екатеринбург": "Екатеринбург",
}


def city_short(value: str) -> str:
    """Город в сокращённой форме — ГОСТ 7.1-2003, 7.0.5-2008, 7.0.108-2022."""
    parts = [p.strip() for p in re.split(r"\s*;\s*", tidy(value)) if p.strip()]
    out = []
    for p in parts:
        key = p.lower().rstrip(".")
        out.append(CITY_ABBR.get(p.lower(), CITY_ABBR.get(key, p)))
    return " ; ".join(out)


def city_full(value: str) -> str:
    """Город полностью — ГОСТ Р 7.0.100-2018 сокращений названий мест не допускает."""
    parts = [p.strip() for p in re.split(r"\s*;\s*", tidy(value)) if p.strip()]
    out = []
    for p in parts:
        out.append(CITY_FULL.get(p.lower(), p))
    return " ; ".join(out)


# --------------------------------------------------------------------------
# Мелкая нормализация
# --------------------------------------------------------------------------

def tidy(value) -> str:
    """Схлопывает пробелы, снимает висячие знаки."""
    s = str(value or "").replace(" ", " ").replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" ,;")


def clean_dash(value: str) -> str:
    return re.sub(r"\s*[-‐-―]\s*", EN_DASH, str(value or "")) if value else ""


def normalize_pages(value: str) -> str:
    """«45-52», «45 – 52», «С. 45-52» → «45–52»."""
    s = tidy(value)
    if not s:
        return ""
    s = re.sub(r"^[СCsS]\.?\s*", "", s)
    s = re.sub(r"\s*с\.?\s*$", "", s, flags=re.I)
    m = re.match(r"^(\d+)\s*[-‐-―]\s*(\d+)$", s)
    if m:
        return f"{m.group(1)}{EN_DASH}{m.group(2)}"
    return s


_MONTHS = {
    "янв": "01", "фев": "02", "мар": "03", "апр": "04", "ма": "05", "июн": "06",
    "июл": "07", "авг": "08", "сен": "09", "окт": "10", "ноя": "11", "дек": "12",
}


def normalize_date(value: str) -> str:
    """Любую внятную дату приводит к ДД.ММ.ГГГГ."""
    s = tidy(value)
    if not s:
        return ""
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", s):
        return s
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        return f"{int(m.group(1)):02d}.{int(m.group(2)):02d}.{m.group(3)}"
    m = re.fullmatch(r"(\d{1,2})\s+([А-Яа-яё]+)\.?\s+(\d{4})\s*(?:г\.?)?", s)
    if m:
        for stem, num in _MONTHS.items():
            if m.group(2).lower().startswith(stem):
                return f"{int(m.group(1)):02d}.{num}.{m.group(3)}"
    return s


def today() -> str:
    return date.today().strftime("%d.%m.%Y")


def apply_nbsp(s: str) -> str:
    """Неразрывные пробелы там, где перенос строки в Word портит вид."""
    s = re.sub(r"\b([А-ЯЁA-Z]\.)\s+([А-ЯЁA-Z]\.)", rf"\1{NBSP}\2", s)
    s = re.sub(r"\b([А-ЯЁA-Z]\.)\s+(?=[А-ЯЁA-Z][а-яёa-z])", rf"\1{NBSP}", s)
    s = re.sub(r"(?<=[а-яёa-z])\s+([А-ЯЁA-Z]\.\s*[А-ЯЁA-Z]\.)", rf"{NBSP}\1", s)
    s = re.sub(r"\b(С\.|Т\.|Ч\.|Вып\.|№|с\.)\s+", rf"\1{NBSP}", s)
    return s


# --------------------------------------------------------------------------
# Сборка
# --------------------------------------------------------------------------

def join_areas(parts, dash: str) -> str:
    """Соединяет области знаком « . — », не удваивая точку после сокращений."""
    out = ""
    for raw in parts:
        p = str(raw).strip()
        if not p:
            continue
        if not out:
            out = p
            continue
        out = f"{out} {dash} {p}" if out.endswith((".", "!", "?")) else f"{out}. {dash} {p}"
    return out


_LATIN_RE = re.compile(r"[A-Za-z]")
_CYR_RE = re.compile(r"[А-Яа-яЁё]")


def is_latin(*chunks) -> bool:
    """Латиница ли источник: у иностранных изданий другие обозначения томов."""
    text = " ".join(str(c or "") for c in chunks)
    return len(_LATIN_RE.findall(text)) > len(_CYR_RE.findall(text))


LABELS_RU = {"vol": "Т.", "issue": "№", "part": "Ч.", "pages": "С.", "extent": "с."}
LABELS_LAT = {"vol": "Vol.", "issue": "No.", "part": "Pt.", "pages": "P.", "extent": "p."}


def labels(latin: bool) -> dict:
    return LABELS_LAT if latin else LABELS_RU


def end_sentence(s: str) -> str:
    """Ставит завершающую точку, если её нет."""
    s = s.rstrip()
    if not s:
        return s
    if s.endswith((".", "!", "?")):
        return s
    if s.endswith(")"):
        return s + "."
    return s + "."


def with_subtitle(title: str, subtitle: str) -> str:
    """«Заглавие : сведения, относящиеся к заглавию»."""
    title = tidy(title)
    subtitle = tidy(subtitle)
    if not subtitle:
        return title
    return f"{title} : {subtitle}"


def responsibility_list(people, max_named: int = 4, et_al: str = "[и др.]") -> str:
    """«И. И. Иванов, П. П. Петров» либо «И. И. Иванов [и др.]»."""
    people = [p for p in people if p.surname or p.initials]
    if not people:
        return ""
    if len(people) > max_named:
        return f"{people[0].responsibility()} {et_al}"
    return ", ".join(p.responsibility() for p in people)


def heading_list(people, comma: bool) -> str:
    """Заголовок для подстрочной ссылки: до трёх авторов через запятую."""
    people = [p for p in people if p.surname or p.initials]
    if not people:
        return ""
    if len(people) > 3:
        return people[0].heading(comma=comma)
    return ", ".join(p.heading(comma=comma) for p in people)


def role_group(people, label: str) -> str:
    """«под редакцией И. И. Иванова», «перевод с английского М. Лорие»."""
    people = [p for p in people if p.surname or p.initials]
    if not people:
        return ""
    return f"{label} {responsibility_list(people)}"


def join_sentences(parts) -> str:
    """Соединяет области точкой, не удваивая её после сокращений («416 с.»)."""
    out = ""
    for raw in parts:
        p = str(raw).strip()
        if not p:
            continue
        if not out:
            out = p
            continue
        out = f"{out} {p}" if out.endswith((".", "!", "?")) else f"{out}. {p}"
    return out


# --------------------------------------------------------------------------
# Обозначение нормативного акта
# --------------------------------------------------------------------------

_BARE_NUMBER_RE = re.compile(r"^[\d][\d\-./]*(?:[-–—][А-ЯЁA-Z]{1,4})?$")
_BARE_DATE_RE = re.compile(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}$|^\d{4}-\d{2}-\d{2}$")
_VERB_RE = re.compile(r"^(принят|одобрен|утвержд|введ|подписан)", re.I)


def act_designation(doc_number: str = "", adopted: str = "") -> str:
    """Обозначение акта одной фразой: «от 23.07.2020 № 827».

    По ГОСТ дата принятия и номер документа образуют единое обозначение,
    а не два самостоятельных элемента. Раздельная подача полей — частый
    случай (данные приходят из карточки базы), поэтому склеиваем здесь,
    а не в каждом форматтере.

    Уже оформленные значения не трогаем: «№ 827» останется как есть,
    «принят Государственной Думой 21.07.2020» — тоже.
    """
    number = tidy(doc_number)
    date = tidy(adopted)

    if number and _BARE_NUMBER_RE.match(number):
        number = f"№ {number}"
    if date and _BARE_DATE_RE.match(date):
        date = f"от {date}"

    if date and number:
        # «от …» всегда впереди номера; глагольная форма — позади.
        if _VERB_RE.match(date):
            return f"{number} ({date})"
        return f"{date} {number}"
    return date or number


def title_with_designation(title: str, subtitle: str,
                           doc_number: str = "", adopted: str = "") -> str:
    """Заглавие с подзаголовком и обозначением акта.

    Обозначение примыкает к подзаголовку через пробел («… : приказ … от
    23.07.2020 № 827»), потому что вместе они образуют одни сведения,
    относящиеся к заглавию. Без подзаголовка обозначение вводится
    двоеточием как самостоятельные сведения.
    """
    full = with_subtitle(title, subtitle)
    designation = act_designation(doc_number, adopted)
    if not designation:
        return full
    if not full:
        return designation
    return f"{full} {designation}" if tidy(subtitle) else f"{full} : {designation}"
