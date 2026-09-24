"""Firmen und Forschungseinrichtungen aus OpenStreetMap über die Overpass API.

Daten © OpenStreetMap-Mitwirkende, lizenziert unter ODbL (Namensnennung auf der Karte).
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

# Diese Tags werden übernommen; alles andere wird verworfen, damit die JSON-Dateien klein bleiben.
KEEP_TAGS = (
    "office", "amenity", "man_made", "industrial", "operator", "brand", "description",
    "website", "contact:website", "url", "addr:street", "addr:housenumber", "addr:postcode",
    "addr:city", "wikidata", "research", "product",
)


def build_query(cfg: dict) -> str:
    region, ocfg = cfg["region"], cfg["osm"]
    around = f"(around:{int(region['radius_km'] * 1000)},{region['lat']},{region['lon']})"
    parts = "".join(f"nwr{sel}{around};" for sel in ocfg["selectors"])
    return f"[out:json][timeout:{ocfg.get('timeout_s', 180)}];({parts});out center tags;"


def parse_elements(elements: list[dict]) -> list[dict]:
    result = []
    for el in elements:
        tags = el.get("tags") or {}
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if not tags.get("name") or lat is None or lon is None:
            continue
        result.append({
            "id": f"{el['type']}/{el['id']}",
            "name": tags["name"],
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "tags": {k: tags[k] for k in KEEP_TAGS if k in tags},
        })
    return sorted(result, key=lambda e: e["id"])


def fetch_osm(session: requests.Session, cfg: dict) -> list[dict]:
    """Probiert die konfigurierten Overpass-Instanzen nacheinander."""
    query = build_query(cfg)
    last_error: Exception | None = None
    for endpoint in cfg["osm"]["endpoints"]:
        try:
            resp = session.post(endpoint, data={"data": query}, timeout=cfg["osm"].get("timeout_s", 180) + 30)
            resp.raise_for_status()
            elements = parse_elements(resp.json().get("elements", []))
            log.info("Overpass (%s): %d Einträge", endpoint, len(elements))
            return elements
        except (requests.RequestException, ValueError) as exc:
            log.warning("Overpass-Instanz %s fehlgeschlagen: %s", endpoint, exc)
            last_error = exc
    raise RuntimeError(f"Alle Overpass-Instanzen fehlgeschlagen: {last_error}")
