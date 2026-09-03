"""Модель библиографического источника.

Один нейтральный набор полей, из которого каждый стандарт собирает свою строку.
Модель ничего не знает о ГОСТах — она только хранит выверенные данные.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional


# --------------------------------------------------------------------------
# Типы источников
# --------------------------------------------------------------------------

SOURCE_TYPES = {
    "book": "книга, монография, учебное пособие",
    "chapter": "глава книги, статья в сборнике, материалы конференции",
    "article": "статья в журнале или газете",
    "dissertation": "диссертация",
    "abstract": "автореферат диссертации",
    "standard": "ГОСТ, стандарт, нормативно-технический документ",
    "law": "закон, кодекс, указ, приказ, постановление",
    "treaty": "международный акт: конвенция, рекомендация, хартия",
    "website": "сайт целиком как ресурс",
    "webpage": "отдельный материал на сайте",
    "archive": "архивный документ",
    "media": "видео-, аудиоматериал",
    "preprint": "препринт, депонированная рукопись",
}

# Короткие названия для показа человеку. SOURCE_TYPES выше — развёрнутые
# пояснения для выбора типа; эти — подпись под готовой ссылкой.
TYPE_LABELS = {
    "book": "книга",
    "chapter": "глава книги или статья в сборнике",
    "article": "статья в журнале",
    "dissertation": "диссертация",
    "abstract": "автореферат диссертации",
    "standard": "стандарт (ГОСТ и подобные)",
    "law": "закон или нормативный акт",
    "treaty": "международный акт (конвенция, рекомендация)",
    "website": "сайт целиком",
    "webpage": "материал на сайте",
    "archive": "архивный документ",
    "media": "видео- или аудиоматериал",
    "preprint": "препринт",
}

# Типы, которые проще всего перепутать между собой. Показываем как подсказку:
# «если это на самом деле X — укажите type=X».
TYPE_NEIGHBOURS = {
    "chapter": ["article", "webpage"],
    "article": ["chapter", "webpage"],
    "webpage": ["article", "website"],
    "website": ["webpage"],
    "book": ["chapter", "dissertation"],
    "dissertation": ["abstract"],
    "abstract": ["dissertation"],
    "law": ["treaty", "standard"],
    "treaty": ["law"],
}


def type_label(type_name: str) -> str:
    return TYPE_LABELS.get(type_name, type_name)


SourceType = str

MEDIUM_PRINT = "print"
MEDIUM_ELECTRONIC = "electronic"

# Составные части: имеют «документ, в котором помещены» (после //)
COMPONENT_TYPES = {"chapter", "article", "webpage", "preprint"}

# Типы, которые по определению электронные
ALWAYS_ELECTRONIC = {"website", "webpage"}


# --------------------------------------------------------------------------
# Персона
# --------------------------------------------------------------------------

_INITIAL_RE = re.compile(r"^[А-ЯЁA-Z][а-яёa-z]?\.?$")
_GLUED_RE = re.compile(r"([А-ЯЁA-Z])\.(?=[А-ЯЁA-Z])")
# Типовая порча распознавания в PDF: фамилия слипается с инициалом
# («СурковаК.В.», «АбишеваВ.Т.»). В русском слове строчная буква не может
# стоять вплотную к прописной с точкой, поэтому разрыв безопасен.
_OCR_GLUED_SURNAME_RE = re.compile(r"([а-яёa-z])([А-ЯЁA-Z]\.)")


def space_initials(s: str) -> str:
    """«И.И.Иванов» → «И. И. Иванов»; иначе инициалы не опознаются."""
    s = _OCR_GLUED_SURNAME_RE.sub(r"\1 \2", str(s or ""))
    prev = None
    while prev != s:
        prev = s
        s = _GLUED_RE.sub(r"\1. ", s)
    return re.sub(r"\s+", " ", s).strip()
_PATRONYMIC_RE = re.compile(r"(ович|евич|ьич|инич|овна|евна|ична|инична)$", re.I)
_LOWER_PARTICLES = {"де", "ван", "фон", "да", "ди", "дель", "ла", "ле", "van", "von", "de", "di", "del", "la", "le"}


@dataclass
class Person:
    """Имя лица. `surname` обязательна, остальное восстанавливается."""

    surname: str = ""
    initials: str = ""          # «И. И.»
    given: str = ""             # «Иван Иванович» — полная форма, если известна
    role: str = ""              # редактор, переводчик, составитель, ответственный редактор

    # ---- разбор ----------------------------------------------------------

    @classmethod
    def parse(cls, raw: str, role: str = "") -> "Person":
        """Разбирает имя в любом ходовом написании.

        Понимает: «Иванов И. И.», «И. И. Иванов», «Иванов, И. И.»,
        «Иванов Иван Иванович», «Rancier M.», «Bates E.».
        """
        s = " ".join(str(raw or "").replace(" ", " ").split())
        if not s:
            return cls(role=role)
        s = space_initials(s)

        # «Иванов, И. И.» — запятая сразу отделяет фамилию
        if "," in s:
            head, tail = s.split(",", 1)
            head, tail = head.strip(), tail.strip()
            if head and not _INITIAL_RE.match(head.split()[0]):
                p = cls(surname=head, role=role)
                p._absorb_names(tail)
                return p

        tokens = s.split()
        initial_flags = [bool(_INITIAL_RE.match(t)) and len(t.rstrip(".")) <= 2 for t in tokens]

        if any(initial_flags):
            surname_tokens = [t for t, f in zip(tokens, initial_flags) if not f]
            initial_tokens = [t for t, f in zip(tokens, initial_flags) if f]
            p = cls(surname=" ".join(surname_tokens), role=role)
            p.initials = normalize_initials(" ".join(initial_tokens))
            return p

        # Полные имена без инициалов
        if len(tokens) >= 3 and _PATRONYMIC_RE.search(tokens[-1]):
            return cls(surname=tokens[0], given=" ".join(tokens[1:]), role=role)._filled()
        if len(tokens) == 2:
            # «Иванов Иван» — в русской традиции фамилия первая
            return cls(surname=tokens[0], given=tokens[1], role=role)._filled()
        if len(tokens) == 1:
            return cls(surname=tokens[0], role=role)
        return cls(surname=tokens[0], given=" ".join(tokens[1:]), role=role)._filled()

    def _absorb_names(self, tail: str) -> None:
        tokens = tail.split()
        if tokens and all(_INITIAL_RE.match(t) for t in tokens):
            self.initials = normalize_initials(tail)
        else:
            self.given = tail
            self._filled()

    def _filled(self) -> "Person":
        if not self.initials and self.given:
            self.initials = " ".join(f"{w[0]}." for w in self.given.split() if w)
        return self

    # ---- вывод -----------------------------------------------------------

    @property
    def short(self) -> str:
        """«И. И.» — инициалы, выведенные при необходимости."""
        if self.initials:
            return normalize_initials(self.initials)
        if self.given:
            return " ".join(f"{w[0]}." for w in self.given.split() if w)
        return ""

    def heading(self, comma: bool = False) -> str:
        """Заголовок записи: «Иванов И. И.» или «Иванов, И. И.»."""
        if not self.surname:
            return self.short
        if not self.short:
            return self.surname
        return f"{self.surname}, {self.short}" if comma else f"{self.surname} {self.short}"

    def responsibility(self) -> str:
        """Сведения об ответственности: «И. И. Иванов»."""
        if not self.surname:
            return self.short
        return f"{self.short} {self.surname}".strip()

    def full(self) -> str:
        """Полная форма: «Иванов Иван Иванович» (для диссертаций)."""
        if self.given:
            return f"{self.surname} {self.given}".strip()
        return self.heading()


def normalize_initials(raw: str) -> str:
    """«И.И.», «И. И», «ИИ» → «И. И.»"""
    letters = re.findall(r"[А-ЯЁA-Z]", str(raw or ""))
    return " ".join(f"{ch}." for ch in letters)


def as_people(value: Any, role: str = "") -> list[Person]:
    """Приводит что угодно к списку Person."""
    if value in (None, "", [], {}):
        return []
    if isinstance(value, Person):
        return [value]
    if isinstance(value, dict):
        return [Person(
            surname=value.get("surname", ""),
            initials=value.get("initials", ""),
            given=value.get("given", ""),
            role=value.get("role", role),
        )._filled()]
    if isinstance(value, str):
        # Строка со списком авторов через запятую или точку с запятой
        chunks = [c for c in re.split(r"\s*;\s*", value) if c.strip()]
        if len(chunks) == 1:
            chunks = _split_comma_authors(value)
        return [Person.parse(c, role=role) for c in chunks if c.strip()]
    if isinstance(value, (list, tuple)):
        out: list[Person] = []
        for item in value:
            out.extend(as_people(item, role=role))
        return out
    return [Person.parse(str(value), role=role)]


def _split_comma_authors(value: str) -> list[str]:
    """Делит «Иванов И. И., Петров П. П.» по запятым, не разрывая «Иванов, И. И.»."""
    parts = [p.strip() for p in value.split(",")]
    if len(parts) <= 1:
        return [value]
    merged: list[str] = []
    for part in parts:
        if not part:
            continue
        tokens = part.split()
        only_initials = tokens and all(_INITIAL_RE.match(t) for t in tokens)
        if only_initials and merged:
            merged[-1] = f"{merged[-1]}, {part}"
        else:
            merged.append(part)
    return merged


# --------------------------------------------------------------------------
# Источник
# --------------------------------------------------------------------------

@dataclass
class Reference:
    type: SourceType = "book"

    authors: list[Person] = field(default_factory=list)
    editors: list[Person] = field(default_factory=list)
    translators: list[Person] = field(default_factory=list)
    compilers: list[Person] = field(default_factory=list)

    title: str = ""              # основное заглавие
    subtitle: str = ""           # сведения, относящиеся к заглавию (после « : »)
    parallel_title: str = ""     # заглавие на другом языке
    organization: str = ""       # учреждение в сведениях об ответственности

    edition: str = ""            # «2-е изд., перераб. и доп.»
    container: str = ""          # журнал, сборник, сайт — то, что после «//»
    container_subtitle: str = "" # «сб. науч. ст.», «офиц. сайт», «электрон. журн.»
    container_editors: list[Person] = field(default_factory=list)

    city: str = ""               # можно несколько через « ; »
    publisher: str = ""
    year: str = ""
    year_end: str = ""           # для длящихся изданий

    volume: str = ""             # Т.
    issue: str = ""              # №
    part: str = ""               # Ч.
    pages: str = ""              # страницы составной части: «45–52»
    total_pages: str = ""        # объём издания: «250»
    series: str = ""

    url: str = ""
    access_date: str = ""        # дата обращения
    publication_date: str = ""   # дата публикации в сети
    update_note: str = ""        # «Обновляется в течение суток»
    doi: str = ""
    isbn: str = ""
    issn: str = ""

    medium: str = ""             # print | electronic; пусто = вывести автоматически
    material_designation: str = ""  # «видеофайл», «изображение», «электрон. текстовые дан.»
    duration: str = ""           # «00:25:56 (время воспроизведения)»

    # диссертации
    specialty: str = ""          # «24.00.01»
    specialty_name: str = ""     # «Теория и история культуры»
    degree: str = ""             # «кандидата культурологии»
    institution: str = ""

    # нормативные документы
    doc_number: str = ""         # «№ 131-ФЗ», «7.0.5-2008»
    adopted: str = ""            # «принят Государственной Думой 8 июля 2006 года»
    status: str = ""             # «введен в действие 01.07.2009»
    jurisdiction: str = ""       # «Российская Федерация. Законы»

    # архив
    archive: str = ""            # «ГАРФ», «НА РК»
    archive_ref: str = ""        # «Ф. 480. Оп. 2. № 104/65. Л. 34»

    note: str = ""

    # ---- служебное -------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Reference":
        data = dict(data or {})
        ref = cls()
        ref.type = str(data.pop("type", "book") or "book").strip().lower()

        for key, role in (
            ("authors", ""), ("editors", "редактор"),
            ("translators", "переводчик"), ("compilers", "составитель"),
            ("container_editors", "редактор"),
        ):
            if key in data:
                setattr(ref, key, as_people(data.pop(key), role=role))
        # синонимы
        for alias, target in (("author", "authors"), ("editor", "editors"),
                              ("translator", "translators")):
            if alias in data:
                getattr(ref, target).extend(as_people(data.pop(alias)))

        for key, value in data.items():
            if hasattr(ref, key) and value is not None:
                setattr(ref, key, str(value).strip() if not isinstance(value, list) else value)

        ref.normalize()
        return ref

    def normalize(self) -> "Reference":
        from .text import clean_dash, normalize_date, normalize_pages, tidy

        self.title = tidy(self.title)
        self.subtitle = tidy(self.subtitle)
        self.container = tidy(self.container)
        self.publisher = tidy(self.publisher)
        self.pages = normalize_pages(self.pages)
        self.total_pages = re.sub(r"\s*с\.?\s*$", "", tidy(self.total_pages)).strip()
        self.access_date = normalize_date(self.access_date)
        self.publication_date = normalize_date(self.publication_date)
        self.year = tidy(self.year)
        self.doi = re.sub(r"^(?:doi:?\s*|https?://(?:dx\.)?doi\.org/)", "", tidy(self.doi), flags=re.I)
        self.series = clean_dash(tidy(self.series))
        if not self.medium:
            self.medium = MEDIUM_ELECTRONIC if (self.url or self.type in ALWAYS_ELECTRONIC) else MEDIUM_PRINT
        return self

    # ---- предикаты -------------------------------------------------------

    @property
    def is_component(self) -> bool:
        return self.type in COMPONENT_TYPES

    @property
    def is_electronic(self) -> bool:
        return self.medium == MEDIUM_ELECTRONIC

    @property
    def primary_authors(self) -> list[Person]:
        return [p for p in self.authors if p.surname or p.initials]

    @property
    def use_author_heading(self) -> bool:
        """Заголовок записи применяют при одном–трёх авторах (ГОСТ 7.80)."""
        return 1 <= len(self.primary_authors) <= 3

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key in ("authors", "editors", "translators", "compilers", "container_editors"):
            out[key] = [
                {k: v for k, v in p.items() if v}
                for p in out[key]
            ]
        return {k: v for k, v in out.items() if v}
