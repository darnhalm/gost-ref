from __future__ import annotations

import base64

import pytest

from gost_ref import academia


SEARCH_HTML = """
    <a class="result__a" href="https://www.academia.edu/49699327/Digital_heritage">
      (PDF) Digital heritage | Academia.edu
    </a>
    <a class="result__a" href="https://example.org/not-academia">Wrong host</a>
    <a class="result__a" href="https://uw.academia.edu/SomeAuthor">Profile</a>
    <a class="result__a" href="https://www.academia.edu/49699327/Digital_heritage">Duplicate</a>
    """


def test_search_returns_only_unique_document_pages(monkeypatch):
    captured = {}

    def fake_post(query):
        captured["query"] = query
        return SEARCH_HTML

    monkeypatch.setattr(academia, "_post_html", fake_post)
    result = academia.search("digital heritage", limit=5)

    assert captured["query"] == "digital heritage"
    assert result["results"] == [{
        "title": "Digital heritage",
        "url": "https://www.academia.edu/49699327/Digital_heritage",
    }]
    assert result["status"] == "candidates"
    assert "не скачивались" in result["notice"]


def test_search_falls_back_to_bing_and_decodes_redirect(monkeypatch):
    target = "https://www.academia.edu/73525568/Digital_heritage"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    bing_html = (
        '<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1'
        + encoded + '">(PDF) Digital heritage | Academia</a></h2></li>'
    )
    monkeypatch.setattr(academia, "_post_html", lambda _query: "<html></html>")
    monkeypatch.setattr(academia, "_get_bing_html", lambda _query: bing_html)

    result = academia.search("digital heritage", limit=1)

    assert result["results"] == [{"title": "Digital heritage", "url": target}]


def test_search_falls_back_to_reader_markdown(monkeypatch):
    target = "https://www.academia.edu/49699327/Digital_heritage_in_digital_museums"
    redirect = "https://duckduckgo.com/l/?uddg=" + target.replace(":", "%3A").replace("/", "%2F")
    markdown = f"## [(PDF) Digital heritage in digital museums | Academia]({redirect})"
    monkeypatch.setattr(academia, "_post_html", lambda _query: "")
    monkeypatch.setattr(academia, "_get_bing_html", lambda _query: "")
    monkeypatch.setattr(academia, "_get_reader_markdown", lambda _query: markdown)

    result = academia.search("digital heritage", limit=1)

    assert result["results"] == [{
        "title": "Digital heritage in digital museums", "url": target,
    }]


@pytest.mark.parametrize("query,limit", [("", 5), ("x", 0), ("x", 11)])
def test_search_rejects_invalid_arguments(query, limit):
    with pytest.raises(academia.AcademiaSearchError):
        academia.search(query, limit)
