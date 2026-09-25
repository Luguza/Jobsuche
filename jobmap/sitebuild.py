"""Baut die statische Karte (folium/Leaflet) aus den JSON-Daten."""

from __future__ import annotations

import html
import logging
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import folium
from branca.colormap import LinearColormap
from folium.plugins import BeautifyIcon, LocateControl, MarkerCluster
from jinja2 import Template

from jobmap.classify import JOB_TYPE_NAMES, OTHER_CATEGORY, job_type, keyword_categories
from jobmap.config import DATA_DIR, read_json
from jobmap.scoring import company_text

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
PUBLISHED_DATA = ("companies.json", "jobs.json", "meta.json", "history.json")
# Grau (unpassend) -> Türkis -> Dunkelblau (sehr passend)
SCORE_COLORMAP = LinearColormap(["#c9ccd3", "#8fd1c1", "#2b9bc4", "#1f3b73"], index=[0, 4, 7, 10],
                                vmin=0, vmax=10)
NEW_DAYS = 7
METHOD_LABELS = {"claude": "Bewertung: Claude", "stichwörter": "Stichwort-Bewertung",
                 "manuell": "manuelle Bewertung"}


def score_colors() -> tuple[list[str], list[str]]:
    colors = [SCORE_COLORMAP(s)[:7] for s in range(11)]
    text = []
    for c in colors:
        r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
        text.append("#1d2433" if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "#ffffff")
    return colors, text


class FilterPanel(folium.MacroElement):
    """Such- und Filterfeld, Legende und Stand-Datum (siehe templates/panel.j2)."""

    _template = Template((TEMPLATE_DIR / "panel.j2").read_text(encoding="utf-8"))

    def __init__(self, jobs_cluster: MarkerCluster, companies_cluster: MarkerCluster, **context):
        super().__init__()
        self._name = "FilterPanel"
        self.jobs_cluster = jobs_cluster.get_name()
        self.companies_cluster = companies_cluster.get_name()
        self.colors, self.text_colors = score_colors()
        for key, value in context.items():
            setattr(self, key, value)


