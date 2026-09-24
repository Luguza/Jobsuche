"""Kurzbeschreibung einer Firma aus ihrer Startseite (nur <title> und Meta-Beschreibung).

Pro Domain wird vorher robots.txt geprüft. Ergebnisse werden in data/website_cache.json
zwischengespeichert, damit jede Seite nur selten abgerufen wird.
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

MAX_BYTES = 400_000
MAX_TEXT = 400


def normalize_url(url: str) -> str | None:
    """Erste URL eines Feldes (OSM erlaubt 'a;b'), mit Schema und ohne Query."""
    url = re.split(r"[\s;,]+", (url or "").strip())[0]
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    parts = urlsplit(url)
    if not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"


class RobotsCache:
    def __init__(self, session: requests.Session, user_agent: str, timeout: float):
        self.session, self.user_agent, self.timeout = session, user_agent, timeout
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            cached = origin in self._parsers
            parser = self._parsers.get(origin)
        if not cached:
            parser = self._load(origin)
            with self._lock:
                self._parsers[origin] = parser
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def _load(self, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        try:
            resp = self.session.get(f"{origin}/robots.txt", timeout=self.timeout)
        except requests.RequestException:
            return None  # robots.txt nicht erreichbar -> Startseite wird gleich ohnehin scheitern
        if resp.status_code in (401, 403):
            parser.disallow_all = True
        elif resp.ok:
            parser.parse(resp.text.splitlines())
        else:
            parser.allow_all = True
        return parser


def extract_meta(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    def meta(**attrs) -> str:
        tag = soup.find("meta", attrs=attrs)
        return (tag.get("content") or "").strip() if tag else ""

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description = meta(name="description") or meta(property="og:description") or meta(name="Description")
    return {
        "title": " ".join(title.split())[:MAX_TEXT],
        "description": " ".join(description.split())[:MAX_TEXT],
    }


def fetch_meta(session: requests.Session, robots: RobotsCache, url: str, timeout: float) -> dict:
    today = date.today().isoformat()
    if not robots.allowed(url):
        return {"status": "robots_disallowed", "fetched": today}
    try:
        with session.get(url, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            if "html" not in resp.headers.get("Content-Type", "html"):
                return {"status": "not_html", "fetched": today}
            raw = resp.raw.read(MAX_BYTES, decode_content=True)
            html = raw.decode(resp.encoding or "utf-8", errors="replace")
    except requests.RequestException as exc:
        return {"status": "error", "error": type(exc).__name__, "fetched": today}
    return {"status": "ok", "fetched": today, **extract_meta(html)}


def update_website_cache(session: requests.Session, cfg: dict, urls: list[str], cache: dict) -> dict:
    """Ruft fehlende bzw. veraltete Einträge ab und gibt den aktualisierten Cache zurück."""
    wcfg = cfg["websites"]
    today = date.today()

    def stale(entry: dict | None) -> bool:
        if not entry:
            return True
        age = today - date.fromisoformat(entry["fetched"])
        limit = wcfg["refresh_days"] if entry.get("status") == "ok" else wcfg["retry_failed_days"]
        return age > timedelta(days=limit)

    todo = sorted({u for u in urls if stale(cache.get(u))})
    if not todo:
        return cache
    log.info("Websites: %d Startseiten abrufen", len(todo))
    robots = RobotsCache(session, cfg["user_agent"], wcfg["timeout_s"])
    with ThreadPoolExecutor(max_workers=wcfg.get("workers", 8)) as pool:
        results = pool.map(lambda u: (u, fetch_meta(session, robots, u, wcfg["timeout_s"])), todo)
        for i, (url, entry) in enumerate(results, 1):
            cache[url] = entry
            if i % 250 == 0:
                log.info("Websites: %d/%d abgerufen", i, len(todo))
    ok = sum(1 for u in todo if cache[u]["status"] == "ok")
    log.info("Websites: %d von %d erfolgreich", ok, len(todo))
    return cache
