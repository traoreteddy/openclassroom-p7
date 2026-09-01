"""Tests de la vectorisation et de l'index FAISS.

Les tests tournent hors ligne : le modèle d'embedding réel est remplacé par un
modèle déterministe, ce qui permet de valider la mécanique (construction,
persistance, rechargement, métadonnées, garde-fous) sans clé d'API ni
téléchargement de modèle.
"""

import json

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from puls_events_rag.vectorstore import faiss_store
from puls_events_rag.vectorstore.embeddings import get_embedding_model

DIMENSION = 16


@pytest.fixture
def embeddings_factices(monkeypatch):
    """Remplace le modèle d'embedding par un modèle déterministe local."""
    modele = DeterministicFakeEmbedding(size=DIMENSION)
    monkeypatch.setattr(faiss_store, "get_embedding_model", lambda: modele)
    return modele


def chunks_de_test(nombre: int = 5) -> list[dict]:
    return [
        {
            "id": f"{i}::0",
            "text": f"Concert de jazz numéro {i} au Duc des Lombards, Paris.",
            "metadata": {
                "uid": str(i),
                "titre": f"Concert {i}",
                "url": f"https://openagenda.com/agenda/events/concert-{i}",
                "ville": "Paris",
                "periode": "le 12 septembre 2026 à 18h00",
                "chunk_index": 0,
                "chunk_total": 1,
            },
        }
        for i in range(nombre)
    ]


# --- Sélection du modèle d'embedding ------------------------------------------


def test_fournisseur_mistral_sans_cle_leve_une_erreur_explicite(monkeypatch):
    """Sans clé, le message doit indiquer la solution de repli."""
    from puls_events_rag.config import settings

    monkeypatch.setattr(settings, "embedding_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "")
    with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
        get_embedding_model()


# --- Construction de l'index ---------------------------------------------------


def test_index_vide_est_refuse(embeddings_factices, tmp_path):
    with pytest.raises(ValueError, match="Aucun chunk"):
        faiss_store.build_index([], index_dir=tmp_path)


def test_index_contient_un_vecteur_par_chunk(embeddings_factices, tmp_path):
    faiss_store.build_index(chunks_de_test(5), index_dir=tmp_path)
    store = faiss_store.load_index(tmp_path)
    assert store.index.ntotal == 5
    assert store.index.d == DIMENSION


def test_vectorisation_par_lots_traite_tous_les_chunks(embeddings_factices, tmp_path):
    """Le volume dépasse la taille de lot : aucun chunk ne doit être perdu."""
    nombre = faiss_store.BATCH_SIZE * 2 + 7
    faiss_store.build_index(chunks_de_test(nombre), index_dir=tmp_path)
    assert faiss_store.load_index(tmp_path).index.ntotal == nombre


def test_metadonnees_de_l_index_sont_persistees(embeddings_factices, tmp_path):
    faiss_store.build_index(chunks_de_test(3), index_dir=tmp_path)
    meta = json.loads((tmp_path / faiss_store.METADATA_FILE).read_text(encoding="utf-8"))
    assert meta["chunks"] == 3
    assert meta["documents"] == 3
    assert meta["dimension"] == DIMENSION


# --- Rechargement et recherche -------------------------------------------------


def test_index_absent_donne_une_consigne_utilisable(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_index.py"):
        faiss_store.load_index(tmp_path)


def test_changement_de_fournisseur_est_detecte(embeddings_factices, tmp_path, monkeypatch):
    """Mistral et HuggingFace n'ont pas la même dimension : l'index doit être refusé."""
    from puls_events_rag.config import settings

    faiss_store.build_index(chunks_de_test(3), index_dir=tmp_path)
    monkeypatch.setattr(settings, "embedding_provider", "huggingface")
    with pytest.raises(ValueError, match="reconstruisez l'index"):
        faiss_store.load_index(tmp_path)


def test_recherche_retourne_les_metadonnees_de_citation(embeddings_factices, tmp_path):
    faiss_store.build_index(chunks_de_test(5), index_dir=tmp_path)
    resultats = faiss_store.load_index(tmp_path).similarity_search("concert", k=2)
    assert len(resultats) == 2
    for doc in resultats:
        assert doc.metadata["url"].startswith("https://openagenda.com/")
        assert doc.metadata["ville"] == "Paris"
        assert doc.page_content


# --- Algorithme d'index ---------------------------------------------------------


def test_index_flat_par_defaut(embeddings_factices, tmp_path):
    """Le défaut est la recherche exhaustive : résultats exacts."""
    import faiss

    faiss_store.build_index(chunks_de_test(5), index_dir=tmp_path)
    assert isinstance(faiss_store.load_index(tmp_path).index, faiss.IndexFlatL2)


def test_index_hnsw_configurable(embeddings_factices, tmp_path, monkeypatch):
    """Le graphe HNSW est activable pour les gros corpus, avec ses paramètres."""
    import faiss

    from puls_events_rag.config import settings

    monkeypatch.setattr(settings, "faiss_index_type", "hnsw")
    monkeypatch.setattr(settings, "hnsw_m", 16)
    faiss_store.build_index(chunks_de_test(20), index_dir=tmp_path)

    store = faiss_store.load_index(tmp_path)
    assert isinstance(store.index, faiss.IndexHNSWFlat)
    assert store.index.ntotal == 20
    meta = json.loads((tmp_path / faiss_store.METADATA_FILE).read_text(encoding="utf-8"))
    assert meta["index_type"] == "hnsw"


# --- Exhaustivité de l'index ----------------------------------------------------


def test_index_complet_est_confirme(embeddings_factices, tmp_path):
    chunks = chunks_de_test(12)
    faiss_store.build_index(chunks, index_dir=tmp_path)
    rapport = faiss_store.verify_index(chunks, index_dir=tmp_path)
    assert rapport["complet"]
    assert rapport["vecteurs"] == 12
    assert rapport["evenements_indexes"] == rapport["evenements_attendus"] == 12


def test_index_incomplet_est_detecte(embeddings_factices, tmp_path):
    """Un index construit sur un sous-ensemble ne doit pas passer pour complet."""
    chunks = chunks_de_test(12)
    faiss_store.build_index(chunks[:8], index_dir=tmp_path)
    rapport = faiss_store.verify_index(chunks, index_dir=tmp_path)
    assert not rapport["complet"]
    assert rapport["vecteurs"] == 8
    assert len(rapport["chunks_manquants"]) == 4


def test_retriever_respecte_le_top_k(embeddings_factices, tmp_path, monkeypatch):
    from puls_events_rag.config import settings

    monkeypatch.setattr(settings, "top_k", 3)
    faiss_store.build_index(chunks_de_test(10), index_dir=tmp_path)
    assert len(faiss_store.get_retriever(tmp_path).invoke("concert")) == 3
