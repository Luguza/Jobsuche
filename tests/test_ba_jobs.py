import json
from pathlib import Path

from jobmap.sources.ba_jobs import parse_job, search_jobs

CENTER = (49.0069, 8.4037)
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ba_v6_search.json").read_text())


def test_parse_v6_item_picks_nearest_location():
    job = parse_job(FIXTURE["ergebnisliste"][0], CENTER)
    assert job["refnr"] == "10000-1111111111-S"
    assert job["company"] == "Beispiel Batterie GmbH"
    assert job["city"] == "Karlsruhe, Baden"  # nicht der Standort in München
    assert job["distance_km"] < 5
    assert job["url"].endswith("/jobdetail/10000-1111111111-S")


def test_parse_legacy_schema():
    item = {"refnr": "1-2-S", "arbeitgeber": "Alt GmbH", "titel": "Data Scientist",
            "arbeitsort": {"ort": "Karlsruhe", "koordinaten": {"lat": 49.0, "lon": 8.4}}}
    job = parse_job(item, CENTER)
    assert job["company"] == "Alt GmbH" and job["lat"] == 49.0


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params)
        return FakeResponse(FIXTURE)


def test_search_dedupes_by_refnr_and_filters_titles(cfg):
    cfg["jobs"]["search_terms"] = ["Batterie", "Machine Learning"]
    cfg["jobs"]["request_delay_s"] = 0
    session = FakeSession()
    jobs = search_jobs(session, cfg)
    refs = [j["refnr"] for j in jobs]
    assert refs == sorted(set(refs))
    assert "10000-3333333333-S" not in refs  # "Elektriker" wird per Titelfilter verworfen
    assert jobs[0]["search_terms"] == ["Batterie", "Machine Learning"]
    assert session.calls[0]["angebotsart"] == "1;34"
    assert session.calls[0]["zeitarbeit"] == "false"


def test_title_filter_ignores_company_name_and_generic_titles(cfg):
    import re

    from jobmap.sources.ba_jobs import is_relevant
    from jobmap.textutil import KeywordMatcher

    matcher = KeywordMatcher(cfg["scoring"]["keywords"])
    exclude = [re.compile(p, re.I) for p in cfg["jobs"]["exclude_title_patterns"]]

    def relevant(title, company="Firma GmbH"):
        return is_relevant({"title": title, "company": company}, cfg, matcher, exclude)

    assert relevant("Masterarbeit: Entwicklung eines ML Roaming Assistants")
    assert relevant("Data Scientist Logistics Network Simulation")
    assert not relevant("NTT DATA Deutschland SE: Deal Maker (w/m/x)", "NTT DATA Deutschland SE")
    assert not relevant("Steuerfachangestellte/r (m/w/d)")
    assert not relevant("Vertriebsmitarbeiter (m/w/d) im Bereich Photovoltaik")
