#!/usr/bin/env python3
"""Optional local Academia.edu search and download adapter.

Search uses a persistent, user-controlled browser profile.  Downloads are
delegated to the separately installed MIT-licensed ``academiadl-py`` tool and
therefore only capture pages already visible to the user.
"""

from __future__ import annotations

import asyncio
import html
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

import httpx


class AcademiaError(RuntimeError):
    """A bounded, user-facing Academia integration error."""


@dataclass(frozen=True)
class AcademiaItem:
    title: str
    url: str
    authors: str = ""
    snippet: str = ""


class _SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self._href = values.get("href") or ""
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.results.append((self._href, " ".join(self._text)))
            self._href = ""
            self._text = []


def _clean_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in {"academia.edu", "www.academia.edu"}:
        return ""
    if not re.fullmatch(r"/\d{4,}(?:/[^?#]+)?/?", parsed.path):
        return ""
    return urlunparse(("https", "www.academia.edu", parsed.path.rstrip("/"), "", "", ""))


class AcademiaLocal:
    """Runs blocking browser work outside the Telegram event loop."""

    def __init__(
        self,
        downloader_dir: str,
        output_dir: str,
        python: str | None = None,
    ):
        self.downloader_dir = Path(downloader_dir).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.python = python or sys.executable

    @property
    def download_available(self) -> bool:
        return (self.downloader_dir / "main.py").is_file()

    async def search(self, query: str, limit: int = 5) -> list[AcademiaItem]:
        return await asyncio.to_thread(self._search_sync, query, limit)

    def _search_sync(self, query: str, limit: int) -> list[AcademiaItem]:
        query = " ".join(str(query or "").split())
        if not query:
            return []
        try:
            response = httpx.post(
                "https://html.duckduckgo.com/html/",
                data={"q": f"site:academia.edu/ {query}"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; gost-ref/1.0)"},
                timeout=25,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AcademiaError("Веб-поиск Academia временно недоступен.") from exc

        parser = _SearchParser()
        parser.feed(response.text)
        items: list[AcademiaItem] = []
        seen: set[str] = set()
        for href, raw_title in parser.results:
            decoded = html.unescape(href)
            if "uddg=" in decoded:
                decoded = (parse_qs(urlparse(decoded).query).get("uddg") or [decoded])[0]
            url = _clean_url(decoded)
            if not url or url in seen:
                continue
            title = html.unescape(" ".join(raw_title.split()))
            title = re.sub(r"^\(PDF\)\s*", "", title, flags=re.I)
            title = re.sub(r"\s*[|–-]\s*Academia(?:\.edu)?\s*$", "", title, flags=re.I)
            if not title:
                title = urlparse(url).path.rsplit("/", 1)[-1].replace("_", " ")
            seen.add(url)
            items.append(AcademiaItem(title=title[:400], url=url))
            if len(items) >= max(1, min(limit, 10)):
                break
        return items

    async def download(self, url: str) -> Path:
        return await asyncio.to_thread(self._download_sync, url)

    def _download_sync(self, url: str) -> Path:
        clean_url = _clean_url(url)
        if not clean_url:
            raise AcademiaError("Нужна прямая HTTPS-ссылка на документ Academia.edu.")
        script = self.downloader_dir / "main.py"
        if not script.is_file():
            raise AcademiaError("Локальный academiadl-py не установлен.")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        destination = self.output_dir / f"academia-{int(time.time())}.pdf"
        command = [
            self.python, str(script), clean_url,
            "--pages", "all", "--output", str(destination),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.downloader_dir),
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AcademiaError("Academia не завершила сохранение за 15 минут.") from exc
        if completed.returncode or not destination.is_file() or destination.stat().st_size == 0:
            tail = " ".join((completed.stdout + "\n" + completed.stderr).split())[-300:]
            raise AcademiaError(
                "Не удалось сохранить документ. Откройте страницу в браузере и проверьте доступ."
                + (f" ({tail})" if tail else "")
            )
        return destination


