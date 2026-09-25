"""Relevanz-Bewertung (0-10) per Claude API oder, ohne API-Key, per Stichwort-Score.

Claude-Bewertungen werden in data/score_cache.json gespeichert, damit nur neue Firmen
bewertet werden. Stichwort-Scores sind billig und werden bei jedem Lauf neu berechnet.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date

from jobmap.classify import OTHER_CATEGORY
from jobmap.textutil import KeywordMatcher

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Du bewertest potenzielle Arbeitgeber für eine konkrete Person.

Profil der Person:
{profile}

Bewerte jede Organisation mit einer ganzen Zahl von 0 bis 10 danach, wie gut sie als Arbeitgeber zu diesem Profil passt:
- 9-10: Machine Learning, Data Science oder Simulation gehören zum Kern UND die Organisation arbeitet in einem Wunschsektor (erneuerbare Energien, Batterien, Wasserstoff, Stromnetze, Klimaschutz, Klimafolgenanpassung) oder entwickelt Materialien mit datengetriebenen Methoden.
- 7-8: Eines von beidem ist klar ausgeprägt, das andere plausibel (z. B. Energieversorger mit Data-Science-Team, Materialforschungsinstitut, KI-Firma mit Energiekunden).
- 4-6: Technisch oder forschungsnah mit möglichen Berührungspunkten, aber weder ML noch Wunschsektor klar erkennbar.
- 1-3: Kaum Bezug (z. B. Handwerk, Handel, allgemeine Beratung, Verwaltung).
- 0: Kein Bezug oder kein echter Arbeitgeber (Verein, Privatperson, geschlossene Firma).

Stütze dich auf die gelieferten Angaben und auf gesichertes Allgemeinwissen über bekannte Organisationen; erfinde keine Details. Sind die Angaben dünn, bewerte vorsichtig und sag das.
Die Begründung besteht aus ein bis zwei kurzen, konkreten Sätzen auf Deutsch: was passt, was fehlt.
Ordne jede Organisation außerdem einer bis drei passenden Branchen aus dieser Liste zu: {categories}.
Gib für jede übergebene id genau ein Ergebnis zurück."""


