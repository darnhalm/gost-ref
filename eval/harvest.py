"""Сбор большого корпуса выверенных записей из диссертаций 2022 года и позже.

Источник — полные тексты, выложенные диссертационными советами. Списки
литературы могут следовать разным стандартам. Нормоконтроль и год защиты
не доказывают соответствие ГОСТ Р 7.0.100-2018; см. ограничения в eval/README.md.

Каждая запись несёт паспорт: вуз, год защиты, файл. Это нужно, чтобы делить
корпус по источникам, а не вслепую: записи из одной диссертации похожи между
собой, и если они окажутся и в рабочей, и в отложенной части, отложенная
перестанет быть честной проверкой.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from eval.from_dissertation import HEAD_RE, STOP_RE, ENTRY_RE, dehyphenate  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / "pdf_cache"
LAST_REJECTED = 0
UA = "Mozilla/5.0 (compatible; gost-ref-eval/1.0)"


def safe_url(url: str) -> str:
    """Ссылки ВШЭ содержат кириллицу и пробелы («…/Диссертация Иванов.pdf»);
    urllib такое не отправит, путь надо кодировать процентами."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((
        parts.scheme, parts.netloc,
        urllib.parse.quote(parts.path, safe="/%"),
        urllib.parse.quote(parts.query, safe="=&%"), parts.fragment))


