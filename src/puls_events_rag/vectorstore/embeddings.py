"""Modèle d'embeddings : conversion des descriptions d'événements en vecteurs.

Deux fournisseurs, sélectionnés par ``settings.embedding_provider`` :

- ``mistral``     : API Mistral (``mistral-embed``, 1024 dimensions) — défaut du POC.
- ``huggingface`` : modèle local via ``langchain-huggingface`` (``all-MiniLM-L6-v2``,
  384 dimensions) — sans clé ni coût par appel, utile hors ligne et pour comparer
  qualité, latence et coût dans le rapport d'évaluation.

Les deux modèles ne produisent pas des vecteurs de même dimension : changer de
fournisseur impose de reconstruire l'index.
"""

from __future__ import annotations

import logging

from langchain_core.embeddings import Embeddings

from puls_events_rag.config import settings

logger = logging.getLogger(__name__)


def get_embedding_model() -> Embeddings:
    """Retourne le modèle d'embedding LangChain correspondant au fournisseur configuré.

    Raises:
        ValueError: si le fournisseur est ``mistral`` sans ``MISTRAL_API_KEY``.
    """
    if settings.embedding_provider == "mistral":
        if not settings.mistral_api_key:
            raise ValueError(
                "MISTRAL_API_KEY est absente. Renseignez-la dans .env, ou basculez sur "
                "le fournisseur local avec EMBEDDING_PROVIDER=huggingface."
            )
        from langchain_mistralai import MistralAIEmbeddings

        logger.info("Embeddings : Mistral (%s)", settings.embedding_model)
        return MistralAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.mistral_api_key,
        )

    from langchain_huggingface import HuggingFaceEmbeddings

    logger.info("Embeddings : HuggingFace local (%s)", settings.hf_embedding_model)
    return HuggingFaceEmbeddings(
        model_name=settings.hf_embedding_model,
        encode_kwargs={"normalize_embeddings": True},
    )


def embedding_dimension(model: Embeddings | None = None) -> int:
    """Dimension des vecteurs produits, utile pour valider un index existant."""
    model = model or get_embedding_model()
    return len(model.embed_query("test de dimension"))
