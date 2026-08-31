# syntax=docker/dockerfile:1
# Image de l'API RAG Puls-Events (démo locale et déploiement).
# Build : docker build -t puls-events-rag .
# Run   : docker run --rm -p 8000:8000 --env-file .env -v "$PWD/data:/app/data" puls-events-rag

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Gestionnaire de dépendances uv (aligné sur le workflow local)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Dépendances + package (résolution figée via uv.lock)
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# Code applicatif
COPY main.py ./
COPY scripts/ ./scripts/

# Index FAISS et données : montés en volume à l'exécution
RUN mkdir -p data/raw data/processed data/index

# Cache des modèles HuggingFace (fournisseur d'embeddings local) : à monter en
# volume pour éviter de retélécharger le modèle à chaque démarrage du conteneur.
# NB : torch/transformers rendent l'image volumineuse ; s'en tenir au fournisseur
# Mistral suffit si l'image doit rester légère.
ENV HF_HOME=/app/.cache/huggingface

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uv", "run", "uvicorn", "puls_events_rag.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
