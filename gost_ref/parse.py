"""Разбор сырой строки ссылки в поля.

Эвристика, а не парсер грамматики: вытаскивает то, что уверенно опознаётся,
и честно сообщает, что осталось неразобранным. Всё, что попало в `leftovers`,
человек (или модель) должен разложить по полям вручную.
"""

from __future__ import annotations

import re
from typing import Any

from .model import TYPE_NEIGHBOURS, space_initials, type_label
from .text import normalize_date, normalize_pages, tidy

# Номер позиции в списке литературы: «1.», «12)», «[3]», «11 » перед заглавием.
# Без его снятия заголовок записи не опознаётся — автор уезжает в заглавие.
_LIST_NUM_RE = re.compile(r"^\s*(?:\[(\d{1,4})\]|(\d{1,4})\s*[.)]|(\d{1,3})(?=\s+[А-ЯЁA-Z]))\s*")

_URL_STRIP_RE = re.compile(r"(?:https?://|www\.)\S+")
_URL_RE = re.compile(r"(?:URL\s*:\s*|Режим доступа\s*:\s*)?(https?://[^\s()<>«»\[\]]+)", re.I)
_ACCESS_RE = re.compile(r"\(\s*дата\s+обращения\s*:\s*([^)]+)\)", re.I)
_PUBDATE_RE = re.compile(r"Дата\s+публикации\s*:\s*([\d.]+)", re.I)
_DOI_RE = re.compile(r"(?:DOI\s*:?\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s,;)\]]+)", re.I)
_ISBN_RE = re.compile(r"ISBN\s*([\dXx\-–—\s]{10,25})", re.I)
_ISSN_RE = re.compile(r"ISSN\s*(\d{4}[-–]\d{3}[\dXx])", re.I)
_PAGES_RE = re.compile(r"\b(?:С|P{1,2})\.\s*(\d+\s*[-–—]\s*\d+|\d+)", re.I)
_TOTAL_RE = re.compile(r"\b(\d{1,4})\s*с\.(?!\s*[–—-]?\s*\d)", re.I)
_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
_VOLUME_RE = re.compile(r"\b(?:Т|Vol|V)\.\s*(\d+)", re.I)
_ISSUE_RE = re.compile(r"(?:№|\bNo\.|\bIss\.)\s*([\d/–—-]+(?:\s*\(\d+\))?)", re.I)
_PART_RE = re.compile(r"\bЧ\.\s*(\d+)", re.I)
_EDITION_RE = re.compile(
    r"(\d+-е\s+изд\.(?:,?\s*(?:перераб|доп|испр|стер|пересмотр)[а-я]*\.?)*)", re.I)
_CONTENT_RE = re.compile(r"Текст\s*:\s*(непосредственный|электронный)", re.I)
_SPECIALTY_RE = re.compile(r"(\d{2}\.\d{2}\.\d{2})")
# Готовый оборот из записи по 7.0.100. Разбирать его надо целиком: иначе шифр
# вырезался из заглавия, а «специальность «Название»» оставалось в нём —
# и форматтер добавлял свой оборот вторым.
_SPECIALTY_CLAUSE_RE = re.compile(
    r"\s*:\s*специальность\s*:?\s*(?:(\d{2}\.\d{2}\.\d{2})\s*)?"
    r"(?:«([^»]{3,140})»)?", re.I)

