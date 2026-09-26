from jobmap.classify import OTHER_CATEGORY, job_type, keyword_categories


def test_job_type_prefers_thesis_over_student_job():
    assert job_type({"title": "Masterarbeit: KI-basierte Regelung", "offer_type": "PRAKTIKUM_TRAINEE"}) == "Abschlussarbeit"
    assert job_type({"title": "Werkstudent*in Data Science", "offer_type": "ARBEIT"}) == "Werkstudent"
    assert job_type({"title": "Promotion – Physische KI", "offer_type": "ARBEIT"}) == "Promotion/Postdoc"
    assert job_type({"title": "Working Student NLP", "offer_type": "PRAKTIKUM_TRAINEE"}) == "Werkstudent"
    assert job_type({"title": "Data Scientist (m/w/d)", "offer_type": "PRAKTIKUM_TRAINEE"}) == "Praktikum"
    assert job_type({"title": "Data Scientist (m/w/d)", "offer_type": "ARBEIT"}) == "Festanstellung"


def test_keyword_categories(cfg):
    patterns = cfg["categories"]
    cats = keyword_categories("Fraunhofer ICT: Batterien, Brennstoffzellen, Wasserstoff", patterns)
    assert {"Batterien & Speicher", "Wasserstoff & Brennstoffzellen", "Forschung & Hochschule"} <= set(cats)
    assert keyword_categories("Bäckerei Schmidt", patterns) == [OTHER_CATEGORY]


def test_job_categories_use_title_not_other_jobs(cfg):
    from jobmap.classify import job_categories

    patterns = cfg["categories"]
    # Firma ohne Branchen-Treffer: die Stelle bekommt nur, was ihr eigener Titel nennt
    assert job_categories("Werkstudent Controlling", [OTHER_CATEGORY], patterns) == [OTHER_CATEGORY]
    assert job_categories("Data Scientist Batteriezellen", [OTHER_CATEGORY], patterns) == [
        "KI & Data Science", "Batterien & Speicher"]
    # Branchen der Firma gelten für alle ihre Stellen
    assert "Netze & Energieversorgung" in job_categories("Controller", ["Netze & Energieversorgung"], patterns)
