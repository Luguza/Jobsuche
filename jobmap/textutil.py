"""Namensnormalisierung, Entfernungen und Stichwort-Suche."""

from __future__ import annotations

import re
import unicodedata

from geopy.distance import geodesic

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

# Rechtsformen und Füllwörter, die beim Abgleich von Firmennamen ignoriert werden.
_LEGAL_TOKENS = {
    "gmbh", "mbh", "ag", "se", "kg", "kgaa", "ohg", "gbr", "ug", "haftungsbeschraenkt",
    "ev", "eg", "co", "cokg", "inc", "ltd", "llc", "sa", "sarl", "sas", "bv", "nv",
    "plc", "corp", "corporation", "gesellschaft", "mit", "beschraenkter", "haftung",
    "und", "and", "the", "group", "gruppe", "holding",
}


def normalize_name(name: str) -> str:
    """'dm-drogerie markt GmbH + Co.KG' -> 'dm drogerie markt'."""
    text = unicodedata.normalize("NFKC", name or "").lower().translate(_UMLAUTS)
    text = re.sub(r"\be\.\s*v\b\.?", " ", text)  # "e.V." (aber nicht "E.ON")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    tokens = re.sub(r"[^a-z0-9]+", " ", text).split()
    kept = [t for t in tokens if t not in _LEGAL_TOKENS]
    return " ".join(kept or tokens)


def company_key(name: str) -> str:
    return normalize_name(name).replace(" ", "-")


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return geodesic((lat1, lon1), (lat2, lon2)).km


class KeywordMatcher:
    """Gewichtete reguläre Ausdrücke aus config.yaml (scoring.keywords)."""

    def __init__(self, keywords: dict):
        self.methods = [(re.compile(p, re.I), w) for p, w in keywords.get("methods", {}).items()]
        self.sectors = [(re.compile(p, re.I), w) for p, w in keywords.get("sectors", {}).items()]
        self.negative = [re.compile(p, re.I) for p in keywords.get("negative", [])]

    @staticmethod
    def _word(text: str, match: re.Match) -> str:
        """Treffer auf das ganze Wort erweitern ("Batter" -> "Batteriespeicher")."""
        before = re.search(r"\w*$", text[:match.start()]).group(0)
        after = re.match(r"\w*", text[match.end():]).group(0)
        return (before + match.group(0) + after).strip(" .")

    def _hits(self, patterns, text: str) -> tuple[int, list[str]]:
        total, found = 0, []
        for pattern, weight in patterns:
            match = pattern.search(text)
            if match:
                total += weight
                found.append(self._word(text, match))
        return total, found

    def score(self, text: str) -> tuple[int, str]:
        """Stichwort-Score 0-10 plus kurze Begründung."""
        m_score, m_found = self._hits(self.methods, text)
        s_score, s_found = self._hits(self.sectors, text)
        neg_found = [self._word(text, m) for m in (p.search(text) for p in self.negative) if m]
        score = min(m_score, 5) + min(s_score, 5)
        if neg_found:
            score -= 4
        score = max(0, min(10, score))
        parts = []
        if m_found:
            parts.append("Methodik: " + ", ".join(dict.fromkeys(m_found)))
        if s_found:
            parts.append("Sektor: " + ", ".join(dict.fromkeys(s_found)))
        if neg_found:
            parts.append("Abzug: " + ", ".join(dict.fromkeys(neg_found)))
        reason = "; ".join(parts) if parts else "Keine passenden Stichwörter gefunden"
        return score, f"{reason}."