def _fmt_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return date.fromisoformat(value[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return value


def _badge(score: int, colors: list[str], text: list[str]) -> str:
    return (f'<span class="jm-badge" style="background:{colors[score]};color:{text[score]}">'
            f"{score}/10</span>")


def new_since(meta: dict) -> date:
    """Ab diesem Datum gilt ein Eintrag als "neu": letzte 7 Tage, aber nie der allererste Lauf."""
    updated = meta.get("updated")
    reference = datetime.fromisoformat(updated).date() if updated else date.today()
    since = reference - timedelta(days=NEW_DAYS)
    if meta.get("baseline"):
        since = max(since, date.fromisoformat(meta["baseline"]) + timedelta(days=1))
    return since


def _is_new(first_seen: str | None, since: date) -> bool:
    return bool(first_seen) and date.fromisoformat(first_seen) >= since


def company_popup(company: dict, jobs: list[dict], colors, text, since: date) -> str:
    e = html.escape
    parts = [f'<div class="jm-pop"><h3>{e(company["name"])}</h3>',
             _badge(company["score"], colors, text)]
    if _is_new(company.get("first_seen"), since):
        parts.append('<span class="jm-new">neu</span>')
    method = METHOD_LABELS.get(company.get("score_method"), company.get("score_method", ""))
    parts.append(f'<div class="jm-reason">{e(company.get("reason", ""))} '
                 f'<span class="jm-sub">({e(method)})</span></div>')
    info = [company.get("city") or company.get("address"),
            f'{company["distance_km"]:.0f} km vom Zentrum' if company.get("distance_km") is not None else None,
            company.get("industry"), ", ".join(company.get("tags") or []) or None]
    parts.append(f'<div class="jm-sub">{e(" · ".join(i for i in info if i))}</div>')
    summary = company.get("description") or company.get("meta_description")
    if summary:
        parts.append(f'<div class="jm-sub" style="margin-top:4px">{e(summary[:220])}</div>')
    if company.get("categories_display"):
        parts.append(f'<div class="jm-sub">Branche: {e(", ".join(company["categories_display"]))}</div>')
    if jobs:
        # Reihenfolge wie in marker.options.jobs, damit die Filter einzelne Einträge ausblenden können
        parts.append(f'<div style="margin-top:8px"><b>Passende Stellen ({len(jobs)})</b>'
                     '<div class="jm-sub jm-hidden-note"></div><ul>')
        for i, job in enumerate(jobs):
            new = '<span class="jm-new">neu</span>' if _is_new(job.get("first_seen"), since) else ""
            parts.append(
                f'<li data-job="{i}"><a href="{e(job["url"])}" target="_blank" rel="noopener">'
                f'{e(job["title"])}</a>{new}<br><span class="jm-sub">{e(_job_details(job))}</span></li>')
        parts.append("</ul></div>")
    links = []
    if company.get("website"):
        links.append(f'<a href="{e(company["website"])}" target="_blank" rel="noopener">Website</a>')
    for qid in (company.get("refs") or {}).get("wikidata", [])[:1]:
        links.append(f'<a href="https://www.wikidata.org/wiki/{e(qid)}" target="_blank" rel="noopener">Wikidata</a>')
    for osm_id in (company.get("refs") or {}).get("osm", [])[:1]:
        links.append(f'<a href="https://www.openstreetmap.org/{e(osm_id)}" target="_blank" rel="noopener">OSM</a>')
    if links:
        parts.append(f'<div style="margin-top:6px">{" · ".join(links)}</div>')
    parts.append("</div>")
    return "".join(parts)


def _salary(job: dict) -> str | None:
    """Gehaltsspanne; die BA liefert je nach Stelle Stunden-, Monats- oder Jahreswerte."""
    values = [float(v) for v in (job.get("salary_from"), job.get("salary_to")) if v]
    if not values:
        return None
    top = max(values)
    if top < 200:
        text, unit = [f"{v:.0f}" for v in values], "€/Std."
    elif top < 15000:
        text, unit = [f"{v:,.0f}".replace(",", ".") for v in values], "€/Monat"
    else:
        text, unit = [f"{v / 1000:.0f}" for v in values], "T€/Jahr"
    if len(values) == 2:
        return f"{text[0]}–{text[1]} {unit}" if text[0] != text[1] else f"{text[0]} {unit}"
    return f"ab {text[0]} {unit}" if job.get("salary_from") else f"bis {text[0]} {unit}"


def _job_details(job: dict) -> str:
    parts = [job_type(job), " / ".join(job.get("hours") or []) or None, job.get("contract"),
             "Homeoffice möglich" if job.get("homeoffice") else None, _salary(job),
             job.get("city"), f"seit {_fmt_date(job['published'])}" if job.get("published") else None]
    return " · ".join(p for p in parts if p)


def _job_filter_data(job: dict, reference: date, since: date) -> dict:
    """Kompakte Angaben je Stelle für die Filter im Browser."""
    try:
        age = (reference - date.fromisoformat(job["published"][:10])).days
    except (KeyError, TypeError, ValueError):
        age = None
    return {"t": job_type(job), "h": job.get("hours") or [], "ho": bool(job.get("homeoffice")),
            "age": age, "d": job.get("distance_km"), "n": _is_new(job.get("first_seen"), since)}


def _search_text(company: dict, jobs: list[dict]) -> str:
    fields = [company["name"], company.get("city"), company.get("industry"), company.get("description"),
              company.get("meta_description"), company.get("reason"), " ".join(company.get("tags") or [])]
    fields += [j["title"] for j in jobs]
    return " ".join(f for f in fields if f).lower()


def _marker(location, company, jobs, kind, colors, text, since: date, reference: date) -> folium.Marker:
    score = int(company["score"])
    icon = BeautifyIcon(
        icon_shape="marker" if kind == "job" else "circle",
        number=score,
        border_color="#ffffff",
        border_width=2,
        background_color=colors[score],
        text_color=text[score],
        inner_icon_style="font-weight:700;font-size:12px;" + ("margin-top:1px;" if kind == "job" else ""),
    )
    is_new = _is_new(company.get("first_seen"), since) or any(
        _is_new(j.get("first_seen"), since) for j in jobs)
    return folium.Marker(
        location=location,
        icon=icon,
        tooltip=html.escape(company["name"]),
        popup=folium.Popup(company_popup(company, jobs, colors, text, since), max_width=300, lazy=True),
        score=score,
        search=_search_text(company, jobs),
        label=company["name"],
        isnew=is_new,
        cats=company["categories_display"],
        dist=company.get("distance_km"),
        jobs=[_job_filter_data(j, reference, since) for j in jobs] or None,
        riseOnHover=True,
    )


def build_map(cfg: dict, companies: list[dict], jobs: list[dict], meta: dict) -> folium.Map:
    region, mcfg = cfg["region"], cfg["map"]
    colors, text = score_colors()
    updated = meta.get("updated")
    reference = datetime.fromisoformat(updated).date() if updated else date.today()
    since = new_since(meta)
    by_key = {c["key"]: c for c in companies}
    titles: dict[str, list[str]] = defaultdict(list)
    for job in jobs:
        titles[job.get("company_key")].append(job["title"])
    for company in companies:
        # Branchen von Claude, sonst per Stichwort (auch aus den Stellentiteln)
        company["categories_display"] = company.get("categories") or keyword_categories(
            company_text({**company, "job_titles": titles.get(company["key"])}), cfg.get("categories", {}))

    fmap = folium.Map(location=[region["lat"], region["lon"]], zoom_start=mcfg.get("zoom_start", 10),
                      tiles=None, zoom_control="bottomright", control_scale=True)
    folium.TileLayer("OpenStreetMap", name="Karte (OpenStreetMap)").add_to(fmap)
    folium.Circle([region["lat"], region["lon"]], radius=region["radius_km"] * 1000, color="#1f3b73",
                  weight=1.5, fill=False, dash_array="6 6", interactive=False).add_to(fmap)

    # Stellen je Firma und Standort bündeln, neueste zuerst
    job_groups: dict[tuple, list[dict]] = defaultdict(list)
    for job in sorted(jobs, key=lambda j: j.get("published") or "", reverse=True):
        if job.get("company_key") in by_key and job.get("lat") is not None:
            job_groups[(job["company_key"], round(job["lat"], 3), round(job["lon"], 3))].append(job)
    job_companies = {key for key, _, _ in job_groups}
    open_companies = [c for c in companies if c["key"] not in job_companies
                      and not c.get("job_refs") and c["score"] >= mcfg.get("min_score_companies", 5)]

    cluster_opts = {"showCoverageOnHover": False, "spiderfyOnMaxZoom": True,
                    "maxClusterRadius": mcfg.get("cluster_radius_px", 20)}
    shown_jobs = sum(len(v) for v in job_groups.values())
    jobs_cluster = MarkerCluster(name=f"Offene Stellen ({shown_jobs})",
                                 options=cluster_opts, icon_create_function="jmClusterIcon('job')")
    companies_cluster = MarkerCluster(name=f"Passende Firmen ohne Ausschreibung ({len(open_companies)})",
                                      options=cluster_opts, icon_create_function="jmClusterIcon('company')")

    for (key, _, _), group in sorted(job_groups.items()):
        location = [group[0]["lat"], group[0]["lon"]]
        _marker(location, by_key[key], group, "job", colors, text, since, reference).add_to(jobs_cluster)
    for company in sorted(open_companies, key=lambda c: c["key"]):
        _marker([company["lat"], company["lon"]], company, [], "company", colors, text,
                since, reference).add_to(companies_cluster)

    # Ebenen werden im Panel geschaltet (kein LayerControl, das auf dem Handy das Panel überdeckt)
    jobs_cluster.add_to(fmap)
    companies_cluster.add_to(fmap)
    LocateControl(position="bottomright", strings={"title": "Mein Standort"}).add_to(fmap)

    shown_companies = [by_key[key] for key in job_companies] + open_companies
    category_counts = Counter(c for company in shown_companies for c in company["categories_display"])
    categories = [(name, category_counts[name]) for name in [*cfg.get("categories", {}), OTHER_CATEGORY]
                  if category_counts[name]]
    shown_job_list = [j for group in job_groups.values() for j in group]
    type_counts = Counter(job_type(j) for j in shown_job_list)
    hour_counts = Counter(h for j in shown_job_list for h in (j.get("hours") or []))

    methods = meta.get("score_methods") or {}
    scoring_note = ("Claude API" if methods.get("claude") else "Stichwort-Score") + (
        " (teils Stichwörter)" if methods.get("claude") and methods.get("stichwörter") else "")
    FilterPanel(
        jobs_cluster, companies_cluster,
        title=mcfg.get("title", "Jobkarte"),
        heading=mcfg.get("title", "Jobkarte"),
        updated=_fmt_date(updated),
        region_name=region["name"],
        radius_km=region["radius_km"],
        repo_url=mcfg.get("repo_url", ""),
        scoring_note=scoring_note,
        stats=(f"{shown_jobs} Stellen bei {len(job_companies)} Arbeitgebern · "
               f"{len(open_companies)} passende Firmen ohne Ausschreibung"),
        categories=categories,
        job_types=[(name, type_counts[name]) for name in JOB_TYPE_NAMES if type_counts[name]],
        hours=[(name, hour_counts[name]) for name in ("Vollzeit", "Teilzeit") if hour_counts[name]],
        homeoffice_count=sum(1 for j in shown_job_list if j.get("homeoffice")),
        n_jobs=shown_jobs,
        n_companies=len(open_companies),
    ).add_to(fmap)
    return fmap


def build_site(cfg: dict, out_dir: Path, data_dir: Path = DATA_DIR) -> Path:
    companies = read_json(data_dir / "companies.json", [])
    jobs = read_json(data_dir / "jobs.json", [])
    meta = read_json(data_dir / "meta.json", {})
    if not companies:
        raise SystemExit("data/companies.json fehlt oder ist leer, zuerst 'python -m jobmap update' ausführen")

    out_dir.mkdir(parents=True, exist_ok=True)
    fmap = build_map(cfg, companies, jobs, meta)
    index = out_dir / "index.html"
    fmap.save(str(index))
    (out_dir / "data").mkdir(exist_ok=True)
    for name in PUBLISHED_DATA:
        if (data_dir / name).exists():
            shutil.copy2(data_dir / name, out_dir / "data" / name)
    (out_dir / ".nojekyll").touch()
    log.info("Karte geschrieben: %s (%.0f kB)", index, index.stat().st_size / 1024)
    return index
