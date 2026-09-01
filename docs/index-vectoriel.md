# Base vectorielle FAISS

Choix d'implémentation et mesures de l'index construit par
`src/puls_events_rag/vectorstore/faiss_store.py`.

## 1. Composition de l'index

| Caractéristique | Valeur |
|---|---|
| Bibliothèque | FAISS (`faiss-cpu`), pilotée via LangChain |
| Type d'index | `IndexFlatL2` (recherche exhaustive, résultats exacts) |
| Vecteurs | 2 030 chunks pour 616 événements |
| Dimension | 1 024 (`mistral-embed`) |
| Métrique | Distance L2 |
| Taille sur disque | ~6 Mo |

Fichiers persistés dans `data/index/` :

- `index.faiss` — les vecteurs et la structure de recherche ;
- `index.pkl` — le docstore LangChain : texte et métadonnées de chaque chunk ;
- `index_meta.json` — fournisseur, modèle, dimension, type d'index et paramètres
  de chunking, écrits par le projet.

## 2. Métadonnées indexées

Chaque vecteur porte les métadonnées de son événement, ce qui permet à la chaîne
RAG de citer ses sources plutôt que de les paraphraser :

`uid`, `titre`, `url` (page OpenAgenda), `date_debut`, `date_fin`, `periode`
(formulée en français), `lieu`, `adresse`, `ville`, `code_postal`,
`departement`, `region`, `latitude`, `longitude`, `mots_cles`, `agenda_source`,
`modalite`, `accessibilite`, `age_min`, `age_max`, plus `chunk_index` et
`chunk_total` pour situer le morceau dans son événement.

Couverture mesurée : 616/616 événements avec URL et coordonnées GPS.

## 3. Métrique : pourquoi L2 et non le cosinus

Les embeddings Mistral sont **unitaires** — normes mesurées entre 0,9999 et
1,0002 sur un échantillon de 500 vecteurs. Or pour des vecteurs de norme 1 :

```
||a − b||² = 2 − 2·cos(a, b)
```

Distance L2 et similarité cosinus produisent donc exactement le même classement.
Normaliser explicitement ou changer de métrique n'apporterait rien ; la valeur
par défaut de LangChain (`EUCLIDEAN_DISTANCE`) est conservée en connaissance de
cause.

## 4. Choix de l'algorithme : mesures

`scripts/benchmark_search.py` compare les deux algorithmes sur le corpus réel.
Les vecteurs sont relus depuis l'index existant : la comparaison ne refacture
aucun embedding.

Relevé sur 2 030 vecteurs, 8 requêtes réelles, 400 recherches :

| Index | Moyenne | p50 | p95 | Rappel@5 | Construction |
|---|---|---|---|---|---|
| **Flat (exact)** | 0,168 ms | 0,165 ms | 0,183 ms | 1,000 | immédiate |
| HNSW (M=32, efSearch=64) | 0,066 ms | 0,066 ms | 0,085 ms | 0,950 | 0,07 s |

HNSW est bien 2,5 fois plus rapide — mais le gain absolu est de **0,10 ms**,
soit **0,09 %** du coût d'embedding d'une requête (109 ms mesurées sur l'API
Mistral). Autrement dit : le gain est invisible pour l'utilisateur, alors que la
perte de rappel, elle, se voit dans les réponses — 5 % des meilleurs résultats
manqués.

**Décision : `IndexFlatL2`.** Exact, sans paramétrage, sans coût de
construction. C'est le bon algorithme à cette échelle, et le rester tant que la
recherche ne pèse pas dans le temps de réponse — typiquement au-delà de quelques
centaines de milliers de vecteurs.

Le basculement est prêt si le corpus grandit :

```bash
FAISS_INDEX_TYPE=hnsw  # puis reconstruire l'index
```

Les paramètres `HNSW_M`, `HNSW_EF_CONSTRUCTION` et `HNSW_EF_SEARCH` sont
exposés dans la configuration ; `efSearch` est le levier rappel/latence.

## 5. Vérification de l'exhaustivité

Un lot d'embeddings en échec ou une reprise partielle laisseraient un index
silencieusement incomplet. `verify_index()` compare trois choses : le nombre de
vecteurs, les identifiants de chunk et les événements couverts. Le contrôle est
intégré à `scripts/check_dataset.py` (contrôle A6) :

```
OK  A6 tous les chunks présents dans l'index — 2030 vecteurs / 2030 attendus, 0 manquants
    événements couverts : 616/616 | index flat
```

Deux tests verrouillent ce comportement, dont un qui construit délibérément un
index partiel pour vérifier qu'il est bien rejeté.

## 6. Construction par lots

Les embeddings sont calculés par lots de 64. L'appel lot par lot borne la taille
des requêtes envoyées à l'API et permet de suivre l'avancement sur plusieurs
milliers de chunks. Durée mesurée : ~32 s pour 1 210 chunks via l'API Mistral.

## 7. Garde-fou au chargement

`load_index()` refuse un index construit avec un autre fournisseur d'embeddings :
`mistral-embed` produit des vecteurs de dimension 1 024, `all-MiniLM-L6-v2` de
dimension 384. Sans ce contrôle, l'incompatibilité se manifesterait par une
erreur obscure de dimension au moment de la première recherche.
