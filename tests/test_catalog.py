"""Catalog integration tests; the network and real credentials are not used."""

from __future__ import annotations

import json
import subprocess

import pytest

from gost_ref import catalog


def _completed(payload: dict, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=json.dumps(payload), stderr=stderr,
    )


def test_catalog_search_returns_normalized_candidates(monkeypatch):
    captured = {}
    payload = {
        "page": 1,
        "total": 22,
        "more_pages": False,
        "matched": 22,
        "results": [{
            "id": "isbndb:9780892362509",
            "title": " Historical and Philosophical Issues ",
            "authors": "Nicholas Stanley Price",
            "publisher": "Getty Conservation Institute",
            "edition": "1st, 1996",
            "language": "English",
            "year": "1996",
            "description": "A catalog description",
            "url": "https://example.invalid/record",
        }],
    }

    monkeypatch.setattr(catalog, "_binary", lambda: "/opt/annas-mcp")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _completed(payload)

    monkeypatch.setattr(catalog.subprocess, "run", fake_run)
    result = catalog.search(
        "9780892362509", author="Price", language="en", limit=3,
    )

    assert result["provider"] == "Anna's Archive metadata catalogs"
    assert result["client_version"] == "0.8.2"
    assert result["total"] == 22
    candidate = result["results"][0]
    assert candidate["id"] == "isbndb:9780892362509"
    assert candidate["catalog"] == "isbndb"
    assert candidate["fields"]["type"] == "book"
    assert candidate["fields"]["title"] == "Historical and Philosophical Issues"
    assert candidate["record_url"] == "https://example.invalid/record"
    assert "book-download" not in captured["command"]
    assert captured["command"][:6] == [
        "/opt/annas-mcp", "--json", "--json-errors", "--timeout", "60s",
        "metadata-search",
    ]
    assert captured["command"][-4:] == ["--author", "Price", "--language", "en"]
    assert "shell" not in captured["kwargs"]


def test_catalog_record_maps_identifiers_and_omits_download_data(monkeypatch):
    payload = {
        "id": "isbndb:9780892362509",
        "url": "https://example.invalid/record",
        "title": "Historical and Philosophical Issues",
        "publisher": "Getty Conservation Institute",
        "edition": "1st, 1996",
        "year": "1996",
        "languages": ["en"],
        "description": "Description",
        "identifiers": {
            "isbn10": ["0892362502"],
            "isbn13": ["9780892362509"],
            "oclc": ["12345"],
        },
        "sources": ["isbndb"],
        "fast_download": True,
        "hash": "must-not-leak",
    }
    monkeypatch.setattr(catalog, "_binary", lambda: "/opt/annas-mcp")
    monkeypatch.setattr(catalog.subprocess, "run", lambda *a, **k: _completed(payload))

    result = catalog.record("isbndb:9780892362509")
    assert result["fields"]["isbn"] == "9780892362509"
    assert result["fields"]["language"] == "en"
    assert result["identifiers"]["oclc"] == ["12345"]
    assert "hash" not in result
    assert "fast_download" not in result


@pytest.mark.parametrize("page,limit", [(0, 5), (1, 0), (1, 21)])
def test_catalog_search_rejects_invalid_paging(page, limit):
    with pytest.raises(catalog.CatalogError):
        catalog.search("book", page=page, limit=limit)


def test_catalog_client_error_is_bounded(monkeypatch):
    monkeypatch.setattr(catalog, "_binary", lambda: "/opt/annas-mcp")
    monkeypatch.setattr(
        catalog.subprocess,
        "run",
        lambda *a, **k: _completed({}, returncode=1, stderr="provider unavailable"),
    )
    with pytest.raises(catalog.CatalogError, match="provider unavailable"):
        catalog.search("book")
