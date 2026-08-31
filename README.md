# Puls-Events RAG — Assistant intelligent de recommandation d'événements culturels

POC (Proof of Concept) d'un système **RAG** (Retrieval-Augmented Generation) développé dans le cadre du projet 7 du parcours OpenClassrooms, pour le compte de **Puls-Events**.

## 🎯 Objectifs

- **Contexte** : Puls-Events souhaite proposer à ses utilisateurs un assistant conversationnel capable de recommander des événements culturels pertinents.
- **Problématique** : un système RAG permet de répondre en langage naturel à partir de données d'événements réelles et à jour, sans hallucination hors du catalogue.
- **Objectif du POC** : démontrer la faisabilité technique et la valeur métier d'un pipeline complet :
  1. Collecte des événements via l'**API Open Agenda**
  2. Nettoyage, chunking et **vectorisation** (embeddings Mistral, ou HuggingFace en local)
  3. Indexation dans une base vectorielle **FAISS** (persistée sur disque)
  4. Chaîne RAG orchestrée avec **LangChain** (retriever + LLM Mistral)
  5. Exposition via une **API FastAPI** (`/ask`, `/rebuild`)
  6. **Évaluation** sur un jeu de test annoté (similarité sémantique, couverture des réponses)

## 🗂️ Structure du projet

```
P7/
├── README.md
├── pyproject.toml              # Dépendances et configuration du projet (uv / pip)
├── uv.lock                     # Résolution figée des dépendances (reproductibilité)
├── requirements.txt            # Dépendances d'exécution figées (export de uv.lock)
├── requirements-dev.txt        # Outils de développement (pytest, ruff, jupyter)
├── .env.example                # Modèle de variables d'environnement (clés d'API, tracing)
├── Dockerfile                  # Conteneurisation de l'API
├── .dockerignore
├── main.py                     # Point d'entrée : lance l'API en local
├── src/
│   └── puls_events_rag/        # Package principal (src-layout)
│       ├── config.py           # Configuration centralisée (chemins, modèles, .env)
│       ├── ingestion/          # Collecte et préparation des données
│       │   ├── open_agenda.py  #   Client API Open Agenda
│       │   └── preprocessing.py#   Nettoyage + chunking des événements
│       ├── vectorstore/        # Base vectorielle
│       │   ├── embeddings.py   #   Embeddings (Mistral / HuggingFace, batch)
│       │   └── faiss_store.py  #   Construction / persistance / chargement FAISS
│       ├── rag/                # Chaîne RAG
│       │   ├── prompts.py      #   Prompts système
│       │   └── chain.py        #   Assemblage retriever + LLM (LangChain)
│       └── api/                # API HTTP
│           ├── main.py         #   Application FastAPI (/health, /ask, /rebuild)
│           └── schemas.py      #   Schémas Pydantic requêtes/réponses
├── scripts/
│   └── build_index.py          # Pipeline complet d'indexation (CLI)
├── notebooks/                  # Explorations (données, embeddings, évaluation)
├── data/                       # Données locales (non versionnées)
│   ├── raw/                    #   Événements bruts Open Agenda
│   ├── processed/              #   Documents nettoyés / chunks
│   └── index/                  #   Index FAISS persisté + métadonnées
├── evaluation/                 # Évaluation du système
│   ├── test_set.example.json   #   Format du jeu de test annoté
│   ├── evaluate_rag.py         #   Script d'évaluation (métriques + rapport)
│   └── results/                #   Rapports générés (non versionnés)
├── tests/                      # Tests automatisés (pytest)
│   ├── test_environment.py     #   Vérification de l'environnement et des imports
│   └── test_api.py             #   Tests de l'API
└── docs/                       # Rapport technique et documentation
    └── architecture.md         #   Architecture technique détaillée
```

## 🚀 Instructions de reproduction

