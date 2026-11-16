"""Unified discovery with provenance; existing lookup functions remain untouched."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def _norm(value: Any) -> str:
    s = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    return " ".join(re.findall(r"[^\\W_]+", s, flags=re.UNICODE))


def _edition_key(fields: dict) -> tuple:
    """Conservative identity: never collapse known conflicting editions."""
    return (_norm(fields.get("title")), _norm(fields.get("year")),
            _norm(fields.get("publisher")), _norm(fields.get("isbn")))


def _compatible(a: dict, b: dict) -> bool:
    if not _norm(a.get("title")) or _norm(a.get("title")) != _norm(b.get("title")):
        return False
    # Missing publication details are NOT evidence of an identical edition.
    for field in ("year", "publisher", "isbn"):
        x, y = _norm(a.get(field)), _norm(b.get(field))
        if not x or not y or x != y:
            return False
    return True


def reconcile(records: list[dict]) -> list[dict]:
    """Group exact edition matches, retaining each provider and its original fields."""
    groups: list[dict] = []
    for record in records:
        fields = record.get("fields") or {}
        if not isinstance(fields, dict):
            continue
        source = str(record.get("source") or record.get("provider") or "unknown")
        provenance = {key: [{"source": source, "value": value,
                             "verified": bool(record.get("verified", False))}]
                      for key, value in fields.items() if value not in (None, "")}
        for group in groups:
            if _compatible(group["fields"], fields):
                group["sources"].append(source)
                for key, entries in provenance.items():
                    group["provenance"].setdefault(key, []).extend(entries)
                break
        else:
            groups.append({"fields": dict(fields), "sources": [source],
                           "provenance": provenance, "verified": bool(record.get("verified", False))})
    return groups


def discover(query: str, *, providers: tuple[str, ...] = ("openalex", "crossref"),
             include_rsl: bool = True) -> dict:
    """Search supported live metadata indices; expose RSL as a browser task.

    Errors are isolated per provider. No catalog result is automatically verified.
    """
    query = " ".join(str(query or "").split())
    if not query:
        raise ValueError("empty query")
    from . import lookup
    handlers = {"openalex": lookup.by_openalex, "crossref": lookup.by_crossref_title}
    results: list[dict] = []
    errors: dict[str, str] = {}
    for name in providers:
        if name not in handlers:
            errors[name] = "unsupported provider"
            continue
        try:
            payload = handlers[name](query)
            candidates = payload.get("candidates") or [{"fields": payload.get("fields", {})}]
            for candidate in candidates:
                if candidate.get("fields"):
                    results.append({"fields": candidate["fields"], "source": payload.get("source", name),
                                    "provider": name, "verified": False})
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
    manual_checks = []
    if include_rsl:
        from .rsl import search_instructions
        manual_checks.append(search_instructions(title=query))
    return {"query": query, "groups": reconcile(results), "raw_count": len(results),
            "provider_errors": errors, "manual_checks": manual_checks,
            "verification_required": True}
