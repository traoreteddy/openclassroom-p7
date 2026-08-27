# Puls-Events RAG — Assistant intelligent de recommandation d'événements culturels

POC (Proof of Concept) d'un système **RAG** (Retrieval-Augmented Generation) développé dans le cadre du projet 7 du parcours OpenClassrooms, pour le compte de **Puls-Events**.

## 🎯 Objectifs

- **Contexte** : Puls-Events souhaite proposer à ses utilisateurs un assistant conversationnel capable de recommander des événements culturels pertinents.
- **Problématique** : un système RAG permet de répondre en langage naturel à partir de données d'événements réelles et à jour, sans hallucination hors du catalogue.
- **Objectif du POC** : démontrer la faisabilité technique et la valeur métier d'un pipeline complet :
  1. Collecte des événements via l'**API Open Agenda**
  2. Nettoyage, chunking et **vectorisation** (embeddings Mistral)
  3. Indexation dans une base vectorielle **FAISS** (persistée sur disque)
  4. Chaîne RAG orchestrée avec **LangChain** (retriever + LLM Mistral)
  5. Exposition via une **API FastAPI** (`/ask`, `/rebuild`)
  6. **Évaluation** sur un jeu de test annoté (similarité sémantique, couverture des réponses)

## 🗂️ Structure du projet

```
P7/
├── README.md
├── pyproject.toml              # Dépendances et configuration du projet (uv / pip)
├── .env.example                # Modèle de variables d'environnement (clés d'API)
├── main.py                     # Point d'entrée : lance l'API en local
├── src/
│   └── puls_events_rag/        # Package principal (src-layout)
│       ├── config.py           # Configuration centralisée (chemins, modèles, .env)
│       ├── ingestion/          # Collecte et préparation des données
│       │   ├── open_agenda.py  #   Client API Open Agenda
│       │   └── preprocessing.py#   Nettoyage + chunking des événements
│       ├── vectorstore/        # Base vectorielle
│       │   ├── embeddings.py   #   Embeddings (Mistral, batch)
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
├── evaluation/                 # Jeu de test annoté et résultats d'évaluation
├── tests/                      # Tests automatisés (pytest)
└── docs/                       # Rapport technique et documentation
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

# Avec uv (recommandé)
uv sync

# Ou avec pip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configurer les clés d'API

```bash
cp .env.example .env
# Éditer .env et renseigner OPENAGENDA_API_KEY et MISTRAL_API_KEY
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

### 6. Lancer les tests

```bash
uv run pytest
```

## 📊 Évaluation

Le jeu de test annoté se trouve dans `evaluation/` (voir `test_set.example.json` pour le format). Les métriques utilisées et les résultats sont détaillés dans le rapport technique (`docs/`).

## 🛠️ Technologies

| Composant | Technologie |
|---|---|
| Source de données | API Open Agenda |
| Embeddings & LLM | Mistral AI (`mistral-embed`, `mistral-small-latest`) |
| Base vectorielle | FAISS |
| Orchestration RAG | LangChain |
| API | FastAPI + Uvicorn |
| Qualité / tests | Ruff, Pytest |