### Prérequis

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/) (recommandé) ou pip
- Une clé d'API [Open Agenda](https://developers.openagenda.com/) et une clé d'API [Mistral](https://console.mistral.ai/)

### 1. Cloner le dépôt et installer les dépendances

```bash
git clone <url-du-depot>
cd P7

# Avec uv (recommandé) : crée .venv et installe les versions figées de uv.lock
uv sync

# Ou avec venv + pip
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # dépendances d'exécution
pip install -r requirements-dev.txt    # outils de dev (pytest, ruff, jupyter)
pip install -e . --no-deps             # le package puls_events_rag lui-même
```

L'environnement virtuel (`.venv/`) **n'est pas versionné** : la reproductibilité est assurée
par `uv.lock` et les fichiers `requirements*.txt`, qui figent toutes les versions transitives.
Ces derniers sont générés depuis `uv.lock` — ne pas les éditer à la main :

```bash
uv export --frozen --no-hashes --no-emit-project --no-dev  -o requirements.txt
uv export --frozen --no-hashes --no-emit-project --only-dev -o requirements-dev.txt
```

### 2. Configurer les clés d'API

```bash
cp .env.example .env
# Éditer .env et renseigner OPENAGENDA_API_KEY et MISTRAL_API_KEY
# (variables LANGSMITH_* optionnelles : tracing des chaînes RAG)
```

### 3. Construire l'index vectoriel

```bash
uv run python scripts/build_index.py
```

Le pipeline collecte les événements, les nettoie, les découpe en chunks, calcule les embeddings et persiste l'index FAISS dans `data/index/`.

### 4. Lancer l'API

```bash
uv run python main.py
# ou : uv run uvicorn puls_events_rag.api.main:app --reload
```

L'API est disponible sur http://127.0.0.1:8000 (documentation interactive : http://127.0.0.1:8000/docs).

### 5. Interroger le système

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Quels concerts ont lieu ce week-end à Paris ?"}'
```

Reconstruire l'index (après mise à jour des données) :

```bash
curl -X POST http://127.0.0.1:8000/rebuild
```

### 6. Vérifier l'environnement

```bash
uv run pytest tests/test_environment.py -v
```

Ces tests contrôlent que toutes les briques du pipeline sont importables et compatibles
(`faiss-cpu`, intégration FAISS/LangChain, `langchain-mistralai`, FastAPI, configuration).

Pour simuler une installation « propre » sur une nouvelle machine :

```bash
python -m venv /tmp/env-test && source /tmp/env-test/bin/activate
pip install --no-cache-dir -r requirements.txt && pip install -e . --no-deps
python -m pytest tests/test_environment.py
```

### 7. Lancer les tests

```bash
uv run pytest
```

### 8. Lancer l'API dans Docker

```bash
docker build -t puls-events-rag .
docker run --rm -p 8000:8000 --env-file .env -v "$PWD/data:/app/data" puls-events-rag
```

L'index FAISS est monté depuis `data/`, il n'est donc pas embarqué dans l'image.

## 📊 Évaluation

Le jeu de test annoté se trouve dans `evaluation/` (voir `test_set.example.json` pour le format).

```bash
uv run python evaluation/evaluate_rag.py
```

Le script interroge la chaîne RAG sur chaque question, calcule les métriques (similarité sémantique, couverture des sources, taux d'abstention) et écrit un rapport dans `evaluation/results/`. Les résultats commentés sont repris dans le rapport technique (`docs/`).

## 🔀 Fournisseurs d'embeddings

Le POC repose par défaut sur l'API **Mistral** (`mistral-embed`). Un second fournisseur,
**HuggingFace** en local (`sentence-transformers/all-MiniLM-L6-v2`), est installé et
sélectionnable via la configuration :

```bash
# .env
EMBEDDING_PROVIDER=huggingface        # "mistral" (défaut) ou "huggingface"
HF_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

Intérêt du second fournisseur : fonctionnement **hors ligne et sans coût par appel**, et
comparaison qualité / latence / coût entre API et modèle local dans le rapport d'évaluation.
À noter : il embarque `torch` et `transformers`, ce qui alourdit l'installation
(≈ 1 Go) et l'image Docker. L'index FAISS doit être **reconstruit** en cas de changement
de fournisseur, les deux modèles ne produisant pas des vecteurs de même dimension.

## 🔍 Observabilité

Le tracing LangSmith s'active par variables d'environnement (`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`) : il permet d'auditer les latences, d'inspecter les chunks réellement récupérés et de suivre la consommation de tokens. Aucune dépendance supplémentaire n'est requise (`langsmith` est déjà embarqué par LangChain).

## 🛠️ Technologies

| Composant | Technologie |
|---|---|
| Source de données | API Open Agenda |
| Embeddings (défaut) | Mistral AI (`mistral-embed`) |
| Embeddings (alternative locale) | HuggingFace (`langchain-huggingface`, `all-MiniLM-L6-v2`) |
| LLM | Mistral AI (`mistral-small-latest`) |
| Base vectorielle | FAISS |
| Orchestration RAG | LangChain |
| API | FastAPI + Uvicorn |
| Qualité / tests | Ruff, Pytest |
| Observabilité | LangSmith (tracing optionnel) |
| Conteneurisation | Docker |
