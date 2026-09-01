# Puls-Events RAG — Assistant intelligent de recommandation d'événements culturels

POC (Proof of Concept) d'un système **RAG** (Retrieval-Augmented Generation) développé dans le cadre du projet 7 du parcours OpenClassrooms, pour le compte de **Puls-Events**.

## 🎯 Objectifs

- **Contexte** : Puls-Events souhaite proposer à ses utilisateurs un assistant conversationnel capable de recommander des événements culturels pertinents.
- **Problématique** : un système RAG permet de répondre en langage naturel à partir de données d'événements réelles et à jour, sans hallucination hors du catalogue.
- **Objectif du POC** : démontrer la faisabilité technique et la valeur métier d'un pipeline complet :
  1. Collecte des événements **Open Agenda**, filtrés par localisation et par période
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
│   ├── rebuild_all.py          # Tout reconstruire du vide à l'index (CLI)
│   ├── collect_events.py       # Collecte + nettoyage + chunking (CLI)
│   ├── check_dataset.py        # Contrôle de cohérence du jeu de données
│   ├── benchmark_search.py     # Banc d'essai des algorithmes FAISS
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
    ├── architecture.md         #   Architecture technique détaillée
    ├── api-source.md           #   Caractéristiques de l'API de collecte
    └── index-vectoriel.md      #   Choix et mesures de l'index FAISS
```

## 🚀 Instructions de reproduction

### Prérequis

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/) (recommandé) ou pip
- Une clé d'API [Mistral](https://console.mistral.ai/) (la collecte des événements, elle, ne demande aucune clé)

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

### 3. Tout reconstruire en une commande

```bash
uv run python scripts/rebuild_all.py --yes
```

Purge `data/`, puis rejoue la chaîne complète : collecte → nettoyage → chunking →
contrôle de cohérence → vectorisation. La vectorisation n'est lancée que si le
contrôle passe, pour ne pas payer d'appels d'embedding sur un corpus incohérent.
Compter une minute environ pour Paris sur un an d'historique.

Seul `data/` est purgé : `.env` et le code ne sont jamais touchés. `--keep-raw`
repart du dernier brut collecté, sans rappeler l'API.

Les étapes 4 à 6 ci-dessous détaillent cette chaîne, à lancer séparément au besoin.

### 4. Collecter les événements

```bash
uv run python scripts/collect_events.py                                  # Paris, 90 jours
uv run python scripts/collect_events.py --cities Paris Lyon --period-days 60
```

Écrit les événements bruts dans `data/raw/`, puis les documents nettoyés et les chunks
dans `data/processed/`. Voir la section « Source des données » ci-dessous.

### 5. Contrôler la cohérence du jeu de données

```bash
uv run python scripts/check_dataset.py --strict
```

22 contrôles avant de payer la vectorisation : chaînage des artefacts (brut →
documents → chunks → index), respect du périmètre collecté, intégrité du chunking,
propreté du texte à vectoriser, complétude des métadonnées de citation. `--strict`
retourne un code de sortie non nul en cas d'échec, ce qui permet d'en faire un
garde-fou dans un enchaînement de commandes.

Chaque collecte écrit un manifeste `data/raw/events_<horodatage>.meta.json`
(villes, fenêtre, types, plafond) : c'est lui qui permet de vérifier que les
données correspondent bien au périmètre demandé, plutôt que de le supposer.

### 6. Construire l'index vectoriel

```bash
uv run python scripts/build_index.py
```

Le pipeline reprend la collecte, calcule les embeddings et persiste l'index FAISS dans `data/index/`.

### 7. Lancer l'API

```bash
uv run python main.py
# ou : uv run uvicorn puls_events_rag.api.main:app --reload
```

L'API est disponible sur http://127.0.0.1:8000 (documentation interactive : http://127.0.0.1:8000/docs).

### 8. Interroger le système

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Quels concerts ont lieu ce week-end à Paris ?"}'
```

Reconstruire l'index (après mise à jour des données) :

```bash
curl -X POST http://127.0.0.1:8000/rebuild
```

### 9. Vérifier l'environnement

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

### 10. Lancer les tests

```bash
uv run pytest
```

### 11. Lancer l'API dans Docker

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

## 🗃️ Source des données

