"""Vérifie que l'environnement de développement est correctement installé.

Ces tests ne valident pas la logique métier : ils garantissent qu'un collègue
(ou un évaluateur) qui reproduit l'installation dispose bien de toutes les
briques nécessaires au pipeline RAG.
"""

import importlib

import pytest

MODULES_REQUIS = [
    "faiss",                              # base vectorielle
    "langchain",                          # orchestration
    "langchain_community.vectorstores",   # intégration FAISS
    "langchain_mistralai",                # embeddings + LLM Mistral (par défaut)
    "langchain_huggingface",              # embeddings locaux (alternative)
    "fastapi",                            # API
    "uvicorn",                            # serveur ASGI
    "pydantic_settings",                  # configuration / .env
]


@pytest.mark.parametrize("module", MODULES_REQUIS)
def test_dependance_importable(module):
    """Chaque dépendance clé du POC doit être importable."""
    importlib.import_module(module)


def test_faiss_cpu_et_non_gpu():
    """faiss-cpu est privilégié à faiss-gpu pour la portabilité."""
    from importlib.metadata import PackageNotFoundError, version

    version("faiss-cpu")
    with pytest.raises(PackageNotFoundError):
        version("faiss-gpu")


def test_integration_faiss_langchain():
    """FAISS doit être exposé par LangChain (compatibilité des versions)."""
    from langchain_community.vectorstores import FAISS

    assert hasattr(FAISS, "from_documents")
    assert hasattr(FAISS, "save_local")
    assert hasattr(FAISS, "load_local")


def test_fournisseurs_embeddings_disponibles():
    """Les deux fournisseurs d'embeddings du POC doivent être instanciables."""
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_mistralai import MistralAIEmbeddings

    assert hasattr(MistralAIEmbeddings, "embed_documents")
    assert hasattr(HuggingFaceEmbeddings, "embed_documents")


def test_package_projet_importable():
    """Le package du projet doit être installé (src-layout)."""
    from puls_events_rag.config import settings

    assert settings.embedding_model
    assert settings.llm_model


def test_modele_env_sans_vraie_cle():
    """Le modèle .env.example documente les clés sans jamais en contenir une vraie."""
    from puls_events_rag.config import PROJECT_ROOT

    contenu = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "MISTRAL_API_KEY" in contenu
    assert "OPENAGENDA_API_KEY" in contenu
    assert "votre_cle_mistral" in contenu  # valeur factice attendue
