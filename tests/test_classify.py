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
