"""Извлечение списка литературы из полного текста диссертации.

Список в диссертации проходит нормоконтроль и проверку совета, поэтому
он ближе к правильному оформлению, чем списки в статьях. Это проверка не
только на устойчивость разбора, но и на точность: как далеко наш вывод
уходит от того, что реально приняли к защите.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import warnings

warnings.filterwarnings("ignore")

HERE = pathlib.Path(__file__).resolve().parent

HEAD_RE = re.compile(
    r"(СПИСОК\s+(?:ИСПОЛЬЗОВАННОЙ\s+|ИСПОЛЬЗОВАННЫХ\s+|ЦИТИРОВАННОЙ\s+)?"
    r"(?:ЛИТЕРАТУРЫ|ИСТОЧНИКОВ)|БИБЛИОГРАФИЯ|БИБЛИОГРАФИЧЕСКИЙ\s+СПИСОК)", re.I)
STOP_RE = re.compile(r"(ПРИЛОЖЕНИ[ЕЯ]|ПРИЛОЖЕНИЯ\b)", re.I)
ENTRY_RE = re.compile(r"(?m)^\s*(\d{1,3})\s*\.\s+(?=[«\"\[A-ZА-ЯЁ])")


def page_texts(path: pathlib.Path) -> list[str]:
    from pdfminer.high_level import extract_text
    out = []
    # постранично, чтобы не держать весь текст в памяти дважды
    from pdfminer.pdfpage import PDFPage
    with path.open("rb") as fh:
        total = sum(1 for _ in PDFPage.get_pages(fh))
    for i in range(total):
        try:
            out.append(extract_text(str(path), page_numbers=[i]) or "")
        except Exception:  # noqa: BLE001
            out.append("")
    return out


def dehyphenate(s: str) -> str:
    """«Оло-\nвянишникова» → «Оловянишникова»; перенос строки — не пробел."""
    s = re.sub(r"([а-яёa-z])[-­]\s*\n\s*([а-яёa-z])", r"\1\2", s)
    return s


def extract(path: pathlib.Path, limit: int = 250) -> list[str]:
    pages = page_texts(path)
    joined = "\n".join(pages)
    joined = dehyphenate(joined)

    # берём последнее вхождение заголовка: в оглавлении оно встречается раньше
    heads = list(HEAD_RE.finditer(joined))
    if not heads:
        raise SystemExit("заголовок списка литературы не найден")
    start = heads[-1].end()
    tail = joined[start:]
    stop = STOP_RE.search(tail)
    if stop:
        tail = tail[:stop.start()]

    marks = list(ENTRY_RE.finditer(tail))
    entries: list[str] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(tail)
        body = tail[m.start():end]
        body = re.sub(r"\s+", " ", body).strip()
        body = re.sub(r"\s*\d{1,4}\s*$", "", body)      # номер страницы в колонтитуле
        if 40 < len(body) < 700:
            entries.append(body)
        if len(entries) >= limit:
            break
    return entries


def main() -> None:
    pdf = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "diss1.pdf")
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 250
    entries = extract(pdf, limit)
    out = HERE / "corpus_diss.json"
    out.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"извлечено записей: {len(entries)} → {out.name}")
    for e in entries[:5]:
        print("  ·", e[:130])


if __name__ == "__main__":
    main()
