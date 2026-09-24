"""Manuell gepflegte Seed-Liste (data/seed_companies.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml


def load_seed(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    entries = []
    for i, entry in enumerate(data.get("companies") or []):
        if not isinstance(entry, dict) or not entry.get("name"):
            raise ValueError(f"{path.name}: Eintrag {i + 1} braucht mindestens ein Feld 'name'")
        tags = entry.get("tags") or []
        entries.append({
            "name": str(entry["name"]).strip(),
            "address": entry.get("address"),
            "city": entry.get("city"),
            "lat": entry.get("lat"),
            "lon": entry.get("lon"),
            "website": entry.get("website"),
            "notes": entry.get("notes"),
            "tags": [str(t) for t in (tags if isinstance(tags, list) else [tags])],
            "score": entry.get("score"),
            "reason": entry.get("reason"),
        })
    return entries
