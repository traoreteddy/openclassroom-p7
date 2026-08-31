# Architecture technique — Puls-Events RAG

> Squelette de documentation. Chaque section est à compléter au fil de
> l'implémentation, puis reprise dans le rapport technique
> (`Template+de+rapport+technique.docx`).

## 1. Contexte et objectifs du POC

## 2. Vue d'ensemble du pipeline

```text
Open Agenda ──> Nettoyage ──> Chunking ──> Embeddings ──> Index FAISS
                                                              │
Question ────────────────────────────────> Retriever ─────────┘
                                               │
                                               ▼
                                    Prompt augmenté ──> LLM ──> Réponse + sources
```

### 2.1 Ingestion et indexation
- Source et périmètre des données collectées
- Règles de nettoyage et de déduplication
- Stratégie de chunking (taille, chevauchement, champs vectorisés)
- Modèle d'embeddings et format de l'index persisté

### 2.2 Récupération
- Mesure de similarité, `top_k`, seuil de score
- Métadonnées remontées avec chaque chunk

### 2.3 Augmentation et génération
- Structure du prompt système
- Modèle de génération et paramètres

## 3. Exposition applicative (API)
- Endpoints, schémas de requête/réponse, codes d'erreur

## 4. Évaluation
- Constitution du jeu de test annoté
- Métriques retenues et résultats

## 5. Observabilité et coûts
- Tracing des chaînes, latences, consommation de tokens

## 6. Déploiement
- Conteneurisation, variables d'environnement, cycle de reconstruction de l'index

## 7. Limites et pistes d'amélioration
