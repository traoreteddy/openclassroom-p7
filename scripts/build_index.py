"""Pipeline complet d'indexation : collecte -> nettoyage -> chunking -> embeddings -> FAISS.

Usage : python scripts/build_index.py
"""

from puls_events_rag.ingestion.open_agenda import fetch_events
from puls_events_rag.ingestion.preprocessing import chunk_documents, clean_events
from puls_events_rag.vectorstore.faiss_store import build_index


def main() -> None:
    raw_events = fetch_events()
    documents = clean_events(raw_events)
    chunks = chunk_documents(documents)
    build_index(chunks)
    print(f"Index construit : {len(chunks)} chunks à partir de {len(documents)} événements.")


if __name__ == "__main__":
    main()
