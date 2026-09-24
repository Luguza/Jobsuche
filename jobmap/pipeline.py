"""Datenaktualisierung: Quellen abfragen, zusammenführen, bewerten, JSON schreiben."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from jobmap.config import DATA_DIR, read_json, write_json
from jobmap.geocode import CachedGeocoder
from jobmap.history import diff_run
from jobmap.http import make_session
from jobmap.merge import CompanyIndex, attach_jobs, from_osm, from_seed, from_wikidata
from jobmap.scoring import company_text, score_companies
from jobmap.sources.ba_jobs import search_jobs
from jobmap.sources.osm import fetch_osm
from jobmap.sources.seed import load_seed
from jobmap.sources.websites import normalize_url, update_website_cache
from jobmap.sources.wikidata import fetch_wikidata
from jobmap.textutil import KeywordMatcher, distance_km

log = logging.getLogger(__name__)

# Felder, die in data/companies.json landen (Reihenfolge egal, JSON wird sortiert).
COMPANY_FIELDS = (
    "key", "name", "sources", "refs", "lat", "lon", "loc_source", "city", "address", "website",
    "description", "industry", "tags", "notes", "meta_title", "meta_description", "job_refs",
    "score", "reason", "score_method", "first_seen", "distance_km",
)


def _fetch_or_previous(name: str, fetch: Callable[[], list], data_dir: Path) -> tuple[list, str]:
    """Rohdaten einer Quelle abrufen; bei Fehlern den letzten Stand aus data/sources/ nehmen."""
    path = data_dir / "sources" / f"{name}.json"
    try:
        data = fetch()
    except Exception as exc:  # noqa: BLE001 - jede Störung der Quelle soll den Lauf nicht abbrechen
        previous = read_json(path)
        if previous is None:
            raise
        log.warning("%s nicht abrufbar (%s), verwende letzten Stand", name, exc)
        return previous, "letzter Stand"
    write_json(path, data)
    return data, "aktuell"


def _geocode_missing(records: list[dict], geocoder: CachedGeocoder, queries: Callable[[dict], list[str]]):
    for record in records:
        if record.get("lat") is not None:
            continue
        for query in queries(record):
            coords = geocoder.geocode(query)
            if coords:
                record["lat"], record["lon"] = coords
                break


def run_update(cfg: dict, data_dir: Path = DATA_DIR, use_llm: bool = True,
               fetch_websites: bool = True) -> dict:
    region = cfg["region"]
    center = (region["lat"], region["lon"])
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    session = make_session(cfg["user_agent"])

    prev_companies = {c["key"]: c for c in read_json(data_dir / "companies.json", [])}
    prev_jobs = {j["refnr"]: j for j in read_json(data_dir / "jobs.json", [])}
    geocoder = CachedGeocoder(data_dir / "geocache.json", cfg["user_agent"],
                              cfg["geocoding"]["min_delay_s"], cfg["geocoding"].get("country_codes"))

    # 1. Quellen
    jobs = search_jobs(session, cfg)
    osm, osm_status = _fetch_or_previous("osm", lambda: fetch_osm(session, cfg), data_dir)
    wikidata, wd_status = _fetch_or_previous("wikidata", lambda: fetch_wikidata(session, cfg), data_dir)
    seed = load_seed(data_dir / "seed_companies.yaml")

    _geocode_missing(jobs, geocoder, lambda j: [
        q for q in (", ".join(p for p in (j.get("street"), j.get("plz"), j.get("city")) if p),
                    ", ".join(p for p in (j.get("plz"), j.get("city")) if p)) if q])
    seed_records = [from_seed(e, e.get("lat"), e.get("lon")) for e in seed]
    _geocode_missing(seed_records, geocoder, lambda r: [
        q for q in (r.get("address"), ", ".join(p for p in (r["name"], r.get("city")) if p)) if q])

    # 2. Firmen zusammenführen (Seed zuletzt, damit dessen Angaben Vorrang haben)
    index = CompanyIndex()
    for el in osm:
        index.add(from_osm(el))
    for item in wikidata:
        index.add(from_wikidata(item))
    for record in seed_records:
        if record.get("lat") is None:
            log.warning("Seed-Eintrag %r konnte nicht geokodiert werden", record["name"])
            continue
        index.add(record)
    attach_jobs(index, [j for j in jobs if j.get("lat") is not None])
    jobs = [j for j in jobs if j.get("lat") is not None]

    companies = []
    for company in index.by_key.values():
        if company.get("lat") is None:
            continue
        company["distance_km"] = round(distance_km(*center, company["lat"], company["lon"]), 1)
        if company["distance_km"] <= region["radius_km"]:
            companies.append(company)

    # 3. Startseiten (Titel + Meta-Beschreibung) als Kontext; Firmen mit Ausschlusswort im Namen überspringen
    matcher = KeywordMatcher(cfg["scoring"]["keywords"])
    for company in companies:
        company["website"] = normalize_url(company.get("website") or "")
    website_cache = read_json(data_dir / "website_cache.json", {})
    if fetch_websites and cfg["websites"].get("enabled", True):
        wanted = [c["website"] for c in companies
                  if c["website"] and not any(p.search(c["name"]) for p in matcher.negative)]
        web_session = make_session(cfg["user_agent"], retries=0)
        website_cache = update_website_cache(web_session, cfg, wanted, website_cache)
        write_json(data_dir / "website_cache.json", website_cache)
    for company in companies:
        meta = website_cache.get(company["website"] or "") or {}
        if meta.get("status") == "ok":
            company["meta_title"] = meta.get("title") or None
            company["meta_description"] = meta.get("description") or None

    # 4. Stufe 1: grober Stichwort-Filter (Firmen mit Stellen und Seed-Einträge kommen immer weiter)
    min_kw = cfg["scoring"]["stage1_min_keyword_score"]
    candidates = [
        c for c in companies
        if c.get("job_refs") or "seed" in c["sources"] or matcher.score(company_text(c))[0] >= min_kw
    ]
    log.info("Stufe 1: %d von %d Firmen sind Kandidaten", len(candidates), len(companies))

    # Nur der Hauptsitz-Ort aus Wikidata bekannt (Stadtmitte): genauere Lage per Name suchen
    for company in candidates:
        if company.get("loc_source") != "wikidata_hq":
            continue
        coords = geocoder.geocode(company["name"])
        if coords and distance_km(company["lat"], company["lon"], *coords) <= 25:
            company["lat"], company["lon"] = coords
            company["loc_source"] = "nominatim"
            company["distance_km"] = round(distance_km(*center, *coords), 1)
    candidates = [c for c in candidates if c["distance_km"] <= region["radius_km"]]

    # 5. Stufe 2: Relevanz-Score (Claude oder Stichwörter)
    score_cache = read_json(data_dir / "score_cache.json", {})
    score_cache = score_companies(candidates, cfg, score_cache, use_llm=use_llm)
    write_json(data_dir / "score_cache.json", score_cache)

    # 6. Ausgabe
    for company in candidates:
        company["first_seen"] = (prev_companies.get(company["key"]) or {}).get("first_seen", today)
        company["sources"] = sorted(company["sources"])
    for job in jobs:
        job["first_seen"] = (prev_jobs.get(job["refnr"]) or {}).get("first_seen", today)
    out_companies = sorted(
        ({f: c.get(f) for f in COMPANY_FIELDS if c.get(f) not in (None, "", [], {})} for c in candidates),
        key=lambda c: c["key"])
    jobs.sort(key=lambda j: j["refnr"])

    write_json(data_dir / "companies.json", out_companies)
    write_json(data_dir / "jobs.json", jobs)
    geocoder.save()

    meta = {
        "updated": now.isoformat(timespec="seconds"),
        "region": region,
        "counts": {
            "jobs": len(jobs),
            "companies": len(out_companies),
            "companies_with_jobs": sum(1 for c in out_companies if c.get("job_refs")),
            "osm_raw": len(osm),
            "wikidata_raw": len(wikidata),
            "seed": len(seed),
        },
        "score_methods": dict(Counter(c["score_method"] for c in out_companies)),
        "sources": {"osm": osm_status, "wikidata": wd_status},
    }
    write_json(data_dir / "meta.json", meta)

    history = read_json(data_dir / "history.json", [])
    history.append(diff_run(prev_jobs, jobs, prev_companies, out_companies, meta["updated"]))
    write_json(data_dir / "history.json", history)
    # Datum des ersten Laufs: was damals schon da war, wird auf der Karte nie als "neu" markiert
    meta["baseline"] = history[0]["timestamp"][:10]
    write_json(data_dir / "meta.json", meta)
    log.info("Fertig: %d Stellen, %d Firmen (Geokodierungen neu: %d)", len(jobs), len(out_companies),
             geocoder.queries)
    return meta