def output_schema(categories: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "score": {"type": "integer"},
                        "reason": {"type": "string"},
                        "categories": {"type": "array", "items": {"type": "string", "enum": categories}},
                    },
                    "required": ["id", "score", "reason", "categories"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def company_text(company: dict) -> str:
    """Alle Angaben zu einer Firma als ein Text für Stichwortsuche und Claude."""
    parts = [
        company["name"],
        company.get("industry"),
        company.get("description"),
        company.get("meta_title"),
        company.get("meta_description"),
        company.get("notes"),
        " ".join(company.get("tags") or []),
        " | ".join(company.get("job_titles") or []),
    ]
    return " \n".join(p for p in parts if p)


def llm_payload(company: dict) -> dict:
    payload = {
        "id": company["key"],
        "name": company["name"],
        "ort": company.get("city"),
        "art": ", ".join(company.get("tags") or []) or None,
        "branche": company.get("industry"),
        "beschreibung": company.get("description"),
        "website": company.get("website"),
        "website_titel": company.get("meta_title"),
        "website_beschreibung": company.get("meta_description"),
        "notizen": company.get("notes"),
        "aktuelle_stellen": (company.get("job_titles") or [])[:8] or None,
    }
    return {k: v for k, v in payload.items() if v}


class ClaudeScorer:
    def __init__(self, cfg: dict, client=None):
        import anthropic

        self.anthropic = anthropic
        self.llm_cfg = cfg["scoring"]["llm"]
        self.client = client or anthropic.Anthropic()
        self.categories = list(cfg.get("categories", {})) + [OTHER_CATEGORY]
        self.system = SYSTEM_PROMPT.format(profile=cfg["scoring"]["profile"].strip(),
                                           categories=", ".join(self.categories))

    def _request(self, batch: list[dict]):
        content = "Bewerte die folgenden Organisationen:\n" + "\n".join(
            json.dumps(llm_payload(c), ensure_ascii=False) for c in batch)
        kwargs = dict(
            model=self.llm_cfg["model"],
            max_tokens=16000,
            system=self.system,
            messages=[{"role": "user", "content": content}],
            output_config={
                "effort": self.llm_cfg.get("effort", "low"),
                "format": {"type": "json_schema", "schema": output_schema(self.categories)},
            },
        )
        fallbacks = self.llm_cfg.get("fallbacks")
        if fallbacks:
            # Serverseitiger Fallback, falls das Modell eine Anfrage ablehnt.
            return self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks=fallbacks, **kwargs)
        return self.client.messages.create(**kwargs)

    def score_batch(self, batch: list[dict]) -> dict[str, dict]:
        """Gibt {key: {score, reason}} zurück; bei Fehlern ein leeres Dict."""
        try:
            response = self._request(batch)
        except self.anthropic.APIStatusError as exc:
            log.warning("Claude-API-Fehler (%s): %s", exc.status_code, exc.message)
            return {}
        except self.anthropic.APIConnectionError as exc:
            log.warning("Claude-API nicht erreichbar: %s", exc)
            return {}
        if response.stop_reason in ("refusal", "max_tokens"):
            log.warning("Claude-Antwort unbrauchbar (stop_reason=%s)", response.stop_reason)
            return {}
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            results = json.loads(text)["results"]
        except (ValueError, KeyError, TypeError):
            log.warning("Claude-Antwort ist kein gültiges JSON")
            return {}
        wanted = {c["key"] for c in batch}
        return {
            r["id"]: {
                "score": max(0, min(10, int(r["score"]))),
                "reason": r["reason"].strip(),
                "categories": [c for c in r.get("categories", []) if c in self.categories],
            }
            for r in results if r.get("id") in wanted
        }


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def score_companies(companies: list[dict], cfg: dict, cache: dict, use_llm: bool = True,
                    client=None) -> dict:
    """Setzt score/reason/score_method an jeder Firma. Gibt den aktualisierten Cache zurück."""
    matcher = KeywordMatcher(cfg["scoring"]["keywords"])
    llm_cfg = cfg["scoring"]["llm"]
    today = date.today().isoformat()

    for company in companies:
        if company.get("manual_score") is not None:
            company.update(score=int(company["manual_score"]), score_method="manuell",
                           reason=company.get("manual_reason") or "Manuell festgelegt (Seed-Liste).")
            continue
        cached = cache.get(company["key"])
        if cached and cached.get("model"):
            company.update(score=cached["score"], reason=cached["reason"], score_method="claude",
                           categories=cached.get("categories") or None)
            continue
        score, reason = matcher.score(company_text(company))
        company.update(score=score, reason=reason, score_method="stichwörter")

    if not (use_llm and (client is not None or llm_available())):
        log.info("Kein ANTHROPIC_API_KEY gesetzt: Stichwort-Bewertung wird verwendet")
        return cache

    todo = [c for c in companies if c["score_method"] == "stichwörter"]
    # Zuerst Firmen mit Stellen, dann nach Stichwort-Score, damit die Kostenbremse das Wichtigste bewertet.
    todo.sort(key=lambda c: (not c.get("job_refs"), -c["score"], c["key"]))
    limit = llm_cfg.get("max_new_per_run", 500)
    if len(todo) > limit:
        log.warning("%d Firmen unbewertet, bewerte in diesem Lauf nur %d", len(todo), limit)
        todo = todo[:limit]
    if not todo:
        return cache

    scorer = ClaudeScorer(cfg, client=client)
    size = llm_cfg.get("batch_size", 20)
    done = 0
    for start in range(0, len(todo), size):
        batch = todo[start:start + size]
        results = scorer.score_batch(batch)
        for company in batch:
            result = results.get(company["key"])
            if not result:
                continue  # Stichwort-Score bleibt, nächster Lauf versucht es erneut
            cache[company["key"]] = {**result, "model": llm_cfg["model"], "scored": today,
                                     "name": company["name"]}
            company.update(score=result["score"], reason=result["reason"], score_method="claude",
                           categories=result["categories"] or None)
            done += 1
        log.info("Claude-Bewertung: %d/%d", min(start + size, len(todo)), len(todo))
    log.info("Claude hat %d Firmen neu bewertet", done)
    return cache
