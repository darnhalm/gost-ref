"""Сбор корпуса настоящих библиографических записей из КиберЛенинки.

Берём списки литературы статей по музеологии, цифровому наследию и
музыкальным инструментам — как есть, вместе с повреждениями распознавания.
Ничего не чистим: смысл корпуса именно в том, что он грязный.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from gost_ref.lookup import _post_json  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
UA = "Mozilla/5.0 (compatible; gost-ref-eval/1.0)"

QUERIES = [
    "виртуальный музей культурное наследие",
    "музыкальные инструменты традиционная культура",
    "3D моделирование объектов культурного наследия",
    "музеефикация памятников архитектуры",
    "цифровое документирование музейных предметов",
    "звукозапись и музыкальная культура",
    "органология народные инструменты",
    "реставрация музейных предметов методика",
    "нематериальное культурное наследие ЮНЕСКО",
    "музейная коммуникация экспозиция",
    "историко-культурная экспертиза объектов наследия",
    "фотограмметрия в музейном деле",
]

CYR = re.compile(r"[А-Яа-яЁё]")
YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
PARA = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")


def unescape(s: str) -> str:
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'"), ("&laquo;", "«"), ("&raquo;", "»"),
                 ("&mdash;", "—"), ("&ndash;", "–"), ("&shy;", "")):
        s = s.replace(a, b)
    return s


def looks_like_reference(t: str) -> bool:
    if not (45 < len(t) < 340) or not CYR.search(t) or not YEAR.search(t):
        return False
    if len(re.findall(r"URL:", t, re.I)) > 1:      # сводное подстрочное примечание
        return False
    if re.match(r"^\d+\s*(См\.|Например|Данные сайта)", t, re.I):
        return False
    has_marker = ("//" in t or re.search(r"\bС\.\s*\d", t)
                  or re.search(r"URL:", t, re.I) or re.search(r"\d+\s*с\.", t))
    return bool(has_marker)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def article_links(query: str, size: int = 12) -> list[str]:
    data = _post_json("https://cyberleninka.ru/api/search",
                      {"mode": "articles", "q": query, "size": size, "from": 0})
    return [a["link"] for a in (data.get("articles") or []) if a.get("link")]


def main(target: int = 200) -> None:
    seen: set[str] = set()
    corpus: list[str] = []
    sources: list[dict] = []

    for query in QUERIES:
        if len(corpus) >= target:
            break
        try:
            links = article_links(query)
        except Exception as exc:  # noqa: BLE001
            print(f"  поиск «{query[:40]}» — {type(exc).__name__}", file=sys.stderr)
            continue

        for link in links:
            if len(corpus) >= target:
                break
            try:
                html = fetch("https://cyberleninka.ru" + link)
            except Exception as exc:  # noqa: BLE001
                print(f"  {link[:40]} — {type(exc).__name__}", file=sys.stderr)
                continue

            added = 0
            for chunk in PARA.findall(html):
                t = re.sub(r"\s+", " ", unescape(TAG.sub("", chunk))).strip()
                if looks_like_reference(t) and t not in seen:
                    seen.add(t)
                    corpus.append(t)
                    added += 1
                    if len(corpus) >= target:
                        break
            if added:
                sources.append({"link": link, "refs": added})
            time.sleep(0.4)

    (HERE / "corpus_200.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "corpus_200_sources.json").write_text(
        json.dumps(sources, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"собрано записей: {len(corpus)} из {len(sources)} статей")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