# «Москва : Наука, 2005», «М.: Вече, 2009», «Санкт-Петербург: Композитор. - 2007»
# Город — одно-три слова без инициалов; издательство — без двоеточия внутри,
# иначе «Серошевский В. Л. Якуты : опыт... Санкт-Петербург : Изд. ИРГО, 1896»
# разбирался как город «Серошевский В. Л. Якуты».
_IMPRINT_RE = re.compile(
    r"(?:^|[.–—]\s+(?:[-–—]\s+)*)\s*"
    # Либо ходовое сокращение места издания, либо название без точек внутри.
    # Точка в общей ветке запрещена намеренно: именно она пропускала
    # «Серошевский В. Л. Якуты» в поле города.
    r"(М\.|Л\.|СПб\.|Пг\.|Н\. Новгород|Ростов н/Д|"
    r"[А-ЯЁA-Z][А-Яа-яЁёA-Za-z\-]{2,24}"
    r"(?:[ \-][А-ЯЁA-Zа-яёa-z][А-Яа-яЁёA-Za-z\-]{1,20}){0,2})"
    r"\s*:\s*([^,:]{2,70}?)"
    r"\s*[,.]?\s*[-–—]?\s*(1[5-9]\d{2}|20\d{2})\b"
)
_IMPRINT_NOPUB_RE = re.compile(
    r"(?:^|[.–—]\s+(?:[-–—]\s+)*)\s*"
    r"(М\.|СПб\.|Л\.|Пг\.|Москва|Санкт-Петербург|Ленинград|Н\. Новгород|Ростов н/Д|"
    r"Екатеринбург|Новосибирск|Казань|Киев|Минск)"
    r"\s*,\s*(1[5-9]\d{2}|20\d{2})\b"
)

_DISS_RE = re.compile(
    r"(автореф(?:ерат)?\.?\s*дис(?:сертации)?|диссертаци[яиюей]|дис\.)"
    r"\s*(?:\.{2,3}|…)?\s*(?:на соискание[^:/]*)?", re.I
)

# Порядок важен: первое совпадение выигрывает, поэтому узкие приметы идут
# раньше широких. Каждая примета должна опираться на служебный оборот
# описания, а не на слово, которое может оказаться в заглавии книги.
_TYPE_HINTS = (
    ("abstract", re.compile(r"\bавтореф(?:ерат)?\.?\s*дис", re.I)),
    ("dissertation", re.compile(r"\bдис(?:\.\s*(?:\.{2,}|…)|сертац)", re.I)),
    ("standard", re.compile(r"^\s*(ГОСТ|ОСТ|СНиП|СП|ТУ)\s*[Р\d]", re.I)),
    # Нормативный акт опознаётся только вместе с номером или датой принятия:
    # без этого «Приказы в делопроизводстве» и «Указатель имён» уходили в law.
    ("law", re.compile(
        r"(?:федеральн\w*\s+закон|федер\.\s*закон|\bкодекс\b|№\s*\d+[-–]?ФЗ"
        # между «приказ» и номером обычно стоит орган: «приказ Минобрнауки от 1 ноября … № 1224»
        r"|\b(?:приказ|постановлени|указ|распоряжени)\w*"
        r"[А-ЯЁа-яё\s.\-]{0,50}?(?:№\s*\d|\bот\s+\d))", re.I)),
    # Окончание слова обязательно: иначе «Конвенциональность в искусстве» — договор.
    ("treaty", re.compile(
        r"\b(?:конвенци(?:я|и|ю|ей|й|ям|ями|ях)|деклараци(?:я|и|ю|ей|й)"
        r"|хартия|хартии|рекомендаци\w*\s+ЮНЕСКО)\b", re.I)),
    ("archive", re.compile(r"\bФ\.\s*\d+\.\s*Оп\.\s*\d+", re.I)),
    ("website", re.compile(r":\s*(?:офиц\.\s*)?(?:официальный\s+)?сайт\b", re.I)),
)