def get(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(safe_url(url), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# --------------------------------------------------------------------------
# ВШЭ: перечень защит со ссылками на полные тексты
# --------------------------------------------------------------------------

HSE_LIST = "https://www.hse.ru/sci/diss/"
PDF_RE = re.compile(r'href="(https?://[^"]*?\.pdf)"', re.I)


def hse_dissertations(years: list[int], pages: int = 4) -> list[dict]:
    """Ссылки на полные тексты диссертаций ВШЭ за указанные годы."""
    found: list[dict] = []
    seen: set[str] = set()
    for year in years:
        for page in range(1, pages + 1):
            url = f"{HSE_LIST}?year={year}&page={page}"
            try:
                html = get(url).decode("utf-8", "replace")
            except Exception as exc:  # noqa: BLE001
                print(f"  ВШЭ {year} стр.{page}: {type(exc).__name__}", file=sys.stderr)
                continue
            for link in PDF_RE.findall(html):
                name = urllib.parse.unquote(link.rsplit("/", 1)[-1]).lower()
                if not re.search(r"диссертац|dissert", name):
                    continue
                if re.search(r"резюме|summary|аннотац|автореферат|abstract", name):
                    continue
                if link in seen:
                    continue
                seen.add(link)
                found.append({"url": link, "source": "НИУ ВШЭ", "year": year})
            time.sleep(0.5)
    return found


# --------------------------------------------------------------------------
# Прочие советы: перечни с прямыми ссылками на полные тексты
# --------------------------------------------------------------------------

# Гуманитарные советы, где ГОСТ обязателен по регламенту. У ВШЭ советы по
# экономике и психологии ведут списки в APA, поэтому один вуз корпус не
# закрывает — нужна ширина по областям знания.
OTHER_COUNCILS = [
    ("Институт Наследия", "http://dissovet.heritage-institute.ru/"),
    ("РГГУ", "https://www.rsuh.ru/science/dissertation-councils/"),
    ("СПбГИК", "https://spbgik.ru/science/dissertation-councils/"),
    ("МГИК", "https://mgik.org/nauka/dissertatsionnye-sovety/"),
]

ANY_PDF_RE = re.compile(r'href="([^"]+\.pdf)"', re.I)
LINK_RE = re.compile(r'href="([^"]+)"', re.I)


def council_pdfs(name: str, root: str, depth: int = 1,
                 max_pdfs: int = 40) -> list[dict]:
    """Обходит страницу совета и, на глубину depth, вложенные страницы,
    собирая ссылки на PDF полных текстов."""
    found: list[dict] = []
    seen_pages: set[str] = set()
    queue = [(root, 0)]
    while queue and len(found) < max_pdfs:
        page, level = queue.pop(0)
        if page in seen_pages:
            continue
        seen_pages.add(page)
        try:
            html = get(page, timeout=30).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        for href in LINK_RE.findall(html):
            full = urllib.parse.urljoin(page, href)
            if full.lower().endswith(".pdf"):
                fname = urllib.parse.unquote(full.rsplit("/", 1)[-1]).lower()
                if re.search(r"резюме|summary|аннотац|отзыв|заключен|справк|abstract", fname):
                    continue
                if full not in {f["url"] for f in found}:
                    found.append({"url": full, "source": name, "year": 0})
            elif level < depth and urllib.parse.urlparse(full).netloc == \
                    urllib.parse.urlparse(root).netloc:
                if re.search(r"dissov|dissert|diss|zashchit|защит", full, re.I):
                    queue.append((full, level + 1))
        time.sleep(0.3)
    return found


# --------------------------------------------------------------------------
# Извлечение списка литературы
# --------------------------------------------------------------------------

def bibliography(pdf: pathlib.Path, cap: int = 90) -> list[str]:
    """Разбираем только хвост документа: список литературы всегда в конце,
    а полное извлечение текста диссертации на 300 страниц занимает минуты."""
    from pdfminer.high_level import extract_text
    from pdfminer.pdfpage import PDFPage
    try:
        with pdf.open("rb") as fh:
            total = sum(1 for _ in PDFPage.get_pages(fh))
    except Exception:  # noqa: BLE001
        return []
    start = max(0, int(total * 0.55))
    try:
        text = extract_text(str(pdf), page_numbers=list(range(start, total))) or ""
    except Exception:  # noqa: BLE001
        return []
    text = dehyphenate(text)

    heads = list(HEAD_RE.finditer(text))
    if not heads:
        return []
    tail = text[heads[-1].end():]
    stop = STOP_RE.search(tail)
    if stop:
        tail = tail[:stop.start()]

    marks = list(ENTRY_RE.finditer(tail))
    out: list[str] = []
    global LAST_REJECTED
    LAST_REJECTED = 0
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(tail)
        body = re.sub(r"\s+", " ", tail[m.start():end]).strip()
        body = re.sub(r"/\s+/", "//", body)          # pdfminer рвёт «//»
        body = re.sub(r"\s*\d{1,4}\s*$", "", body)
        if 40 < len(body) < 700:
            if is_gost_like(body):
                out.append(body)
            else:
                LAST_REJECTED += 1
        if len(out) >= cap:
            break
    return out


CYR_RE = re.compile(r"[А-Яа-яЁё]")
LAT_RE = re.compile(r"[A-Za-z]")
# «Barney, J. (1991). Firm resources…» — APA, а не ГОСТ
APA_RE = re.compile(r"[A-ZА-ЯЁ][a-zа-яё\-]+,?\s+[A-ZА-ЯЁ]\.\s*(?:[A-ZА-ЯЁ]\.\s*)?\(\d{4}[a-z]?\)")
# «(2020) 15(3), 99-120» и «doi:10.…» без предписанных знаков — тоже не ГОСТ
APA_TAIL_RE = re.compile(r"\b\d{1,3}\(\d{1,3}\),\s*\d+[-–]\d+")

# Признаки библиографической структуры: предписанные знаки ГОСТа либо
# выходные данные вида «СПб.: Питер, 2023» / «250 с.» / «С. 101–110».
STRUCT_RE = re.compile(
    r"//|\s:\s|\s/\s|\s[—–]\s|\bС\.\s*\d|\d+\s*с\.|"
    r"[А-ЯЁA-Z][А-Яа-яЁёA-Za-z\-]*\.?\s*:\s*[А-ЯЁA-Z]")


# Две записи, слипшиеся в одну: нумерация в PDF не выделилась, и объём
# предыдущей записи оказался внутри следующей.
MERGED_RE = re.compile(
    r"\d+\s*с\.\s+[А-ЯЁ][а-яё\-]+\s+[А-ЯЁ]\.|"
    r"\d{4}\.\s*[—–-]?\s*\d+\s*с\.\s+[А-ЯЁ][а-яё\-]{2,}\s+[А-ЯЁ]\.")


def looks_merged(t: str) -> bool:
    return bool(MERGED_RE.search(t))


def is_gost_like(t: str) -> bool:
    """Отсеивает записи, оформленные не по ГОСТу.

    Советы ВШЭ по экономике и психологии ведут списки в APA. Такая запись
    выверена, но по другим правилам: считать на ней сходство с ГОСТом
    бессмысленно — движок будет «ошибаться» там, где ошибки нет.
    """
    if APA_RE.search(t) or APA_TAIL_RE.search(t) or looks_merged(t):
        return False
    cyr, lat = len(CYR_RE.findall(t)), len(LAT_RE.findall(t))
    if cyr + lat == 0 or not STRUCT_RE.search(t):
        return False
    if cyr >= lat:                      # русская запись
        return True
    # латинская запись годится, только если оформлена по ГОСТу, а не по APA:
    # «// Журнал. — 2020. — Vol. 12. — P. 775–799»
    return "//" in t and bool(re.search(r"\b(Vol|No|Iss|P|Pp|С|Т)\.", t))


def detect_standard(entries: list[str]) -> str:
    """По каким правилам оформлен список — видно по характерным приметам."""
    sample = " ".join(entries[:40])
    if re.search(r"Текст\s*:\s*(непосредственный|электронный)", sample):
        return "7.0.100"
    if "[Текст]" in sample or "[Электронный ресурс]" in sample:
        return "7.1"
    if "—" in sample or "–" in sample:
        return "7.1 или 7.0.100 (без области вида содержания)"
    return "7.0.5 или неопределённо"


# --------------------------------------------------------------------------
# Сборка корпуса
# --------------------------------------------------------------------------

def main(target: int = 1000, per_diss: int = 50) -> None:
    CACHE.mkdir(exist_ok=True)
    # Перечень документов ищем один раз и кешируем: обход советов долгий.
    docs_file = HERE / "docs.json"
    if docs_file.exists():
        docs = json.loads(docs_file.read_text(encoding="utf-8"))
        print(f"перечень из кеша: {len(docs)} документов")
    else:
        docs = hse_dissertations([2022, 2023, 2024, 2025, 2026], pages=6)
        print(f"ВШЭ: полных текстов {len(docs)}")
        for name, root in OTHER_COUNCILS:
            try:
                extra = council_pdfs(name, root)
                print(f"{name}: {len(extra)}")
                docs.extend(extra)
            except Exception as exc:  # noqa: BLE001
                print(f"{name}: {type(exc).__name__}", file=sys.stderr)
        docs_file.write_text(json.dumps(docs, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        print(f"всего документов: {len(docs)}")

    # По кругу между вузами: иначе квота выбирается первым же источником
    # в перечне, и корпус выходит из одного совета.
    by_source: dict[str, list[dict]] = {}
    for d in docs:
        by_source.setdefault(d["source"], []).append(d)
    mixed: list[dict] = []
    while any(by_source.values()):
        for src in list(by_source):
            if by_source[src]:
                mixed.append(by_source[src].pop(0))
    docs = mixed

    corpus_file = HERE / "corpus_1000.json"
    pass_file = HERE / "corpus_1000_passports.json"
    corpus: list[dict] = json.loads(corpus_file.read_text(encoding="utf-8")) \
        if corpus_file.exists() else []
    passports: list[dict] = json.loads(pass_file.read_text(encoding="utf-8")) \
        if pass_file.exists() else []
    done = {p["url"] for p in passports}
    seen_text: set[str] = {c["text"] for c in corpus}
    if corpus:
        print(f"продолжаю: уже есть {len(corpus)} записей из {len(passports)} диссертаций")

    for i, doc in enumerate(docs):
        if len(corpus) >= target:
            break
        if doc["url"] in done:
            continue
        name = f"{doc['source'].replace(' ', '_')}_{i:03d}.pdf"
        path = CACHE / name
        if not path.exists():
            try:
                path.write_bytes(get(doc["url"], timeout=90))
            except Exception as exc:  # noqa: BLE001
                print(f"  {name}: {type(exc).__name__}", file=sys.stderr)
                continue
        entries = bibliography(path, cap=per_diss)
        if len(entries) < 15:
            path.unlink(missing_ok=True)
            passports.append({"doc": name, "url": doc["url"], "source": doc["source"],
                              "year": doc["year"], "standard": "—", "entries": 0,
                              "note": "список литературы не выделился"})
            continue

        std = detect_standard(entries)
        added = 0
        for e in entries:
            if e in seen_text:
                continue
            seen_text.add(e)
            corpus.append({"text": e, "doc": name, "source": doc["source"],
                           "year": doc["year"], "standard": std})
            added += 1
            if len(corpus) >= target:
                break
        passports.append({"doc": name, "url": doc["url"], "source": doc["source"],
                          "year": doc["year"], "standard": std, "entries": added,
                          "rejected_not_gost": LAST_REJECTED})
        print(f"  {name}  {doc['year']}  {std:<38} +{added}  (всего {len(corpus)})")
        path.unlink(missing_ok=True)   # PDF в корпусе не храним
        corpus_file.write_text(json.dumps(corpus, ensure_ascii=False, indent=1),
                               encoding="utf-8")
        pass_file.write_text(json.dumps(passports, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    print(f"\nсобрано: {len(corpus)} записей из {len(passports)} диссертаций")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
