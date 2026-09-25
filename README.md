# Jobkarte Karlsruhe: ML, Materialien & Energiewende

[![Karte aktualisieren](https://github.com/Luguza/Jobsuche/actions/workflows/update-map.yml/badge.svg)](https://github.com/Luguza/Jobsuche/actions/workflows/update-map.yml)
[![Tests](https://github.com/Luguza/Jobsuche/actions/workflows/tests.yml/badge.svg)](https://github.com/Luguza/Jobsuche/actions/workflows/tests.yml)
· **[Zur Karte](https://luguza.github.io/Jobsuche/)**

Interaktive Karte des Arbeitsmarkts im Umkreis von 50 km um Karlsruhe für
**Machine Learning / Data Science**, **Materialwissenschaft & Simulation** und Sektoren mit
gesellschaftlichem Nutzen (**erneuerbare Energien, Batterien, Wasserstoff, Netze, Klimaschutz,
Klimafolgenanpassung**).

Die Karte zeigt zwei getrennt schaltbare Ebenen:

- **Offene Stellen** (Tropfen-Marker): Arbeitgeber mit aktuell passenden Stellen aus der
  Jobsuche der Bundesagentur für Arbeit, mit Links zu den Anzeigen.
- **Passende Firmen ohne Ausschreibung** (Kreis-Marker): Firmen und Forschungseinrichtungen
  ohne aktuelle Stelle, als Ziel für Initiativbewerbungen.

Farbe und Zahl im Marker sind die **Priorität (Relevanz-Score 0–10)**. Das Popup zeigt die
Begründung, die Branche, die passenden Stellen (mit Anstellungsart, Arbeitszeit, Befristung,
Homeoffice und, falls angegeben, Gehalt) und die Website.

Filter im Panel links (auf dem Handy über die Kopfzeile aufklappen):

- **Suche** nach Firmenname oder Stichwort, mit Trefferliste zum Antippen
- **Ebenen** „Offene Stellen“ und „Firmen ohne Ausschreibung“ ein- und ausblenden
- **Mindest-Priorität** (x/10) und **maximale Entfernung** von Karlsruhe
- **Branche**, z. B. KI & Data Science, Batterien & Speicher, Wasserstoff, Netze (mit
  `ANTHROPIC_API_KEY` ordnet Claude zu, sonst Stichwörter aus `config.yaml` → `categories`)
- nur für Stellen: **Anstellungsart** (Festanstellung, Werkstudent, Abschlussarbeit, Praktikum,
  Promotion/Postdoc, Trainee), **Arbeitszeit** (Vollzeit/Teilzeit), **Homeoffice** und
  **Veröffentlichungsdatum**
- **nur neue Einträge** der letzten Woche

Innerhalb einer Filtergruppe genügt ein Treffer (oder), verschiedene Gruppen gelten zusammen
(und). Im Popup einer Firma werden Stellen, die nicht zu den Filtern passen, ausgeblendet.

**Karte:** https://luguza.github.io/Jobsuche/

## Datenquellen

| Quelle | Inhalt | Lizenz / Nutzung |
|---|---|---|
| [Jobsuche-API der BA](https://github.com/bundesAPI/jobsuche-api) | Stellen zu den Suchbegriffen aus `config.yaml`, dedupliziert über die Referenznummer | Suche über `/pc/v6/jobs` (`/pc/v4/jobs` liefert seit 2026 HTTP 403), Details über `/pc/v4/jobdetails/{base64(refnr)}` |
| OpenStreetMap (Overpass API) | `office=company/research/it/engineer/energy_supplier`, `amenity=research_institute`, `man_made=works` | © OpenStreetMap-Mitwirkende, ODbL; eine Abfrage pro Lauf, mit Ausweich-Instanzen |
| Wikidata (SPARQL) | Unternehmen und Forschungseinrichtungen mit Standort oder Hauptsitz im Umkreis, inkl. Branche | CC0 |
| Firmen-Startseiten | nur `<title>` und Meta-Beschreibung als Kontext für die Bewertung | robots.txt wird pro Domain geprüft; ein Abruf pro Firma, 180 Tage gecacht |
| `data/seed_companies.yaml` | eigene Liste | manuell gepflegt |

Bewusst **nicht** automatisiert: GreenTech-BW-Atlas (Umwelttechnik BW), KLiB, H2BW und
KIT-Gründerschmiede, weil es dort keine API gibt, die Atlas-Suche per robots.txt gesperrt ist
oder keine maschinenlesbare Mitgliederliste existiert. Kostenpflichtige Dienste (North Data,
OpenCorporates) werden ebenfalls nicht genutzt. Interessante Einträge von dort am besten in die
Seed-Liste übernehmen.

## Ablauf

```
BA-Jobsuche ─┐
OSM ─────────┼─► zusammenführen (normalisierter Firmenname, unscharfer Abgleich für Stellen)
Wikidata ────┤        │
Seed-Liste ──┘        ▼
               Startseiten-Metadaten (robots.txt-geprüft, gecacht)
                      │
                      ▼
      Stufe 1: Stichwort-Filter (Methodik + Sektor, Abzüge für z. B. Kanzleien)
                      │   Firmen mit Stellen und Seed-Einträge kommen immer weiter
                      ▼
      Stufe 2: Relevanz-Score 0–10 + Begründung
               • mit ANTHROPIC_API_KEY: Claude (Ergebnisse in data/score_cache.json gecacht,
                 es werden nur neue Firmen bewertet)
               • ohne Key: Stichwort-Score
                      │
                      ▼
      data/*.json (versioniert) ─► folium/Leaflet-Karte ─► GitHub Pages
```

## Daten im Repository

| Datei | Inhalt |
|---|---|
| `data/jobs.json` | aktuelle Stellen (Referenznummer, Titel, Firma, Ort, Link, `first_seen`) |
| `data/companies.json` | bewertete Firmen (Score, Begründung, Quellen, Website, `first_seen`) |
| `data/history.json` | Protokoll je Lauf: neue und verschwundene Stellen und Firmen |
| `data/meta.json` | Stand, Zählwerte, Status der Quellen |
| `data/sources/*.json` | Rohdaten aus OSM und Wikidata (Rückfall, falls eine Quelle ausfällt) |
| `data/geocache.json` | Nominatim-Cache, jede Adresse wird nur einmal abgefragt |
| `data/website_cache.json` | Titel und Meta-Beschreibung der Startseiten |
| `data/score_cache.json` | Claude-Bewertungen |

Veränderungen über die Zeit: `data/history.json` lesen oder z. B.
`git log -p -- data/jobs.json`.

## Einrichtung auf GitHub

1. **Pages aktivieren:** *Settings → Pages → Build and deployment → Source: GitHub Actions*.
2. **Default-Branch:** Der Workflow läuft zeitgesteuert nur auf dem Default-Branch und darf
   standardmäßig nur von dort nach Pages deployen. Diesen Branch also als Default-Branch
   verwenden oder nach `main` mergen.
3. **Optional, Claude-Bewertung:** *Settings → Secrets and variables → Actions → New repository
   secret* mit dem Namen `ANTHROPIC_API_KEY`. Ohne Secret wird per Stichwort bewertet. Beim
   ersten Lauf mit Key werden alle Kandidaten einmal bewertet (bei einigen hundert Firmen
   grob 1–3 US-Dollar mit `claude-opus-5`), danach nur neue Firmen. Die Obergrenze pro Lauf
   steht in `config.yaml` unter `scoring.llm.max_new_per_run`.
4. **Erster Lauf:** *Actions → „Daten aktualisieren & Karte veröffentlichen“ → Run workflow*.

Danach läuft der Workflow jeden Montag früh. Er aktualisiert die Daten, committet sie und
veröffentlicht die Karte neu. Mit der Option „Nur die Karte neu bauen“ lassen sich z. B.
Änderungen an der Darstellung ohne neue Abfragen veröffentlichen.

## Lokal ausführen

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

python -m jobmap update            # Daten abfragen und bewerten (ANTHROPIC_API_KEY optional)
python -m jobmap update --no-llm   # nur Stichwort-Bewertung
python -m jobmap build             # Karte nach site/index.html bauen
python -m pytest                   # Tests
```

Der erste Lauf dauert länger (einige Minuten), weil die Startseiten einmalig abgerufen
werden. Weitere Läufe nutzen die Caches.

## Anpassen

- **Suchbegriffe, Umkreis, Stellenarten, Titel-Ausschlüsse:** `config.yaml` → `region`, `jobs`
- **Stichwörter und Gewichte für Stufe 1:** `config.yaml` → `scoring.keywords`
  (reguläre Ausdrücke)
- **Profil für die Claude-Bewertung und Modell:** `config.yaml` → `scoring.profile`, `scoring.llm`
- **Schwelle für Firmen ohne Stelle:** `config.yaml` → `map.min_score_companies`
- **Branchen für den Filter:** `config.yaml` → `categories`
- **Gruppieren naher Marker:** `config.yaml` → `map.cluster_radius_px` (kleiner = später gruppiert)
- **Eigene Firmen:** `data/seed_companies.yaml`, optional mit festem `score` und `reason`
- **Neu bewerten lassen:** Eintrag aus `data/score_cache.json` löschen (oder die ganze Datei)
