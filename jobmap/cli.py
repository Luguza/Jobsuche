"""Kommandozeile: python -m jobmap update | build."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from jobmap.config import ROOT, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jobmap", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="ausführliche Log-Ausgabe")
    sub = parser.add_subparsers(dest="command", required=True)

    update = sub.add_parser("update", help="Quellen abfragen, bewerten und data/*.json aktualisieren")
    update.add_argument("--no-llm", action="store_true", help="nur Stichwort-Bewertung, keine Claude API")
    update.add_argument("--no-websites", action="store_true", help="keine Firmen-Startseiten abrufen")

    build = sub.add_parser("build", help="statische Karte aus data/*.json bauen")
    build.add_argument("--out", type=Path, default=ROOT / "site", help="Ausgabeverzeichnis (Standard: site/)")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    # Wiederholungsversuche bei toten Firmen-Websites sind erwartbar und würden das Log fluten.
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    for noisy in ("httpx", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = load_config()

    if args.command == "update":
        from jobmap.pipeline import run_update

        run_update(cfg, use_llm=not args.no_llm, fetch_websites=not args.no_websites)
    elif args.command == "build":
        from jobmap.sitebuild import build_site

        build_site(cfg, args.out)
    return 0
