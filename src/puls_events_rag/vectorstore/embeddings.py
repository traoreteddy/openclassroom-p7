"""Calcul des embeddings, avec traitement par batch.

Deux fournisseurs sont prévus, sélectionnés par ``settings.embedding_provider`` :

- ``mistral``     : API Mistral (`mistral-embed`) — fournisseur par défaut du POC.
- ``huggingface`` : modèle local via `langchain-huggingface` — pas de clé d'API
  ni de coût par appel, utile pour travailler hors ligne et pour comparer
  qualité/latence/coût avec l'API dans le rapport d'évaluation.
"""

from puls_events_rag.config import settings  # noqa: F401


def get_embedding_model():
    """Retourne le modèle d'embedding LangChain correspondant au fournisseur configuré."""
    raise NotImplementedError(
        "TODO: instancier MistralAIEmbeddings ou HuggingFaceEmbeddings selon settings"
    )
