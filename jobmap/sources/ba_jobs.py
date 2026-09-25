"""Jobsuche-API der Bundesagentur für Arbeit (https://github.com/bundesAPI/jobsuche-api).

Stand 09/2026: Die Suche läuft über /pc/v6/jobs (/pc/v4/jobs liefert 403),
Details weiterhin über /pc/v4/jobdetails/{base64(refnr)}.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from typing import Any

import requests

from jobmap.textutil import KeywordMatcher, company_key, distance_km

log = logging.getLogger(__name__)

BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
SEARCH_URL = f"{BASE_URL}/pc/v6/jobs"
DETAILS_URL = f"{BASE_URL}/pc/v4/jobdetails/{{code}}"
API_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
JOB_PAGE_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"


def _locations(item: dict) -> list[dict]:
    """Einheitliche Liste von Arbeitsorten, egal ob v6- oder älteres Schema."""
    result = []
    for loc in item.get("stellenlokationen") or []:
        addr = loc.get("adresse") or {}
        result.append({
            "lat": loc.get("breite"),
            "lon": loc.get("laenge"),
            "street": " ".join(filter(None, [addr.get("strasse"), addr.get("hausnummer")])),
            "plz": addr.get("plz"),
            "city": addr.get("ort"),
        })
    legacy = item.get("arbeitsort")
    if legacy:
        coords = legacy.get("koordinaten") or {}
        result.append({
            "lat": coords.get("lat"),
            "lon": coords.get("lon"),
            "street": legacy.get("strasse"),
            "plz": legacy.get("plz"),
            "city": legacy.get("ort"),
        })
    return result


def parse_job(item: dict, center: tuple[float, float]) -> dict | None:
    """Wandelt einen Eintrag der Suchantwort in unser Job-Format um."""
    refnr = item.get("referenznummer") or item.get("refnr")
    company = (item.get("firma") or item.get("arbeitgeber") or "").strip()
    title = (item.get("stellenangebotsTitel") or item.get("titel") or item.get("beruf") or "").strip()
    if not refnr or not company or not title:
        return None

    # Bei mehreren Arbeitsorten den nächstgelegenen zu Karlsruhe nehmen.
    best, best_dist = None, None
    for loc in _locations(item):
        if loc["lat"] is None or loc["lon"] is None:
            if best is None:
                best = loc
            continue
        dist = distance_km(center[0], center[1], loc["lat"], loc["lon"])
        if best_dist is None or dist < best_dist:
            best, best_dist = loc, dist
    best = best or {}

    published = (item.get("veroeffentlichungszeitraum") or {}).get("von") or item.get(
        "aktuelleVeroeffentlichungsdatum")
    hours = []
    if item.get("arbeitszeitVollzeit"):
        hours.append("Vollzeit")
    if any(v for k, v in item.items() if k.startswith("arbeitszeitTeilzeit")):
        hours.append("Teilzeit")
    contract = {"BEFRISTET": "befristet", "UNBEFRISTET": "unbefristet"}.get(item.get("vertragsdauer"))
    return {
        "refnr": refnr,
        "title": title,
        "company": company,
        "company_key": company_key(company),
        "offer_type": item.get("stellenangebotsart") or item.get("angebotsart"),
        "occupation": item.get("hauptberuf") or item.get("beruf"),
        "published": published,
        "first_published": item.get("datumErsteVeroeffentlichung"),
        "lat": best.get("lat"),
        "lon": best.get("lon"),
        "street": best.get("street"),
        "plz": best.get("plz"),
        "city": best.get("city"),
        "distance_km": round(best_dist, 1) if best_dist is not None else None,
        "hours": hours or None,
        "homeoffice": item.get("homeofficemoeglich"),
        "contract": contract,
        "salary_from": item.get("gehaltsspanneVon"),
        "salary_to": item.get("gehaltsspanneBis"),
        "url": item.get("externeURL") or item.get("externeUrl") or JOB_PAGE_URL.format(refnr=refnr),
    }


def title_score(job: dict, matcher: KeywordMatcher) -> int:
    """Stichwort-Score des Stellentitels; der Firmenname im Titel ("NTT DATA: ...") zählt nicht mit."""
    title = re.sub(re.escape(job["company"]), " ", job["title"], flags=re.I)
    return matcher.score(title)[0]


def is_relevant(job: dict, cfg: dict, matcher: KeywordMatcher, exclude: list[re.Pattern]) -> bool:
    if any(p.search(job["title"]) for p in exclude):
        return False
    return title_score(job, matcher) >= cfg["jobs"].get("min_title_score", 0)


def search_jobs(session: requests.Session, cfg: dict) -> list[dict]:
    """Fragt alle Suchbegriffe ab und dedupliziert über die Referenznummer."""
    jcfg, region = cfg["jobs"], cfg["region"]
    center = (region["lat"], region["lon"])
    exclude = [re.compile(p, re.I) for p in jcfg.get("exclude_title_patterns", [])]
    matcher = KeywordMatcher(cfg["scoring"]["keywords"])
    jobs: dict[str, dict] = {}
    excluded = 0

    for term in jcfg["search_terms"]:
        for page in range(1, jcfg.get("max_pages", 5) + 1):
            params = {
                "was": term,
                "wo": region["name"],
                "umkreis": region["radius_km"],
                "veroeffentlichtseit": jcfg.get("veroeffentlichtseit", 60),
                "angebotsart": ";".join(str(a) for a in jcfg.get("angebotsart", [1])),
                "zeitarbeit": str(jcfg.get("zeitarbeit", False)).lower(),
                "pav": str(jcfg.get("private_arbeitsvermittlung", False)).lower(),
                "page": page,
                "size": jcfg.get("page_size", 100),
            }
            resp = session.get(SEARCH_URL, params=params, headers=API_HEADERS, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("ergebnisliste") or data.get("stellenangebote") or []
            for item in items:
                job = parse_job(item, center)
                if job is None:
                    continue
                if not is_relevant(job, cfg, matcher, exclude):
                    excluded += 1
                    continue
                if job["distance_km"] is not None and job["distance_km"] > region["radius_km"] + 5:
                    continue
                existing = jobs.setdefault(job["refnr"], {**job, "search_terms": []})
                if term not in existing["search_terms"]:
                    existing["search_terms"].append(term)
            total = int(data.get("maxErgebnisse") or 0)
            log.info("Jobsuche '%s' Seite %d: %d Treffer (gesamt %d)", term, page, len(items), total)
            time.sleep(jcfg.get("request_delay_s", 0.5))
            if len(items) < params["size"] or page * params["size"] >= total:
                break

    log.info("Jobsuche: %d eindeutige Stellen behalten, %d Treffer per Titelfilter verworfen",
             len(jobs), excluded)
    return sorted(jobs.values(), key=lambda j: j["refnr"])


def fetch_job_details(session: requests.Session, refnr: str) -> dict[str, Any] | None:
    """Details einer Stelle (u. a. Beschreibungstext); None bei Fehlern."""
    code = base64.b64encode(refnr.encode()).decode()
    try:
        resp = session.get(DETAILS_URL.format(code=code), headers=API_HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Jobdetails für %s nicht abrufbar: %s", refnr, exc)
        return None