def parse(raw: str) -> dict[str, Any]:
    """Возвращает {'fields': {...}, 'leftovers': str, 'notes': [...]}"""
    text = space_initials(tidy(raw))
    notes: list[str] = []
    fields: dict[str, Any] = {}

    m = _LIST_NUM_RE.match(text)
    if m:
        fields["list_number"] = next(g for g in m.groups() if g)
        text = text[m.end():].strip()
    rest = text

    def take(pattern: re.Pattern, key: str | None = None, group: int = 1, transform=None):
        nonlocal rest
        m = pattern.search(rest)
        if not m:
            return None
        value = m.group(group).strip()
        if transform:
            value = transform(value)
        if key and value:
            fields[key] = value
        rest = (rest[:m.start()] + " " + rest[m.end():]).strip()
        return value

    # 1. Сетевые сведения
    take(_ACCESS_RE, "access_date", transform=normalize_date)
    take(_PUBDATE_RE, "publication_date", transform=normalize_date)
    take(_DOI_RE, "doi")
    url = take(_URL_RE, "url", transform=lambda u: u.rstrip(".,;»)"))
    take(_ISBN_RE, "isbn", transform=lambda s: tidy(s))
    take(_ISSN_RE, "issn")

    content = take(_CONTENT_RE)
    if content:
        fields["medium"] = "electronic" if content.lower() == "электронный" else "print"

    # 2. Объём
    take(_PAGES_RE, "pages", transform=normalize_pages)
    take(_TOTAL_RE, "total_pages")
    take(_VOLUME_RE, "volume")
    take(_PART_RE, "part")
    if not re.search(r"№\s*[\d/\-–]+[-–][А-ЯЁ]{2,}", rest):   # «№ 431-ФЗ» — не выпуск
        take(_ISSUE_RE, "issue")
    take(_EDITION_RE, "edition")

    # 3. Выходные данные
    m = _IMPRINT_RE.search(rest)
    if m:
        fields["city"] = m.group(1).strip(" ,;")
        fields["publisher"] = m.group(2).strip()
        fields["year"] = m.group(3)
        rest = (rest[:m.start()] + ". " + rest[m.end():]).strip()
    else:
        m = _IMPRINT_NOPUB_RE.search(rest)
        if m:
            fields["city"] = m.group(1).strip()
            fields["year"] = m.group(2)
            rest = (rest[:m.start()] + ". " + rest[m.end():]).strip()

    if "year" not in fields:
        # Год внутри кавычек принадлежит заглавию, а не выходным данным:
        # «The War of 1812» — не год издания.
        masked = re.sub(r"[«\"'‘“][^»\"'’”]{0,120}[»\"'’”]", lambda m: "·" * len(m.group(0)), rest)
        # Год в дате принятия акта («от 22.12.2020 № 431-ФЗ») и год как часть
        # содержания («отчёт за 1952 год») — не выходные данные.
        masked = re.sub(r"\bот\s+\d{1,2}\.\d{1,2}\.(\d{4})",
                        lambda m: m.group(0)[:-4] + "····", masked)
        masked = re.sub(r"(1[5-9]\d{2}|20\d{2})(?=\s*(?:год|г\.|гг\.))",
                        "····", masked)
        hits = list(_YEAR_RE.finditer(masked))
        if hits:
            last = hits[-1]
            fields["year"] = last.group(1)
            rest = (rest[:last.start()] + " " + rest[last.end():]).strip()

    # 4. Тип. Приметы ищем по тексту без URL: слово из адреса
    # («.../prikaz/...») не должно решать за описание.
    probe = _URL_STRIP_RE.sub(" ", text)
    detection: dict[str, Any] = {}
    for type_name, pattern in _TYPE_HINTS:
        m = pattern.search(probe)
        if m:
            fields["type"] = type_name
            detection = {
                "confidence": "высокая",
                "reason": f"в строке есть оборот «{tidy(m.group(0))}»",
            }
            break
    else:
        has_imprint = bool(fields.get("city") or fields.get("publisher"))
        has_numbering = bool(fields.get("issue") or fields.get("volume"))
        if "//" in rest:
            if has_numbering:
                fields["type"] = "article"
                detection = {"confidence": "средняя",
                             "reason": "есть «//» и номер или том выпуска"}
            elif url and not has_imprint:
                # «Заглавие // Название сайта. URL: …» — материал на сайте,
                # а не глава сборника: у сборника были бы город и год издания.
                fields["type"] = "webpage"
                detection = {"confidence": "средняя",
                             "reason": "есть «//» и URL, но нет города и издательства"}
            else:
                fields["type"] = "chapter"
                detection = {"confidence": "средняя",
                             "reason": "есть «//», но нет номера выпуска"}
        elif url:
            fields["type"] = "webpage"
            detection = {"confidence": "средняя", "reason": "есть URL, но нет «//»"}
        else:
            fields["type"] = "book"
            detection = {"confidence": "низкая",
                         "reason": "ни одной приметы не нашлось — взят тип по умолчанию"}

    if fields["type"] in ("dissertation", "abstract"):
        clause = _SPECIALTY_CLAUSE_RE.search(rest)
        if clause and (clause.group(1) or clause.group(2)):
            if clause.group(1):
                fields["specialty"] = clause.group(1)
            if clause.group(2):
                fields["specialty_name"] = clause.group(2).strip()
            rest = (rest[:clause.start()] + " " + rest[clause.end():]).strip()
        spec = _SPECIALTY_RE.search(rest)
        if spec and "specialty" not in fields:
            fields["specialty"] = spec.group(1)
        deg = re.search(
            r"(?:степени\s+)?(канд(?:идата)?\.?|д-?ра|докт(?:ора)?\.?)\s+"
            r"([а-яё]+\.?(?:\s+наук)?)", rest, re.I)
        if deg:
            fields["degree"] = tidy(deg.group(0))
        rest = _DISS_RE.sub(" ", rest)
        rest = re.sub(
            r"(?:степени\s+)?(канд(?:идата)?\.?|д-?ра|докт(?:ора)?\.?)\s+"
            r"[а-яё]+\.?(?:\s+наук)?", " ", rest, flags=re.I)
        rest = _squeeze(_SPECIALTY_RE.sub(" ", rest))

    # 5. Контейнер (после «//»)
    if "//" in rest:
        parts = rest.split("//")
        if len(parts) > 2 and _RESPONSIBILITY_AHEAD_RE.match(parts[1]):
            # первое «//» — опечатка вместо «/»: дальше идут сведения
            # об ответственности, а не название источника
            rest = parts[0] + " / " + "//".join(parts[1:])
            notes.append("В записи два «//»; первое принято за опечатку "
                         "вместо «/» перед сведениями об ответственности.")
        left, right = rest.split("//", 1)
        rest = left.strip()
        container = _squeeze(_strip_areas(right))
        container = re.sub(r"^[\s.,–—-]+", "", container).strip(" .,;")
        if ":" in container and fields["type"] != "book":
            head, tail = container.split(":", 1)
            if len(tail.strip()) < 60:
                fields["container"] = head.strip()
                fields["container_subtitle"] = tail.strip(" .,;")
            else:
                fields["container"] = container
        else:
            fields["container"] = container

    # 6. Автор и заглавие
    rest = _squeeze(_strip_areas(rest))
    rest = _harvest_segments(rest, fields)
    rest = _squeeze(rest)
    author_part, title_part, resp = _split_author_title(rest)
    if author_part:
        fields["authors"] = author_part
    for field, value in resp.items():
        if field == "authors":
            # В заголовке стоит только первый автор, полный перечень — после «/».
            # Берём тот список, где лиц больше.
            current = fields.get("authors", "")
            if value.count(".") >= current.count("."):
                fields["authors"] = value
        elif field == "organization" and fields["type"] in ("dissertation", "abstract"):
            fields["institution"] = value
        else:
            fields.setdefault(field, value)
    if title_part:
        title_part = re.sub(r"(?<=[а-яёa-z0-9])\s*:\s*(?=[А-ЯЁA-Zа-яёa-z])", " : ", title_part)
        if " : " in title_part:
            head, tail = title_part.split(" : ", 1)
            fields["title"] = head.strip(" :;,")
            fields["subtitle"] = tail.strip(" :;,")
        else:
            fields["title"] = title_part.strip(" :;,")

    leftovers = ""
    if not fields.get("title"):
        leftovers = rest
        notes.append("Заглавие не опознано — заполните вручную.")

    if fields.get("url") and fields.get("medium") == "print":
        notes.append("В строке есть URL, но указан «Текст : непосредственный» — противоречие.")

    detection.update({
        "type": fields["type"],
        "label": type_label(fields["type"]),
        "alternatives": [
            {"type": t, "label": type_label(t)}
            for t in TYPE_NEIGHBOURS.get(fields["type"], [])
        ],
    })
    if detection["confidence"] != "высокая":
        notes.append(
            f"Тип определён как «{detection['label']}» ({detection['reason']}). "
            "Если это не так — задайте тип явно."
        )

    return {"fields": fields, "leftovers": leftovers,
            "notes": notes, "type_detection": detection}


