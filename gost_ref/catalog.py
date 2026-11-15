"""Book-catalog metadata through the pinned ``annas-mcp`` client.

Only catalog search and record details are exposed here.  Download commands,
file hashes and fast-download links deliberately stay outside gost-ref: this
module exists to fill bibliographic fields, not to retrieve publications.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

ANNA_MCP_VERSION = "0.8.2"
DEFAULT_TIMEOUT = 60
MAX_RESULTS = 20


class CatalogError(RuntimeError):
    """Catalog client is missing, misconfigured, or returned invalid data."""


def _timeout() -> int:
    try:
        value = int(os.environ.get("GOST_REF_CATALOG_TIMEOUT", DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT
    return max(1, min(value, 120))


def _binary() -> str:
    configured = os.environ.get("ANNAS_MCP_PATH", "").strip()
    if configured:
        if os.path.isfile(configured) and os.access(configured, os.X_OK):
            return configured
        raise CatalogError(f"annas-mcp is not executable: {configured}")
    found = shutil.which("annas-mcp")
    if not found:
        raise CatalogError(
            "annas-mcp is not installed; set ANNAS_MCP_PATH or install the pinned client"
        )
    return found


def _run(args: list[str]) -> dict[str, Any]:
    timeout = _timeout()
    command = [
        _binary(), "--json", "--json-errors", "--timeout", f"{timeout}s", *args,
    ]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout + 5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CatalogError(f"catalog request exceeded {timeout} seconds") from exc
    except OSError as exc:
        raise CatalogError(f"cannot start annas-mcp: {exc}") from exc

    if proc.returncode:
        message = (proc.stderr or proc.stdout or "catalog request failed").strip()
        try:
            payload = json.loads(message.splitlines()[-1])
            message = str(payload.get("error") or payload.get("message") or message)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise CatalogError(message[:800])

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CatalogError("annas-mcp returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise CatalogError("annas-mcp returned a non-object JSON response")
    return data


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _catalog_from_id(record_id: str) -> str:
    return record_id.split(":", 1)[0] if ":" in record_id else ""


def _candidate(item: dict[str, Any]) -> dict[str, Any]:
    record_id = _text(item.get("id"))
    fields: dict[str, Any] = {"type": "book"}
    for key in ("title", "authors", "publisher", "edition", "language", "year"):
        value = _text(item.get(key))
        if value:
            fields[key] = value
    return {
        "id": record_id,
        "catalog": _catalog_from_id(record_id),
        "fields": fields,
        "description": _text(item.get("description")),
        "record_url": _text(item.get("url")),
    }


def search(
    query: str,
    *,
    title: str = "",
    author: str = "",
    publisher: str = "",
    year: str = "",
    language: str = "",
    source: str = "",
    page: int = 1,
    limit: int = 5,
) -> dict[str, Any]:
    """Search library catalogs and return compact bibliographic candidates."""
    query = _text(query)
    if not query:
        raise CatalogError("empty catalog query")
    if page < 1:
        raise CatalogError("page must be at least 1")
    if limit < 1 or limit > MAX_RESULTS:
        raise CatalogError(f"limit must be between 1 and {MAX_RESULTS}")

    args = ["metadata-search", query, "--page", str(page), "--limit", str(limit)]
    for flag, value in (
        ("--title", title), ("--author", author), ("--publisher", publisher),
        ("--year", year), ("--language", language), ("--source", source),
    ):
        value = _text(value)
        if value:
            args.extend([flag, value])

    payload = _run(args)
    results = [_candidate(item) for item in payload.get("results") or []]
    partial = [_candidate(item) for item in payload.get("partial_matches") or []]
    answer: dict[str, Any] = {
        "provider": "Anna's Archive metadata catalogs",
        "client_version": ANNA_MCP_VERSION,
        "query": query,
        "page": int(payload.get("page") or page),
        "total": int(payload.get("total") or 0),
        "total_is_lower_bound": bool(payload.get("total_is_lower_bound")),
        "more_pages": bool(payload.get("more_pages")),
        "matched": int(payload.get("matched") or len(results)),
        "results": results,
        "verification_required": (
            "record_url and identifiers are discovery hints; open the selected record "
            "and verify author and title before citing it"
        ),
    }
    if partial:
        answer["partial_matches"] = partial
    return answer


def _first(values: Any) -> str:
    if isinstance(values, list) and values:
        return _text(values[0])
    return _text(values)


def record(record_id: str) -> dict[str, Any]:
    """Return normalized fields and identifiers for one catalog record."""
    record_id = _text(record_id)
    if not record_id or ":" not in record_id:
        raise CatalogError("record_id must look like isbndb:978... or ol:OL...")
    payload = _run(["book-details", record_id])

    fields: dict[str, Any] = {"type": "book"}
    for key in ("title", "authors", "publisher", "edition", "year"):
        value = _text(payload.get(key))
        if value:
            fields[key] = value
    languages = payload.get("languages") or []
    if languages:
        fields["language"] = ", ".join(_text(v) for v in languages if _text(v))

    identifiers = payload.get("identifiers") or {}
    if not isinstance(identifiers, dict):
        identifiers = {}
    isbn = _first(identifiers.get("isbn13")) or _first(identifiers.get("isbn10"))
    if isbn:
        fields["isbn"] = isbn
    for key in ("doi", "issn"):
        value = _first(identifiers.get(key))
        if value:
            fields[key] = value

    return {
        "provider": "Anna's Archive metadata catalogs",
        "client_version": ANNA_MCP_VERSION,
        "id": _text(payload.get("id")) or record_id,
        "catalog": _catalog_from_id(record_id),
        "fields": fields,
        "identifiers": identifiers,
        "classifications": payload.get("classifications") or {},
        "subjects": payload.get("subjects") or [],
        "alternative_titles": payload.get("alternative_titles") or [],
        "alternative_authors": payload.get("alternative_authors") or [],
        "sources": payload.get("sources") or [],
        "problems": payload.get("problems") or [],
        "description": _text(payload.get("description")),
        "record_url": _text(payload.get("url")),
        "verification_required": (
            "open record_url and verify author and title before using its URL or identifiers"
        ),
    }
