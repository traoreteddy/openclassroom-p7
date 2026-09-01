"""Reconstruction complète, du vide à l'index vectoriel.

Purge les données locales puis rejoue toute la chaîne :
purge -> collecte -> nettoyage -> chunking -> contrôle de cohérence -> vectorisation.

La vectorisation n'est lancée que si le contrôle de cohérence passe : inutile de
payer des appels d'embedding sur un corpus incohérent.

Usage :
    python scripts/rebuild_all.py                      # demande confirmation
    python scripts/rebuild_all.py --yes                # sans confirmation
    python scripts/rebuild_all.py --yes --cities Paris Lyon --max-events 3000
    python scripts/rebuild_all.py --yes --keep-raw     # repart du dernier brut collecté

Seul `data/` est purgé. Le fichier `.env` et le code ne sont jamais touchés.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

from puls_events_rag.config import (
    INDEX_DIR,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    settings,
)
from puls_events_rag.ingestion import open_agenda
from puls_events_rag.ingestion.open_agenda import fetch_events, save_raw_events
from puls_events_rag.ingestion.preprocessing import chunk_documents, clean_events
from puls_events_rag.vectorstore.faiss_store import build_index

logger = logging.getLogger("rebuild")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", "-y", action="store_true", help="Ne pas demander confirmation")
    parser.add_argument("--keep-raw", action="store_true",
                        help="Conserver data/raw/ et repartir du dernier brut collecté")
    parser.add_argument("--cities", nargs="+", default=settings.cities)
    parser.add_argument("--history-days", type=int, default=settings.history_days)
    parser.add_argument("--period-days", type=int, default=settings.period_days)
    parser.add_argument("--event-types", nargs="*", default=settings.event_types)
    parser.add_argument("--max-events", type=int, default=settings.max_events)
    return parser.parse_args()


def purger(repertoires: list[Path]) -> int:
    """Vide les répertoires en conservant les .gitkeep qui structurent le dépôt."""
    supprimes = 0
    for repertoire in repertoires:
        if not repertoire.exists():
            continue
        for fichier in repertoire.iterdir():
            if fichier.name == ".gitkeep":
                continue
            fichier.unlink()
            supprimes += 1
        repertoire.mkdir(parents=True, exist_ok=True)
    return supprimes


def etape(numero: int, total: int, titre: str) -> None:
    print(f"\n[{numero}/{total}] {titre}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    a_purger = [PROCESSED_DATA_DIR, INDEX_DIR]
    if not args.keep_raw:
        a_purger.insert(0, RAW_DATA_DIR)

    print("Reconstruction complète du jeu de données et de l'index.")
    print(f"  répertoires purgés : {', '.join(str(d) for d in a_purger)}")
    print(f"  périmètre          : {', '.join(args.cities)} | "
          f"historique {args.history_days} j + à venir {args.period_days} j | "
          f"types : {', '.join(args.event_types) if args.event_types else 'tous'} | "
          f"plafond {args.max_events}")
    print(f"  embeddings         : {settings.embedding_provider}")

    if not args.yes:
        reponse = input("\nConfirmer la suppression et la reconstruction ? [o/N] ").strip().lower()
        if reponse not in ("o", "oui", "y", "yes"):
            print("Abandon, rien n'a été supprimé.")
            return 1

    total = 5
    etape(1, total, "Purge des données locales")
    print(f"  {purger(a_purger)} fichier(s) supprimé(s)")

    etape(2, total, "Collecte des événements")
    if args.keep_raw:
        bruts = [f for f in sorted(RAW_DATA_DIR.glob("events_*.json"))
                 if not f.name.endswith(".meta.json")]
        if not bruts:
            print("  Aucun brut à réutiliser : relancez sans --keep-raw.")
            return 1
        raw_events = json.loads(bruts[-1].read_text(encoding="utf-8"))
        print(f"  {len(raw_events)} événements relus depuis {bruts[-1].name}")
    else:
        raw_events = fetch_events(
            cities=args.cities,
            history_days=args.history_days,
            period_days=args.period_days,
            event_types=args.event_types,
            max_events=args.max_events,
        )
        save_raw_events(raw_events, params=open_agenda.DERNIER_PERIMETRE)

    etape(3, total, "Nettoyage et chunking")
    documents = clean_events(raw_events)
    chunks = chunk_documents(documents)
    if not chunks:
        print("  Aucun chunk produit : élargissez le périmètre de collecte.")
        return 1
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (PROCESSED_DATA_DIR / "documents.json").write_text(
        json.dumps(documents, ensure_ascii=False, indent=2), encoding="utf-8")
    (PROCESSED_DATA_DIR / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    etape(4, total, "Contrôle de cohérence")
    # Sous-processus plutôt qu'import : les scripts restent indépendants les uns
    # des autres, et le code de sortie du contrôle remonte tel quel.
    controle = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "check_dataset.py"), "--strict"],
        check=False,
    )
    if controle.returncode != 0:
        print("\nReconstruction interrompue : le jeu de données est incohérent.")
        print("L'index n'a pas été construit, aucun appel d'embedding n'a été facturé.")
        return 1

    etape(5, total, "Vectorisation et index FAISS")
    index_dir = build_index(chunks)

    print(f"\nReconstruction terminée."
          f"\n  {len(raw_events)} événements bruts"
          f"\n  {len(documents)} documents nettoyés"
          f"\n  {len(chunks)} chunks vectorisés"
          f"\n  index : {index_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
