"""Einordnung für die Kartenfilter: Branchen (Firmen) und Anstellungsart (Stellen)."""

from __future__ import annotations

import re

# Reihenfolge = Vorrang: "Masterarbeit im Werkstudenten-Team" ist eine Abschlussarbeit.
JOB_TYPES = (
    ("Abschlussarbeit", re.compile(r"masterarbeit|bachelorarbeit|abschlussarbeit|diplomarbeit|thesis", re.I)),
    ("Promotion/Postdoc", re.compile(r"\bpromotion\b|doktorand|\bph\.?\s?d\b|doctoral|postdoc", re.I)),
    ("Werkstudent", re.compile(r"werkstudent|working student|studentische|student assistant|\bhiwi\b", re.I)),
    ("Praktikum", re.compile(r"praktik|praxissemester|internship|\bintern\b", re.I)),
    ("Trainee", re.compile(r"trainee", re.I)),
)
FULL_EMPLOYMENT = "Festanstellung"
JOB_TYPE_NAMES = tuple(name for name, _ in JOB_TYPES) + (FULL_EMPLOYMENT,)
OTHER_CATEGORY = "Sonstige"


def job_type(job: dict) -> str:
    """Anstellungsart aus Titel und Angebotsart der BA."""
    for name, pattern in JOB_TYPES:
        if pattern.search(job.get("title", "")):
            return name
    if job.get("offer_type") == "PRAKTIKUM_TRAINEE":
        return "Praktikum"
    return FULL_EMPLOYMENT


def keyword_categories(text: str, patterns: dict[str, str]) -> list[str]:
    """Branchen, deren Stichwort-Muster (config.yaml: categories) im Text vorkommen."""
    found = [name for name, pattern in patterns.items() if re.search(pattern, text, re.I)]
    return found or [OTHER_CATEGORY]
