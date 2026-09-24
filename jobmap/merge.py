"""Führt Firmen aus allen Quellen zusammen und ordnet ihnen die Stellen zu."""

from __future__ import annotations

import logging

from rapidfuzz import fuzz, process

from jobmap.textutil import company_key, distance_km, normalize_name

log = logging.getLogger(__name__)

# Je kleiner, desto verlässlicher die Ortsangabe der Quelle.
LOCATION_PRIORITY = {"seed": 0, "osm": 1, "wikidata": 2, "wikidata_hq": 3, "ba": 4}

OSM_LABELS = {
    ("office", "company"): "Firma",
    ("office", "research"): "Forschung",
    ("office", "it"): "IT",
    ("office", "engineer"): "Ingenieurbüro",
    ("office", "energy_supplier"): "Energieversorger",
    ("amenity", "research_institute"): "Forschungseinrichtung",
    ("man_made", "works"): "Werk/Produktion",
}


def _address(street: str | None, plz: str | None, city: str | None) -> str | None:
    tail = " ".join(p for p in (plz, city) if p)
    return ", ".join(p for p in (street, tail) if p) or None


def from_osm(el: dict) -> dict:
    tags = el["tags"]
    labels = [label for (k, v), label in OSM_LABELS.items() if tags.get(k) == v]
    labels += [tags[k] for k in ("industrial", "product", "research") if tags.get(k)]
    street = " ".join(p for p in (tags.get("addr:street"), tags.get("addr:housenumber")) if p) or None
    return {
        "name": el["name"],
        "sources": ["osm"],
        "refs": {"osm": [el["id"]]},
        "lat": el["lat"], "lon": el["lon"], "loc_source": "osm",
        "city": tags.get("addr:city"),
        "address": _address(street, tags.get("addr:postcode"), tags.get("addr:city")),
        "website": tags.get("website") or tags.get("contact:website") or tags.get("url"),
        "description": tags.get("description"),
        "tags": labels,
    }


def from_wikidata(item: dict) -> dict:
    return {
        "name": item["name"],
        "sources": ["wikidata"],
        "refs": {"wikidata": [item["id"]]},
        "lat": item["lat"], "lon": item["lon"],
        "loc_source": "wikidata_hq" if item.get("approximate_location") else "wikidata",
        "website": item.get("website"),
        "description": item.get("description"),
        "industry": item.get("industries") or None,
        "tags": [],
    }


def from_seed(entry: dict, lat: float | None, lon: float | None) -> dict:
    return {
        "name": entry["name"],
        "sources": ["seed"],
        "refs": {},
        "lat": lat, "lon": lon, "loc_source": "seed",
        "city": entry.get("city"),
        "address": entry.get("address"),
        "website": entry.get("website"),
        "notes": entry.get("notes"),
        "tags": entry.get("tags") or [],
        "manual_score": entry.get("score"),
        "manual_reason": entry.get("reason"),
    }


def from_job(job: dict) -> dict:
    return {
        "name": job["company"],
        "sources": ["ba"],
        "refs": {},
        "lat": job.get("lat"), "lon": job.get("lon"), "loc_source": "ba",
        "city": job.get("city"),
        "address": _address(job.get("street"), job.get("plz"), job.get("city")),
        "tags": [],
    }


class CompanyIndex:
    """Firmen nach normalisiertem Namen; Einträge mit gleichem Schlüssel werden vereinigt."""

    def __init__(self):
        self.by_key: dict[str, dict] = {}

    def add(self, record: dict) -> dict:
        key = company_key(record["name"])
        if not key:
            return record
        record["key"] = key
        existing = self.by_key.get(key)
        if existing is None:
            self.by_key[key] = record
            return record
        self._merge(existing, record)
        return existing

    @staticmethod
    def _merge(target: dict, other: dict) -> None:
        for source in other["sources"]:
            if source not in target["sources"]:
                target["sources"].append(source)
        for kind, ids in other.get("refs", {}).items():
            target.setdefault("refs", {}).setdefault(kind, [])
            target["refs"][kind] = sorted(set(target["refs"][kind]) | set(ids))
        for tag in other.get("tags") or []:
            if tag not in target["tags"]:
                target["tags"].append(tag)
        better_location = other.get("lat") is not None and (
            target.get("lat") is None
            or LOCATION_PRIORITY[other["loc_source"]] < LOCATION_PRIORITY[target["loc_source"]])
        if better_location:
            for field in ("lat", "lon", "loc_source", "address", "city"):
                if other.get(field) is not None:
                    target[field] = other[field]
        for field, value in other.items():
            if value is not None and target.get(field) in (None, "", []):
                target[field] = value
        if other["sources"] == ["seed"]:
            # Angaben aus der Seed-Liste haben Vorrang vor automatisch gefundenen.
            for field in ("name", "website", "notes", "manual_score", "manual_reason"):
                if other.get(field) is not None:
                    target[field] = other[field]

    def match_job_company(self, name: str, lat: float | None, lon: float | None,
                          max_km: float = 30.0, cutoff: float = 92) -> dict | None:
        """Exakter Schlüssel oder, falls nicht vorhanden, ähnlicher Name in der Nähe."""
        key = company_key(name)
        if key in self.by_key:
            return self.by_key[key]
        choices = {k: k.replace("-", " ") for k in self.by_key}  # Schlüssel = normalisierter Name
        for _, score, match_key in process.extract(
                normalize_name(name), choices, scorer=fuzz.token_sort_ratio, score_cutoff=cutoff, limit=5):
            candidate = self.by_key[match_key]
            if lat is None or candidate.get("lat") is None or distance_km(
                    lat, lon, candidate["lat"], candidate["lon"]) <= max_km:
                log.debug("Stellen-Firma %r zugeordnet zu %r (%.0f)", name, candidate["name"], score)
                return candidate
        return None


def attach_jobs(index: CompanyIndex, jobs: list[dict]) -> None:
    """Ordnet jede Stelle einer Firma zu; unbekannte Arbeitgeber werden neu angelegt."""
    for job in jobs:
        company = index.match_job_company(job["company"], job.get("lat"), job.get("lon"))
        if company is None:
            company = index.add(from_job(job))
        elif "ba" not in company["sources"]:
            company["sources"].append("ba")
        job["company_key"] = company["key"]
        company.setdefault("job_refs", []).append(job["refnr"])
        company.setdefault("job_titles", []).append(job["title"])
