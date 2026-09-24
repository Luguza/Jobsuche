from jobmap.merge import CompanyIndex, attach_jobs, from_osm, from_seed, from_wikidata


def osm(name, lat=49.0, lon=8.4, **tags):
    return {"id": f"node/{abs(hash(name))}", "name": name, "lat": lat, "lon": lon, "tags": tags}


def test_sources_merge_by_normalized_name():
    index = CompanyIndex()
    index.add(from_osm(osm("Vulcan Energie Ressourcen GmbH", office="company", website="vulcan.example")))
    index.add(from_wikidata({"id": "Q1", "name": "Vulcan Energie Ressourcen", "lat": 49.1, "lon": 8.5,
                             "description": "Lithium aus Geothermie", "industries": "Bergbau",
                             "approximate_location": True}))
    assert len(index.by_key) == 1
    company = index.by_key["vulcan-energie-ressourcen"]
    assert company["sources"] == ["osm", "wikidata"]
    assert company["lat"] == 49.0  # OSM-Koordinate schlägt den Wikidata-Hauptsitz
    assert company["description"] == "Lithium aus Geothermie"
    assert company["tags"] == ["Firma"]


def test_seed_overrides_website_and_score():
    index = CompanyIndex()
    index.add(from_osm(osm("Beispiel GmbH", website="http://alt.example")))
    index.add(from_seed({"name": "Beispiel GmbH", "website": "https://neu.example", "score": 9,
                         "reason": "Top", "tags": ["Batterie"]}, 49.01, 8.41))
    company = index.by_key["beispiel"]
    assert company["website"] == "https://neu.example"
    assert company["manual_score"] == 9
    assert company["lat"] == 49.01


def test_jobs_attach_exact_fuzzy_and_new():
    index = CompanyIndex()
    index.add(from_osm(osm("dm-drogerie markt GmbH + Co. KG", lat=49.003, lon=8.37)))
    index.add(from_osm(osm("Stadtwerke Karlsruhe GmbH", lat=49.02, lon=8.36)))
    jobs = [
        {"refnr": "1", "company": "dm-drogerie markt GmbH + Co.KG", "title": "Data Scientist", "lat": 49.0, "lon": 8.4},
        {"refnr": "2", "company": "Stadtwerke Karlsruhe", "title": "Data Engineer", "lat": 49.0, "lon": 8.4},
        {"refnr": "3", "company": "Neue Firma AG", "title": "ML Engineer", "lat": 49.05, "lon": 8.45},
    ]
    attach_jobs(index, jobs)
    assert index.by_key["dm-drogerie-markt"]["job_refs"] == ["1"]
    assert index.by_key["stadtwerke-karlsruhe"]["job_titles"] == ["Data Engineer"]
    assert index.by_key["neue-firma"]["sources"] == ["ba"]
    assert jobs[2]["company_key"] == "neue-firma"