_KNOWN_CITIES = (
    "Москва", "Санкт-Петербург", "СПб.", "СПб", "М.", "Л.", "Ленинград",
    "Казань", "Новосибирск", "Екатеринбург", "Нижний Новгород",
    "Ростов-на-Дону", "Ростов н/Д", "Томск", "Самара", "Воронеж", "Киев", "Минск",
)


def _squeeze(s: str) -> str:
    """Убирает следы вырезанных кусков: « : . », « . . », висячие тире."""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\s*:\s*(?=[.,;:]|$)", "", s)
        s = re.sub(r"\s*:\s*:\s*", " : ", s)
        s = re.sub(r"(?:\.\s*){2,}", ". ", s)
        s = re.sub(r"\s+[-–—]\s*(?=[.]|$)", "", s)
        s = re.sub(r"\s*[.,:]?\s*…(?=\s|$)", "", s)          # хвост от «дис. …»
        s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" .,;:-–—")


def _harvest_segments(rest: str, fields: dict) -> str:
    """Отделяет от хвоста то, что опознаётся однозначно: город, примечание об
    обновлении. Остальное остаётся в описании."""
    segments = [seg.strip() for seg in re.split(r"\.\s+", rest) if seg.strip()]
    if len(segments) <= 1:
        return rest
    kept = [segments[0]]
    for seg in segments[1:]:
        bare = seg.strip(" .,;")
        if not fields.get("city") and bare in _KNOWN_CITIES:
            fields["city"] = bare
            continue
        if re.match(r"^Обновляется", bare, re.I):
            fields["update_note"] = bare
            continue
        kept.append(seg)
    return ". ".join(kept)