Les événements proviennent du jeu **« Public events - OpenAgenda »** exposé par l'API
[Opendatasoft Explore v2.1](https://public.opendatasoft.com/explore/dataset/evenements-publics-openagenda/)
— soit les événements publics OpenAgenda, sous Licence Ouverte v1.0 et **sans clé d'API**.

**Choix du portail.** Le jeu est servi par `public.opendatasoft.com`, portail d'origine où
l'identifiant est stable et sans suffixe. Le catalogue fédéré `data.opendatasoft.com`
expose la même donnée sous `evenements-publics-openagenda@public` (1 233 842
enregistrements, totaux identiques à filtres égaux), mais aussi des déclinaisons locales
bien plus petites au nom très proche — `…@ville-de-roubaix` (7 363),
`…@aix-en-provence` (3 156) — qu'il serait facile de collecter par erreur. Pour basculer
malgré tout, `ODS_BASE_URL` et `ODS_DATASET_ID` suffisent, sans changement de code.

**Filtrage.** La collecte croise une localisation (`refine=location_city:…`) et une période.
Le filtre temporel retient les événements dont la période *chevauche* la fenêtre demandée,
et pas seulement ceux qui y démarrent : une exposition commencée avant mais toujours en
cours reste pertinente pour une recommandation.

Les caractéristiques complètes de l'API (paramètres, limites, robustesse, champs
récupérés) sont documentées dans [`docs/api-source.md`](docs/api-source.md).

**Pagination.** L'API plafonne `limit` à 100 et `offset + limit` à 10 000. La collecte est
donc découpée en tranches ville × fenêtre de 30 jours (`WINDOW_DAYS`), chacune paginée
sous ce plafond.

**Nettoyage.** Le jeu est ouvert à la contribution et contient du bruit, traité par
`ingestion/preprocessing.py` : balises HTML, titres en caractères Unicode stylisés
(normalisation NFKC), dates de saisie aberrantes, contenus de test, doublons d'`uid`, et
agendas hors périmètre culturel (`EXCLUDED_AGENDAS`). Sur un échantillon de 300 événements
parisiens, 262 documents sont retenus (35 hors périmètre, 3 descriptions inexploitables).

**Structuration.** Chaque événement devient un document `{"id", "text", "metadata"}` :
`text` est un bloc lisible à champs nommés (titre, date en français, lieu, ville,
mots-clés, public, accessibilité, conditions, description) et `metadata` porte de quoi
citer la source dans la réponse (URL OpenAgenda, dates ISO, coordonnées GPS, ville).

## 🧠 Vectorisation

`scripts/build_index.py` calcule les embeddings de chaque chunk et persiste l'index FAISS
dans `data/index/` :

```bash
uv run python scripts/build_index.py                     # collecte + vectorisation
uv run python scripts/build_index.py --from-chunks       # revectorise sans rappeler l'API
```

Les embeddings sont calculés **par lots de 64** : l'appel lot par lot borne la taille des
requêtes à l'API et permet de suivre l'avancement sur plusieurs milliers de chunks.

Relevé sur l'index de référence (Paris, 1 an d'historique + 90 jours) :

| Mesure | Valeur |
|---|---|
| Événements indexés | 768 (dont 348 à venir) |
| Chunks vectorisés | 2 451 |
| Dimension des vecteurs | 1 024 (`mistral-embed`) |
| Durée de vectorisation | ~32 s pour 1 210 chunks |
| Taille de l'index sur disque | 6,2 Mo pour 1 210 vecteurs |

À côté de `index.faiss` et `index.pkl`, un fichier `index_meta.json` enregistre le
fournisseur, le modèle, la dimension, le type d'index et les paramètres de chunking.
`load_index()` s'en sert pour refuser un index construit avec un autre fournisseur,
plutôt que d'échouer obscurément sur une incompatibilité de dimensions.

L'index est un `IndexFlatL2` : recherche exhaustive, résultats exacts. Ce choix est
mesuré, pas supposé — `scripts/benchmark_search.py` compare Flat et HNSW sur le corpus
réel. Détails et relevés dans [`docs/index-vectoriel.md`](docs/index-vectoriel.md).

```bash
uv run python scripts/benchmark_search.py
```

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
| Source de données | Événements Open Agenda via l'API Opendatasoft Explore v2.1 |
| Embeddings (défaut) | Mistral AI (`mistral-embed`) |
| Embeddings (alternative locale) | HuggingFace (`langchain-huggingface`, `all-MiniLM-L6-v2`) |
| LLM | Mistral AI (`mistral-small-latest`) |
| Base vectorielle | FAISS |
| Orchestration RAG | LangChain |
| API | FastAPI + Uvicorn |
| Qualité / tests | Ruff, Pytest |
| Observabilité | LangSmith (tracing optionnel) |
| Conteneurisation | Docker |
