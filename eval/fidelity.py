"""Проверка на точность: сходится ли наш вывод с выверенным списком.

Источник — список литературы диссертации, оформленный по ГОСТ Р 7.0.100-2018
и прошедший нормоконтроль. Прогоняем каждую запись через разбор и сборку и
сравниваем с оригиналом.

Сравнение нормализует то, что стандарт допускает в обоих видах:
короткое и длинное тире между областями, кратность пробелов, номер позиции
в списке. Всё остальное расхождение — наше.
"""

from __future__ import annotations

import collections
import difflib
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import gost_ref as g  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent


def norm(s: str) -> str:
    s = re.sub(r"^\s*\d{1,3}\s*\.\s*", "", s)     # номер позиции
    s = s.replace("–", "—").replace("‒", "—")     # тире областей: оба варианта ходовые
    s = re.sub(r"\s+", " ", s)
    return s.strip().strip(".")


def classify(src: str, out: str) -> str:
    """Грубая причина расхождения — чтобы понимать, что чинить."""
    s, o = norm(src), norm(out)
    if s == o:
        return "точное совпадение"
    if s.replace(" ", "") == o.replace(" ", ""):
        return "только пробелы"
    if "Текст :" in s and "Текст :" not in o:
        return "потеряна область вида содержания"
    if s.count("—") > o.count("—") + 2:
        return "потеряны области"
    if len(o) < len(s) * 0.75:
        return "вывод короче оригинала (что-то не разобралось)"
    if len(o) > len(s) * 1.25:
        return "вывод длиннее оригинала"
    return "мелкие расхождения"


def main() -> None:
    src_file = HERE / (sys.argv[1] if len(sys.argv) > 1 else "corpus_diss.json")
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    entries = json.loads(src_file.read_text(encoding="utf-8"))[:limit]

    rows = []
    for raw in entries:
        r = g.reformat(raw, "7.0.100")
        ratio = difflib.SequenceMatcher(None, norm(raw), norm(r["reference"])).ratio()
        rows.append({
            "input": raw,
            "out": r["reference"],
            "type": r["type"],
            "label": r["type_label"],
            "conf": (r.get("type_detection") or {}).get("confidence", ""),
            "ratio": round(ratio, 3),
            "verdict": classify(raw, r["reference"]),
            "errors": [e["code"] for e in r["errors"]],
            "warnings": [w["code"] for w in r["warnings"]],
            "fields": r["fields"],
        })

    (HERE / "fidelity_result.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    n = len(rows)
    exact = sum(1 for r in rows if r["verdict"] == "точное совпадение")
    close = sum(1 for r in rows if r["ratio"] >= 0.95)
    mid = sum(1 for r in rows if 0.80 <= r["ratio"] < 0.95)
    low = sum(1 for r in rows if r["ratio"] < 0.80)
    avg = sum(r["ratio"] for r in rows) / n

    print(f"ЗАПИСЕЙ: {n}   источник: {src_file.name}\n")
    print("СХОДСТВО С ВЫВЕРЕННЫМ ОРИГИНАЛОМ")
    print(f"  точное совпадение      : {exact:>3}  ({exact/n:.0%})")
    print(f"  сходство ≥ 0.95        : {close:>3}  ({close/n:.0%})")
    print(f"  сходство 0.80–0.95     : {mid:>3}")
    print(f"  сходство < 0.80        : {low:>3}")
    print(f"  среднее сходство       : {avg:.3f}")

    print("\nПРИЧИНЫ РАСХОЖДЕНИЙ")
    for v, c in collections.Counter(r["verdict"] for r in rows).most_common():
        print(f"  {c:>3}  {v}")

    print("\nТИПЫ")
    for t, c in collections.Counter(r["label"] for r in rows).most_common():
        print(f"  {c:>3}  {t}")

    print("\nЗАМЕЧАНИЯ ВАЛИДАТОРА (на нашем выводе)")
    codes = collections.Counter(c for r in rows for c in r["errors"] + r["warnings"])
    if not codes:
        print("  нет")
    for code, c in codes.most_common():
        print(f"  {c:>3}  {code}")

    print("\nХУДШИЕ ПЯТЬ")
    for r in sorted(rows, key=lambda x: x["ratio"])[:5]:
        print(f"\n  сходство {r['ratio']}  [{r['verdict']}]")
        print("   было :", norm(r["input"])[:150])
        print("   стало:", norm(r["out"])[:150])


if __name__ == "__main__":
    main()
