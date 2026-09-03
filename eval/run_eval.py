"""Прогон настоящего списка литературы через ядро.

Источник: списки литературы восьми статей КиберЛенинки по музеологии,
цифровому наследию и музыкальным инструментам. Тексты взяты как есть,
вместе с OCR-повреждениями — это и есть то, что реально приходит из PDF.
"""

import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import gost_ref as g

HERE = pathlib.Path(__file__).resolve().parent
entries = json.loads((HERE / "cyberleninka_refs.json").read_text(encoding="utf-8"))

rows = []
for raw in entries:
    r = g.reformat(raw, "7.0.100")
    d = r.get("type_detection", {})
    rows.append({
        "input": raw,
        "out": r["reference"],
        "type": r["type"],
        "label": r["type_label"],
        "conf": d.get("confidence", ""),
        "reason": d.get("reason", ""),
        "errors": [e["code"] for e in r["errors"]],
        "warnings": [w["code"] for w in r["warnings"]],
        "leftovers": r["leftovers"],
        "fields": r["fields"],
    })

(HERE / "result.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

n = len(rows)
print(f"ЗАПИСЕЙ: {n}\n")

print("ТИПЫ")
for t, c in collections.Counter(r["label"] for r in rows).most_common():
    print(f"  {c:>3}  {t}")

print("\nУВЕРЕННОСТЬ ОПРЕДЕЛЕНИЯ ТИПА")
for t, c in collections.Counter(r["conf"] for r in rows).most_common():
    print(f"  {c:>3}  {t}")

print("\nПОЛНОТА РАЗБОРА")
print(f"  заглавие не опознано : {sum(1 for r in rows if not r['fields'].get('title'))}")
print(f"  авторы не опознаны   : {sum(1 for r in rows if not r['fields'].get('authors'))}")
print(f"  год не опознан       : {sum(1 for r in rows if not r['fields'].get('year'))}")
print(f"  остался мусор        : {sum(1 for r in rows if r['leftovers'])}")

print("\nОШИБКИ ВАЛИДАТОРА")
for code, c in collections.Counter(e for r in rows for e in r["errors"]).most_common():
    print(f"  {c:>3}  {code}")

print("\nПРЕДУПРЕЖДЕНИЯ")
for code, c in collections.Counter(w for r in rows for w in r["warnings"]).most_common():
    print(f"  {c:>3}  {code}")

clean = [r for r in rows if not r["errors"] and not r["warnings"]]
print(f"\nБЕЗ ЕДИНОГО ЗАМЕЧАНИЯ: {len(clean)} из {n}")
