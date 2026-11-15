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


def test_search_extracts_embedded_percent_encoded_document_url(monkeypatch):
    body = (
        '<script>var target="https%3A%2F%2Fwww.academia.edu%2F49699327%2F'
        'Digital_heritage_in_digital_museums";</script>'
    )
    monkeypatch.setattr(academia, "_post_html", lambda _query: body)

    result = academia.search("digital heritage", limit=1)

    assert result["results"] == [{
        "title": "Digital heritage in digital museums",
        "url": "https://www.academia.edu/49699327/Digital_heritage_in_digital_museums",
    }]


def test_search_extracts_generic_anchor_without_css_class(monkeypatch):
    body = (
        '<a href="https://www.academia.edu/34749961/Glitch_in_the_museum">'
        '<strong>Glitch</strong> in the museum</a>'
    )
    monkeypatch.setattr(academia, "_post_html", lambda _query: body)

    result = academia.search("museum", limit=1)

    assert result["results"] == [{
        "title": "Glitch in the museum",
        "url": "https://www.academia.edu/34749961/Glitch_in_the_museum",
    }]


def test_search_falls_back_to_yahoo_html(monkeypatch):
    target = "https://www.academia.edu/49699327/Digital_heritage_in_digital_museums"
    monkeypatch.setattr(academia, "_post_html", lambda _query: "")
    monkeypatch.setattr(academia, "_get_bing_html", lambda _query: "")
    monkeypatch.setattr(
        academia, "_get_yahoo_html",
        lambda _query: f'<a href="{target}">Digital heritage in digital museums</a>',
    )

    result = academia.search("digital heritage", limit=1)

    assert result["results"] == [{
        "title": "Digital heritage in digital museums", "url": target,
    }]


def test_search_falls_back_to_reader_markdown(monkeypatch):
    target = "https://www.academia.edu/49699327/Digital_heritage_in_digital_museums"
    redirect = "https://duckduckgo.com/l/?uddg=" + target.replace(":", "%3A").replace("/", "%2F")
    markdown = f"## [(PDF) Digital heritage in digital museums | Academia]({redirect})"
    monkeypatch.setattr(academia, "_post_html", lambda _query: "")
    monkeypatch.setattr(academia, "_get_bing_html", lambda _query: "")
    monkeypatch.setattr(academia, "_get_yahoo_html", lambda _query: "")
    monkeypatch.setattr(academia, "_get_academia_reader_markdown", lambda _query: "")
    monkeypatch.setattr(academia, "_get_reader_markdown", lambda _query: markdown)

    result = academia.search("digital heritage", limit=1)

    assert result["results"] == [{
        "title": "Digital heritage in digital museums", "url": target,
    }]


def test_search_uses_academia_reader_without_download_links(monkeypatch):
    target = "https://www.academia.edu/34749961/Glitch_in_the_museum"
    markdown = f"""
    [Glitch in the museum]({target}?sm=b)
    [](https://www.academia.edu/attachments/54608380/download_file?ct=secret)
    """
    monkeypatch.setattr(academia, "_post_html", lambda _query: "")
    monkeypatch.setattr(academia, "_get_bing_html", lambda _query: "")
    monkeypatch.setattr(academia, "_get_yahoo_html", lambda _query: "")
    monkeypatch.setattr(
        academia, "_get_academia_reader_markdown", lambda _query: markdown,
    )

    result = academia.search("museum", limit=5)

    assert result["results"] == [{"title": "Glitch in the museum", "url": target}]


@pytest.mark.parametrize("query,limit", [("", 5), ("x", 0), ("x", 11)])
def test_search_rejects_invalid_arguments(query, limit):
    with pytest.raises(academia.AcademiaSearchError):
        academia.search(query, limit)
