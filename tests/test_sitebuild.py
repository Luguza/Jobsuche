from jobmap.sitebuild import build_site
from jobmap.config import write_json


def test_build_site_renders_both_layers(cfg, tmp_path):
    data = tmp_path / "data"
    write_json(data / "companies.json", [
        {"key": "a", "name": "Akku <Sim> GmbH", "lat": 49.01, "lon": 8.4, "score": 9, "reason": "Passt",
         "score_method": "claude", "job_refs": ["1"], "first_seen": "2026-09-20", "sources": ["ba"]},
        {"key": "b", "name": "Klima Institut", "lat": 49.05, "lon": 8.5, "score": 7, "reason": "Forschung",
         "score_method": "stichwörter", "website": "https://klima.example", "sources": ["osm"],
         "refs": {"osm": ["node/1"]}},
        {"key": "c", "name": "Unpassend GmbH", "lat": 49.0, "lon": 8.3, "score": 2, "reason": "-",
         "score_method": "stichwörter", "sources": ["osm"]},
    ])
    write_json(data / "jobs.json", [
        {"refnr": "1", "title": "ML Engineer Batterie", "company": "Akku Sim GmbH", "company_key": "a",
         "lat": 49.01, "lon": 8.4, "city": "Karlsruhe", "published": "2026-09-20",
         "url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/1", "first_seen": "2026-09-20"},
    ])
    write_json(data / "meta.json", {"updated": "2026-09-24T06:00:00+00:00", "score_methods": {"claude": 1}})

    index = build_site(cfg, tmp_path / "site", data_dir=data)
    page = index.read_text()
    assert "Stand: 24.09.2026" in page
    # "Unpassend" liegt unter der Schwelle für Firmen ohne Ausschreibung
    assert "1 Stellen bei 1 Arbeitgebern · 1 passende Firmen ohne Ausschreibung" in page
    # Filter: Branchen per Stichwort, Anstellungsart aus dem Titel
    assert 'value="Batterien &amp; Speicher"' in page
    assert 'value="Forschung &amp; Hochschule"' in page
    assert 'value="Festanstellung"' in page
    assert "Akku &lt;Sim&gt; GmbH" in page and "Akku <Sim> GmbH" not in page
    assert "Unpassend GmbH" not in page
    assert (tmp_path / "site" / "data" / "companies.json").exists()


def test_first_run_is_never_marked_new():
    from datetime import date

    from jobmap.sitebuild import new_since

    assert new_since({"updated": "2026-09-24T06:00:00+00:00", "baseline": "2026-09-24"}) == date(2026, 9, 25)
    assert new_since({"updated": "2026-10-20T06:00:00+00:00", "baseline": "2026-09-24"}) == date(2026, 10, 13)


def test_salary_units():
    from jobmap.sitebuild import _salary

    assert _salary({"salary_from": 20.0, "salary_to": 21.0}) == "20–21 €/Std."
    assert _salary({"salary_from": 3500, "salary_to": 4200}) == "3.500–4.200 €/Monat"
    assert _salary({"salary_from": 55000.0, "salary_to": 70000.0}) == "55–70 T€/Jahr"
    assert _salary({"salary_from": 60000}) == "ab 60 T€/Jahr"
    assert _salary({}) is None
