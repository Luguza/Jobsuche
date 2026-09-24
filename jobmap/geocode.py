"""Geokodierung über Nominatim (geopy) mit persistentem Cache in data/geocache.json."""

from __future__ import annotations

import logging
from pathlib import Path

from geopy.exc import GeopyError
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from jobmap.config import read_json, write_json

log = logging.getLogger(__name__)


class CachedGeocoder:
    """Jede Adresse wird nur einmal abgefragt; auch "nicht gefunden" wird gespeichert."""

    def __init__(self, cache_path: Path, user_agent: str, min_delay_s: float = 1.1,
                 country_codes: list[str] | None = None):
        self.cache_path = cache_path
        self.cache: dict[str, dict | None] = read_json(cache_path, {})
        self.user_agent = user_agent
        self.min_delay_s = min_delay_s
        self.country_codes = country_codes
        self._geocode = None
        self.queries = 0

    @staticmethod
    def _key(query: str) -> str:
        return " ".join(query.lower().split())

    def geocode(self, query: str) -> tuple[float, float] | None:
        key = self._key(query)
        if not key:
            return None
        if key in self.cache:
            hit = self.cache[key]
            return (hit["lat"], hit["lon"]) if hit else None
        if self._geocode is None:
            geolocator = Nominatim(user_agent=self.user_agent, timeout=15)
            self._geocode = RateLimiter(geolocator.geocode, min_delay_seconds=self.min_delay_s,
                                        max_retries=2, error_wait_seconds=5.0)
        self.queries += 1
        try:
            location = self._geocode(query, country_codes=self.country_codes, language="de")
        except GeopyError as exc:
            log.warning("Geokodierung fehlgeschlagen für %r: %s", query, exc)
            return None  # Netzwerkfehler nicht cachen, beim nächsten Lauf erneut versuchen
        if location is None:
            self.cache[key] = None
            return None
        self.cache[key] = {
            "lat": round(location.latitude, 6),
            "lon": round(location.longitude, 6),
            "display_name": location.address,
        }
        return self.cache[key]["lat"], self.cache[key]["lon"]

    def save(self) -> None:
        write_json(self.cache_path, self.cache)