# Что может стоять сразу после разделителя областей: год, номер, страницы,
# объём или «Город :». Если дальше строчная буква — это тире внутри заглавия
# («Музейная экспозиция - музейная коммуникация»), и трогать его нельзя.
_AREA_AHEAD = (
    r"(?=(?:\d{4}\b|№|Вып\.|Т\.\s*\d|Ч\.\s*\d|С\.\s*\d|\d+\s*с\.|"
    r"ISBN|ISSN|URL|Режим доступа|Текст\s*:|\d+-е\s+изд|"
    r"[А-ЯЁA-Z][А-Яа-яЁёA-Za-z.\- ]{0,28}\s*:))"
)


def _strip_areas(s: str) -> str:
    """Убирает разделители областей « . — », « . – », « . - » (7.0.100 / 7.1)."""
    s = re.sub(r"\s*\.?\s+[–—]\s+" + _AREA_AHEAD, ". ", s)
    s = re.sub(r"\s*\.?\s+-\s+" + _AREA_AHEAD, ". ", s)
    return re.sub(r"(?:\.\s*){2,}", ". ", s)


# Похоже на перечень лиц: «И. О. Фамилия», «Фамилия И. О.», «Фамилия Имя Отчество»
_PERSON_LIST_RE = re.compile(
    r"^\s*(?:(?:[А-ЯЁA-Z]\.\s*){1,3}[А-ЯЁA-Z][а-яёa-zА-ЯЁA-Z\-]+"
    r"|[А-ЯЁA-Z][а-яёa-z\-]+,?\s*(?:[А-ЯЁA-Z]\.\s*){1,3}"
    r"|[А-ЯЁA-Z][а-яёa-z\-]+\s+[А-ЯЁA-Z][а-яёa-z\-]+(?:\s+[А-ЯЁA-Z][а-яёa-z\-]+)?)\s*$"
    r"|^\s*(?:[А-ЯЁA-Z]\.\s*){1,3}[А-ЯЁA-Z][а-яёa-z\-]+\s*(?:,\s*(?:[А-ЯЁA-Z]\.\s*){1,3}"
    r"[А-ЯЁA-Z][а-яёa-z\-]+\s*)*$")

