"""Construction, persistance et chargement de la base vectorielle FAISS.

L'index est sauvegardé dans ``data/index/`` avec les métadonnées de chaque chunk
(titre, période, lieu, ville, URL de l'événement), afin que la chaîne RAG puisse
citer ses sources.

Les embeddings sont calculés par lots : l'API Mistral limite la taille des
requêtes, et un envoi lot par lot permet de suivre l'avancement sur plusieurs
milliers de chunks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import faiss
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from puls_events_rag.config import INDEX_DIR, settings
from puls_events_rag.vectorstore.embeddings import get_embedding_model

logger = logging.getLogger(__name__)

BATCH_SIZE = 64
METADATA_FILE = "index_meta.json"


def _nouvel_index(dimension: int) -> faiss.Index:
    """Crée l'index FAISS du type configuré.

    Les embeddings Mistral sont unitaires (norme mesurée à 1,0000) : la distance
    L2 et la similarité cosinus donnent alors le même classement, puisque
    ``||a-b||² = 2 - 2·cos(a,b)``. La métrique L2 est donc conservée.
    """
    if settings.faiss_index_type == "hnsw":
        index = faiss.IndexHNSWFlat(dimension, settings.hnsw_m)
        index.hnsw.efConstruction = settings.hnsw_ef_construction
        index.hnsw.efSearch = settings.hnsw_ef_search
        logger.info(
            "Index HNSW (M=%s, efConstruction=%s, efSearch=%s)",
            settings.hnsw_m, settings.hnsw_ef_construction, settings.hnsw_ef_search,
        )
        return index
    logger.info("Index Flat (recherche exhaustive, résultats exacts)")
    return faiss.IndexFlatL2(dimension)


def _to_documents(chunks: list[dict]) -> list[Document]:
    """Convertit les chunks du prétraitement en documents LangChain."""
    return [
        Document(page_content=chunk["text"], metadata={**chunk["metadata"], "id": chunk["id"]})
        for chunk in chunks
    ]


def build_index(chunks: list[dict], index_dir: Path | None = None) -> Path:
    """Construit l'index FAISS à partir des chunks et le persiste sur disque.

    Args:
        chunks: chunks issus de :func:`chunk_documents`.
        index_dir: répertoire de destination (défaut : ``data/index/``).

    Returns:
        Le répertoire contenant l'index persisté.
    """
    if not chunks:
        raise ValueError("Aucun chunk à indexer : lancez d'abord scripts/collect_events.py")

    index_dir = index_dir or INDEX_DIR
    documents = _to_documents(chunks)
    embeddings = get_embedding_model()

    logger.info("Vectorisation de %s chunks par lots de %s…", len(documents), BATCH_SIZE)
    store = FAISS(
        embedding_function=embeddings,
        index=_nouvel_index(len(embeddings.embed_query("dimension"))),
        docstore=InMemoryDocstore(),
        index_to_docstore_id={},
    )
    for start in range(0, len(documents), BATCH_SIZE):
        lot = documents[start : start + BATCH_SIZE]
        store.add_documents(lot)
        logger.info("  %s / %s chunks vectorisés", min(start + BATCH_SIZE, len(documents)), len(documents))

    index_dir.mkdir(parents=True, exist_ok=True)
    store.save_local(str(index_dir))

    (index_dir / METADATA_FILE).write_text(
        json.dumps(
            {
                "chunks": len(chunks),
                "documents": len({c["metadata"]["uid"] for c in chunks}),
                "embedding_provider": settings.embedding_provider,
                "embedding_model": (
                    settings.embedding_model
                    if settings.embedding_provider == "mistral"
                    else settings.hf_embedding_model
                ),
                "dimension": store.index.d,
                "index_type": settings.faiss_index_type,
                "chunk_size": settings.chunk_size,
                "chunk_overlap": settings.chunk_overlap,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Index FAISS persisté dans %s (%s vecteurs)", index_dir, store.index.ntotal)
    return index_dir


def load_index(index_dir: Path | None = None) -> FAISS:
    """Charge l'index FAISS persisté.

    Raises:
        FileNotFoundError: si l'index n'a pas encore été construit.
        ValueError: si l'index a été construit avec un autre fournisseur d'embeddings.
    """
    index_dir = index_dir or INDEX_DIR
    if not (index_dir / "index.faiss").exists():
        raise FileNotFoundError(
            f"Aucun index dans {index_dir}. Lancez d'abord : python scripts/build_index.py"
        )

    meta_path = index_dir / METADATA_FILE
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("embedding_provider") != settings.embedding_provider:
            raise ValueError(
                f"L'index a été construit avec le fournisseur « {meta.get('embedding_provider')} » "
                f"mais la configuration demande « {settings.embedding_provider} ». "
                "Les dimensions diffèrent : reconstruisez l'index."
            )

    # allow_dangerous_deserialization : l'index est produit localement par ce projet.
    return FAISS.load_local(
        str(index_dir), get_embedding_model(), allow_dangerous_deserialization=True
    )


def verify_index(chunks: list[dict], index_dir: Path | None = None) -> dict:
    """Vérifie que l'index contient bien tout ce qui devait être indexé.

    Un lot d'embeddings en échec, un plafond atteint ou une reprise partielle
    laisseraient un index silencieusement incomplet : le contrôle compare le
    nombre de vecteurs, les identifiants de chunk et les événements couverts.

    Returns:
        Un rapport ``{"vecteurs", "chunks_attendus", "chunks_manquants",
        "evenements_attendus", "evenements_indexes", "complet"}``.
    """
    store = load_index(index_dir)
    indexes = {doc.metadata.get("id") for doc in store.docstore._dict.values()}
    attendus = {c["id"] for c in chunks}
    manquants = attendus - indexes

    evenements_attendus = {c["metadata"]["uid"] for c in chunks}
    evenements_indexes = {
        doc.metadata.get("uid") for doc in store.docstore._dict.values()
    }

    rapport = {
        "vecteurs": store.index.ntotal,
        "chunks_attendus": len(attendus),
        "chunks_manquants": sorted(manquants)[:10],
        "evenements_attendus": len(evenements_attendus),
        "evenements_indexes": len(evenements_indexes),
        "complet": (
            store.index.ntotal == len(attendus)
            and not manquants
            and evenements_attendus == evenements_indexes
        ),
    }
    if not rapport["complet"]:
        logger.warning("Index incomplet : %s", rapport)
    return rapport


def get_retriever(index_dir: Path | None = None):
    """Retourne un retriever configuré (``top_k`` issu de la configuration)."""
    return load_index(index_dir).as_retriever(search_kwargs={"k": settings.top_k})
