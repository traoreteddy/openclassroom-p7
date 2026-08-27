"""Configuration centralisée du projet (variables d'environnement via .env)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Racine du projet (P7/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
INDEX_DIR = DATA_DIR / "index"


class Settings(BaseSettings):
    """Paramètres de l'application, chargés depuis l'environnement / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Clés d'API
    openagenda_api_key: str = ""
    mistral_api_key: str = ""

    # Périmètre des données (à ajuster selon le POC)
    openagenda_location: str = "Paris"

    # Vectorisation
    embedding_model: str = "mistral-embed"
    chunk_size: int = 512
    chunk_overlap: int = 64

    # Génération
    llm_model: str = "mistral-small-latest"


settings = Settings()
