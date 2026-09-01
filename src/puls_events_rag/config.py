"""Configuration centralisée du projet (variables d'environnement via .env)."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Racine du projet (P7/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
INDEX_DIR = DATA_DIR / "index"
EVALUATION_DIR = PROJECT_ROOT / "evaluation"
EVALUATION_RESULTS_DIR = EVALUATION_DIR / "results"


class Settings(BaseSettings):
    """Paramètres de l'application, chargés depuis l'environnement / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Clés d'API
    openagenda_api_key: str = ""
    mistral_api_key: str = ""

    # Source de données : jeu "Public events - OpenAgenda" exposé par l'API
    # Opendatasoft Explore v2.1 (données OpenAgenda, sans clé d'API requise).
    ods_base_url: str = "https://public.opendatasoft.com/api/explore/v2.1"
    ods_dataset_id: str = "evenements-publics-openagenda"
    ods_page_size: int = 100          # plafond imposé par l'API
    ods_max_offset: int = 10_000      # l'API refuse offset + limit > 10 000
    ods_timeout: float = 30.0
    ods_max_retries: int = 3

    # Périmètre de collecte
    cities: list[str] = ["Paris"]     # ex. CITIES='["Paris","Lyon"]' dans .env
    history_days: int = 365           # profondeur d'historique, en jours
    period_days: int = 90             # fenêtre à venir, en jours
    event_types: list[str] = []       # ex. ["concert","exposition"] ; vide = tous types
    window_days: int = 30             # découpage temporel des requêtes (plafond d'offset)
    max_events: int = 2000            # garde-fou sur le volume collecté

    # Nettoyage
    min_description_length: int = 30  # sous ce seuil, l'événement est écarté
    max_years_ahead: int = 5          # au-delà, la date est considérée aberrante
    excluded_agendas: list[str] = ["Mes événements France Travail"]

    # Vectorisation
    # Fournisseur d'embeddings : "mistral" (par défaut, via API) ou
    # "huggingface" (modèle local, utile hors ligne ou pour comparer les coûts).
    embedding_provider: Literal["mistral", "huggingface"] = "mistral"
    embedding_model: str = "mistral-embed"
    hf_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_size: int = 512
    chunk_overlap: int = 64

    # Base vectorielle
    # "flat" : recherche exhaustive, résultats exacts — optimal jusqu'à ~100 000
    # vecteurs. "hnsw" : graphe navigable, sous-linéaire, résultats approchés —
    # pertinent au-delà. Voir scripts/benchmark_search.py pour l'arbitrage mesuré.
    faiss_index_type: Literal["flat", "hnsw"] = "flat"
    hnsw_m: int = 32                  # voisins par nœud : qualité vs mémoire
    hnsw_ef_construction: int = 200   # effort de construction du graphe
    hnsw_ef_search: int = 64          # effort de parcours : rappel vs latence

    # Récupération
    top_k: int = 5
    score_threshold: float = 0.0

    # Génération
    llm_model: str = "mistral-small-latest"

    # Observabilité (LangSmith)
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "puls-events-rag"


settings = Settings()
