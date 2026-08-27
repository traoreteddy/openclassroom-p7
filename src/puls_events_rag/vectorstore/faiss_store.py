"""Construction, persistance et chargement de la base vectorielle FAISS.

L'index est sauvegardé dans data/index/ avec ses métadonnées
(titre, date, lieu, URL de l'événement pour chaque chunk).
"""

from puls_events_rag.config import INDEX_DIR  # noqa: F401


def build_index(chunks: list[dict]) -> None:
    """Construit l'index FAISS à partir des chunks et le persiste sur disque."""
    raise NotImplementedError("TODO: FAISS.from_documents + save_local")


def load_index():
    """Charge l'index FAISS persisté et retourne un retriever."""
    raise NotImplementedError("TODO: FAISS.load_local")
