from jobmap.textutil import KeywordMatcher, company_key, normalize_name


def test_normalize_merges_legal_form_variants():
    assert normalize_name("dm-drogerie markt GmbH + Co.KG") == normalize_name("dm-drogerie markt GmbH + Co. KG")
    assert company_key("Innolith Battery Tech Company GmbH") == "innolith-battery-tech-company"


def test_normalize_keeps_names_that_look_like_legal_forms():
    assert normalize_name("E.ON Energie Deutschland GmbH") == "e on energie deutschland"
    assert normalize_name("Förderverein Klimaschutz e.V.") == "foerderverein klimaschutz"


def test_keyword_score_combines_method_and_sector(cfg):
    matcher = KeywordMatcher(cfg["scoring"]["keywords"])
    high, reason = matcher.score("Machine Learning für Batteriematerialien und Wasserstoff-Elektrolyse")
    low, _ = matcher.score("Steuerberatungskanzlei Müller")
    assert high >= 8
    assert "Batter" in reason or "batter" in reason
    assert low == 0


def test_short_keywords_need_word_boundaries(cfg):
    matcher = KeywordMatcher(cfg["scoring"]["keywords"])
    assert matcher.score("Kita Sonnenschein")[0] == 0
    assert matcher.score("KI-gestützte Netzplanung für Verteilnetzbetreiber")[0] >= 4