# «И. О. Фамилия» сразу после разделителя — это сведения об ответственности,
# а не название журнала.
_RESPONSIBILITY_AHEAD_RE = re.compile(
    r"^\s*(?:[А-ЯЁA-Z]\.\s*){1,3}[А-ЯЁA-Z][а-яёa-z\-]+")

_AUTHOR_HEAD_RE = re.compile(
    r"^\s*((?:[А-ЯЁ][а-яё\-]+,?\s+(?:[А-ЯЁ]\.\s*){1,3}[;,]?\s*){1,4})(?=[А-ЯЁ«\"])"
)
_AUTHOR_HEAD_LATIN_RE = re.compile(
    r"^\s*((?:[A-Z][a-z\-]+,?\s+(?:[A-Z]\.\s*){1,3}[;,]?\s*){1,4})(?=[A-Z«\"])"
)


# Что стоит после « / »: авторы или всё-таки редактор, составитель, переводчик.
_ROLE_RE = re.compile(
    r"^(?:(под\s+(?:общ\.|общей|науч\.|научн\.)?\s*ред(?:акцией)?\.?|отв\.\s*ред\.?"
    r"|ред\.-?\s*сост\.?|гл\.\s*ред\.?)"
    r"|(сост(?:авители?)?\.?)"
    r"|(пер(?:евод)?\.?(?:\s+с\s+\S+)?))\s*:?\s*(.+)$", re.I)

_ROLE_FIELDS = ("editors", "compilers", "translators")


def _split_responsibility(part: str) -> dict[str, str]:
    """Разбирает всё после « / » по группам, разделённым « ; ».

    «Ж. Диди-Юберман ; [пер. с фр. А. Шестакова] ; СПбГУ» →
    {authors: …, translators: …, organization: …}. Раньше бралась только
    первая группа, и переводчик, учреждение и часть соавторов пропадали.
    """
    out: dict[str, str] = {}
    for chunk in re.split(r"\s*;\s*", part):
        chunk = chunk.strip().strip("[]").strip(" .,;")
        if not chunk:
            continue
        m = _ROLE_RE.match(chunk)
        if m:
            field = next(f for f, gr in zip(_ROLE_FIELDS, m.groups()[:3]) if gr)
            value = m.group(4).strip(" .,;[]")
            out[field] = f"{out[field]}, {value}" if field in out else value
        elif _PERSON_LIST_RE.match(chunk):
            out["authors"] = f"{out['authors']}, {chunk}" if "authors" in out else chunk
        else:
            # не роль и не имя — учреждение
            out["organization"] = chunk
    return out


def _split_author_title(s: str) -> tuple[str, str, dict[str, str]]:
    """Отделяет заголовок записи от заглавия и сведений об ответственности."""
    resp: dict[str, str] = {}
    if " / " in s:
        s, resp_part = s.split(" / ", 1)
        resp = _split_responsibility(resp_part)

    m = _AUTHOR_HEAD_RE.match(s) or _AUTHOR_HEAD_LATIN_RE.match(s)
    if m:
        authors = m.group(1).strip(" ,;")
        title = s[m.end():].strip()
        return authors, title, resp
    return "", s.strip(), resp
