from jobmap.sources.websites import extract_meta, normalize_url


def test_extract_meta_prefers_description():
    html = """<html><head><title> Beispiel  GmbH | Batteriezellen </title>
    <meta property="og:description" content="OG-Text">
    <meta name="description" content="Wir entwickeln Batteriezellen mit KI."></head></html>"""
    assert extract_meta(html) == {"title": "Beispiel GmbH | Batteriezellen",
                                  "description": "Wir entwickeln Batteriezellen mit KI."}


def test_normalize_url():
    assert normalize_url("www.example.de;https://other.de") == "https://www.example.de/"
    assert normalize_url("http://example.de/de/start?x=1") == "http://example.de/de/start"
    assert normalize_url("") is None
