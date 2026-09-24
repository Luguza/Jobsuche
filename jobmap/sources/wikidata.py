"""Unternehmen und Forschungseinrichtungen aus Wikidata (CC0) über den SPARQL-Endpunkt."""

from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger(__name__)

# {location} wird durch die Ortsbestimmung ersetzt: eigene Koordinaten (P625)
# oder Koordinaten des Hauptsitzes (P159). Zwei getrennte Abfragen vermeiden Timeouts.
_QUERY = """
SELECT ?item ?itemLabel ?itemDescription ?coord ?website
       (GROUP_CONCAT(DISTINCT ?industryLabel; separator="; ") AS ?industries)
WHERE {{
  {location}
  VALUES ?type {{ {types} }}
  ?item wdt:P31 ?type .
  FILTER NOT EXISTS {{ ?item wdt:P576 [] }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  OPTIONAL {{
    ?item wdt:P452 ?industry .
    ?industry rdfs:label ?industryLabel .
    FILTER(LANG(?industryLabel) = "de")
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "de,en". }}
}}
GROUP BY ?item ?itemLabel ?itemDescription ?coord ?website
"""

_AROUND = """SERVICE wikibase:around {{
    ?{var} wdt:P625 ?coord .
    bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "{radius}" .
  }}"""


def build_queries(cfg: dict) -> dict[str, str]:
    region = cfg["region"]
    types = " ".join(f"wd:{t}" for t in cfg["wikidata"]["types"])
    around = dict(lon=region["lon"], lat=region["lat"], radius=region["radius_km"])
    return {
        "own": _QUERY.format(location=_AROUND.format(var="item", **around), types=types),
        "hq": _QUERY.format(location=_AROUND.format(var="hq", **around) + "\n  ?item wdt:P159 ?hq .",
                            types=types),
    }


def _parse_point(wkt: str) -> tuple[float, float] | None:
    match = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", wkt or "")
    if not match:
        return None
    lon, lat = float(match.group(1)), float(match.group(2))
    return lat, lon


def parse_bindings(bindings: list[dict], approximate: bool) -> dict[str, dict]:
    items: dict[str, dict] = {}
    for b in bindings:
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        label = b.get("itemLabel", {}).get("value", "")
        point = _parse_point(b.get("coord", {}).get("value", ""))
        if not point or not label or label == qid:
            continue
        items.setdefault(qid, {
            "id": qid,
            "name": label,
            "description": b.get("itemDescription", {}).get("value", ""),
            "industries": b.get("industries", {}).get("value", ""),
            "website": b.get("website", {}).get("value", ""),
            "lat": round(point[0], 6),
            "lon": round(point[1], 6),
            "approximate_location": approximate,
        })
    return items


def fetch_wikidata(session: requests.Session, cfg: dict) -> list[dict]:
    items: dict[str, dict] = {}
    for kind, query in build_queries(cfg).items():
        resp = session.post(
            cfg["wikidata"]["endpoint"],
            data={"query": query},
            headers={"Accept": "application/sparql-results+json"},
            timeout=120,
        )
        resp.raise_for_status()
        parsed = parse_bindings(resp.json()["results"]["bindings"], approximate=(kind == "hq"))
        log.info("Wikidata (%s): %d Einträge", kind, len(parsed))
        for qid, item in parsed.items():
            items.setdefault(qid, item)  # eigene Koordinaten haben Vorrang vor dem Hauptsitz
    return sorted(items.values(), key=lambda i: i["id"])
