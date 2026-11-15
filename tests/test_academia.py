from __future__ import annotations

import pytest

from gost_ref import academia


class FakeResponse:
    text = """
    <a class="result__a" href="https://www.academia.edu/49699327/Digital_heritage">
      (PDF) Digital heritage | Academia.edu
    </a>
    <a class="result__a" href="https://example.org/not-academia">Wrong host</a>
    <a class="result__a" href="https://uw.academia.edu/SomeAuthor">Profile</a>
    <a class="result__a" href="https://www.academia.edu/49699327/Digital_heritage">Duplicate</a>
    """

    @staticmethod
    def raise_for_status():
        return None


def test_search_returns_only_unique_document_pages(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(academia.httpx, "post", fake_post)
    result = academia.search("digital heritage", limit=5)

    assert captured["data"]["q"] == "site:academia.edu/ digital heritage"
    assert result["results"] == [{
        "title": "Digital heritage",
        "url": "https://www.academia.edu/49699327/Digital_heritage",
    }]
    assert result["status"] == "candidates"
    assert "не скачивались" in result["notice"]


@pytest.mark.parametrize("query,limit", [("", 5), ("x", 0), ("x", 11)])
def test_search_rejects_invalid_arguments(query, limit):
    with pytest.raises(academia.AcademiaSearchError):
        academia.search(query, limit)
