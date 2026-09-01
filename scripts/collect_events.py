"""Collecte des événements OpenAgenda et structuration pour la base vectorielle.

Enchaîne : collecte filtrée (ville + période) -> nettoyage -> chunking, puis
persiste chaque étape sur disque.

Usage :
    python scripts/collect_events.py
    python scripts/collect_events.py --cities Paris Lyon --period-days 60 --max-events 500
"""

from __future__ import annotations

import argparse
import json
import logging

from puls_events_rag.config import PROCESSED_DATA_DIR, settings
from puls_events_rag.ingestion import open_agenda
from puls_events_rag.ingestion.open_agenda import fetch_events, save_raw_events
from puls_events_rag.ingestion.preprocessing import chunk_documents, clean_events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cities", nargs="+", default=settings.cities,
                        help="Villes à collecter (défaut : %(default)s)")
    parser.add_argument("--history-days", type=int, default=settings.history_days,
                        help="Profondeur d'historique, en jours (défaut : %(default)s)")
    parser.add_argument("--period-days", type=int, default=settings.period_days,
                        help="Fenêtre à venir, en jours (défaut : %(default)s)")
    parser.add_argument("--event-types", nargs="*", default=settings.event_types,
                        help="Types d'événement recherchés (défaut : tous)")
    parser.add_argument("--max-events", type=int, default=settings.max_events,
                        help="Plafond d'événements collectés (défaut : %(default)s)")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    raw_events = fetch_events(
        cities=args.cities,
        history_days=args.history_days,
        period_days=args.period_days,
        event_types=args.event_types,
        max_events=args.max_events,
    )
    raw_path = save_raw_events(raw_events, params=open_agenda.DERNIER_PERIMETRE)

    documents = clean_events(raw_events)
    chunks = chunk_documents(documents)

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    documents_path = PROCESSED_DATA_DIR / "documents.json"
    chunks_path = PROCESSED_DATA_DIR / "chunks.json"
    documents_path.write_text(json.dumps(documents, ensure_ascii=False, indent=2), encoding="utf-8")
    chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"\n{len(raw_events)} événements bruts  -----> {raw_path}"
        f"\n{len(documents)} documents nettoyés   ---> {documents_path}"
        f"\n{len(chunks)} chunks prêts à vectoriser -> {chunks_path}"
    )


if __name__ == "__main__":
    main()
