"""Деление корпуса и замер точности.

Делим ПО ДИССЕРТАЦИЯМ, а не по записям: внутри одного списка записи похожи
между собой (один оформитель, одна привычка), и если куски одной диссертации
попадут и в рабочую, и в отложенную часть, отложенная перестанет быть
независимой проверкой.

Рабочую часть смотрим и по ней чиним. Отложенную открываем один раз, в конце.
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
    s = re.sub(r"^\s*\d{1,3}\s*\.\s*", "", s)
    s = s.replace("–", "—").replace("‒", "—")
    return re.sub(r"\s+", " ", s).strip().strip(".")


def split(corpus: list[dict]) -> tuple[list[dict], list[dict]]:
    """Через одну диссертацию, с чередованием по вузам — чтобы обе части
    были одинаковы по составу источников."""
    by_source: dict[str, list[str]] = collections.defaultdict(list)
    for row in corpus:
        if row["doc"] not in by_source[row["source"]]:
            by_source[row["source"]].append(row["doc"])

    dev_docs: set[str] = set()
    for docs in by_source.values():
        for i, doc in enumerate(sorted(docs)):
            if i % 2 == 0:
                dev_docs.add(doc)

    dev = [r for r in corpus if r["doc"] in dev_docs]
    hold = [r for r in corpus if r["doc"] not in dev_docs]
    return dev, hold


STANDARDS = ("7.0.5", "7.0.100", "7.1", "7.0.108")


def measure(rows: list[dict], name: str, show_worst: int = 0) -> dict:
    """Каждую запись сравниваем с ТЕМ стандартом, по которому она оформлена.

    Списки 2022–2026 годов идут и по 7.0.100, и по 7.1, и по 7.0.5 —
    вуз выбирает сам. Сравнивать всё с 7.0.100 значит записывать в ошибки
    правильно оформленные по другому стандарту записи. Поэтому собираем
    во всех четырёх и берём лучшее совпадение, попутно фиксируя, какой
    стандарт выиграл: это и есть ответ, по чему список написан.
    """
    results = []
    for row in rows:
        raw = row["text"]
        best, best_ratio, best_std = None, -1.0, ""
        for std in STANDARDS:
            r = g.reformat(raw, std)
            ratio = difflib.SequenceMatcher(
                None, norm(raw), norm(r["reference"])).ratio()
            if ratio > best_ratio:
                best, best_ratio, best_std = r, ratio, std
        r = best
        ratio = best_ratio
        results.append({**row, "out": r["reference"], "ratio": round(ratio, 3),
                        "matched_standard": best_std,
                        "type": r["type"], "label": r["type_label"],
                        "errors": [e["code"] for e in r["errors"]],
                        "warnings": [w["code"] for w in r["warnings"]],
                        "fields": r["fields"]})

    n = len(results)
    exact = sum(1 for r in results if norm(r["text"]) == norm(r["out"]))
    high = sum(1 for r in results if r["ratio"] >= 0.95)
    low = sum(1 for r in results if r["ratio"] < 0.80)
    avg = sum(r["ratio"] for r in results) / n if n else 0

    print(f"\n══ {name}: {n} записей, "
          f"{len({r['doc'] for r in results})} диссертаций ══")
    print(f"  точное совпадение : {exact:>4}  ({exact/n:.0%})")
    print(f"  сходство ≥ 0,95   : {high:>4}  ({high/n:.0%})")
    print(f"  сходство < 0,80   : {low:>4}  ({low/n:.0%})")
    print(f"  среднее сходство  : {avg:.3f}")
    print("  стандарт, давший лучшее совпадение:")
    for std, c in collections.Counter(r["matched_standard"] for r in results).most_common():
        print(f"    {c:>4}  ГОСТ {std}")

    if show_worst:
        print("\n  худшие:")
        for r in sorted(results, key=lambda x: x["ratio"])[:show_worst]:
            print(f"\n   [{r['ratio']}] {r['label']}")
            print("    было :", norm(r["text"])[:160])
            print("    стало:", norm(r["out"])[:160])
        print("\n  замечания валидатора:")
        codes = collections.Counter(c for r in results
                                    for c in r["errors"] + r["warnings"])
        for code, c in codes.most_common(10):
            print(f"    {c:>4}  {code}")

    return {"name": name, "n": n, "exact": exact, "high": high,
            "low": low, "avg": round(avg, 4), "rows": results}


def main() -> None:
    corpus = json.loads((HERE / "corpus_1000.json").read_text(encoding="utf-8"))
    dev, hold = split(corpus)

    part = sys.argv[1] if len(sys.argv) > 1 else "dev"
    if part == "dev":
        res = measure(dev, "РАБОЧАЯ ЧАСТЬ", show_worst=6)
        (HERE / "dev_result.json").write_text(
            json.dumps(res["rows"], ensure_ascii=False, indent=1), encoding="utf-8")
    elif part == "hold":
        res = measure(hold, "ОТЛОЖЕННАЯ ЧАСТЬ", show_worst=0)
        (HERE / "hold_result.json").write_text(
            json.dumps(res["rows"], ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        measure(dev, "РАБОЧАЯ ЧАСТЬ")
        measure(hold, "ОТЛОЖЕННАЯ ЧАСТЬ")


if __name__ == "__main__":
    main()
