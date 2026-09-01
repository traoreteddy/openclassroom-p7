"""Pipeline complet d'indexation : collecte -> nettoyage -> chunking -> embeddings -> FAISS.

Usage :
    python scripts/build_index.py
    python scripts/build_index.py --cities Paris Lyon --history-days 365 --period-days 90
    python scripts/build_index.py --from-chunks     # réutilise data/processed/chunks.json
"""

from __future__ import annotations

import argparse
import json
import logging

from puls_events_rag.config import PROCESSED_DATA_DIR, settings
from puls_events_rag.ingestion import open_agenda
from puls_events_rag.ingestion.open_agenda import fetch_events, save_raw_events
from puls_events_rag.ingestion.preprocessing import chunk_documents, clean_events
from puls_events_rag.vectorstore.faiss_store import build_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cities", nargs="+", default=settings.cities)
    parser.add_argument("--history-days", type=int, default=settings.history_days,
                        help="Profondeur d'historique en jours (défaut : %(default)s)")
    parser.add_argument("--period-days", type=int, default=settings.period_days,
                        help="Fenêtre à venir en jours (défaut : %(default)s)")
    parser.add_argument("--event-types", nargs="*", default=settings.event_types,
                        help="Types d'événement recherchés (défaut : tous)")
    parser.add_argument("--max-events", type=int, default=settings.max_events)
    parser.add_argument("--from-chunks", action="store_true",
                        help="Repart de data/processed/chunks.json sans rappeler l'API")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    chunks_path = PROCESSED_DATA_DIR / "chunks.json"
    documents_path = PROCESSED_DATA_DIR / "documents.json"

    if args.from_chunks:
        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        print(f"{len(chunks)} chunks relus depuis {chunks_path}")
    else:
        raw_events = fetch_events(
            cities=args.cities,
            history_days=args.history_days,
            period_days=args.period_days,
            event_types=args.event_types,
            max_events=args.max_events,
        )
        save_raw_events(raw_events, params=open_agenda.DERNIER_PERIMETRE)
        documents = clean_events(raw_events)
        chunks = chunk_documents(documents)
        # Les deux artefacts sont réécrits ensemble : un documents.json laissé
        # en arrière décrirait un autre corpus que celui réellement indexé.
        PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        documents_path.write_text(
            json.dumps(documents, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    index_dir = build_index(chunks)
    print(f"\nIndex construit : {len(chunks)} chunks vectorisés -> {index_dir}")


if __name__ == "__main__":
    main()
