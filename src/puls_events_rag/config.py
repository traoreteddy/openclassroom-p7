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

    # Périmètre des données (à ajuster selon le POC)
    openagenda_location: str = "Paris"

    # Vectorisation
    # Fournisseur d'embeddings : "mistral" (par défaut, via API) ou
    # "huggingface" (modèle local, utile hors ligne ou pour comparer les coûts).
    embedding_provider: Literal["mistral", "huggingface"] = "mistral"
    embedding_model: str = "mistral-embed"
    hf_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_size: int = 512
    chunk_overlap: int = 64

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
