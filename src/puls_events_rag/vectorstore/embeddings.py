"""Calcul des embeddings (API Mistral) avec traitement par batch."""

from puls_events_rag.config import settings  # noqa: F401


def get_embedding_model():
    """Retourne le modèle d'embedding LangChain configuré."""
    raise NotImplementedError("TODO: instancier MistralAIEmbeddings")
