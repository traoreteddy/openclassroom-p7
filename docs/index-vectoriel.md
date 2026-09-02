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
| Taille sur disque | 9,8 Mo (8,31 Mo de vecteurs + 1,50 Mo de docstore) |

Fichiers persistés dans `data/index/` :

- `index.faiss` — **les vecteurs eux-mêmes**, plus la structure de recherche.
  C'est l'artefact de la vectorisation : 2 030 × 1 024 × 4 octets (float32) =
  8,31 Mo, soit exactement la taille du fichier à 45 octets d'en-tête près. Les
  vecteurs se relisent avec `index.reconstruct_n()`, ce dont
  `scripts/benchmark_search.py` se sert pour comparer les algorithmes sans
  refacturer un seul embedding ;
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

Les embeddings sont calculés par lots de 64 (`BATCH_SIZE`), dans la boucle de
`faiss_store.py` :

```python
for start in range(0, len(documents), BATCH_SIZE):
    lot = documents[start : start + BATCH_SIZE]
    store.add_documents(lot)
    logger.info("  %s / %s chunks vectorisés",
                min(start + BATCH_SIZE, len(documents)), len(documents))
```

### Déroulé sur le corpus de référence

`range(0, 2030, 64)` produit 32 départs : 0, 64, 128, … 1984. À chaque tour, une
tranche de 64 documents est prélevée. Les trois derniers tours :

```
documents[1856:1920] → 64 documents
documents[1920:1984] → 64 documents
documents[1984:2048] → 46 documents    ← 2030 n'est pas un multiple de 64
```

Le dernier lot est incomplet, et aucun cas particulier ne le traite : le
découpage Python tronque de lui-même à la fin de la liste, `documents[1984:2048]`
ne lève pas d'erreur alors que l'indice 2048 n'existe pas.

Le `min()` de la ligne de journal relève du même détail : au dernier tour,
`start + BATCH_SIZE` vaut 2048 pour 2 030 documents. Sans lui, le journal
afficherait « 2048 / 2030 chunks vectorisés » — sans conséquence sur le
traitement, mais de quoi faire douter du reste.

### Ce que fait un tour de boucle

`store.add_documents(lot)` enchaîne deux opérations dans LangChain :

1. **Appel à l'API** — `embedding_function.embed_documents(textes)` envoie les 64
   `page_content` à Mistral, qui renvoie 64 vecteurs de 1 024 nombres. Seul le
   `page_content` est vectorisé ; les métadonnées ne partent jamais chez le
   fournisseur.
2. **Insertion** — `index.add(vector)` ajoute la matrice à l'index, soit 256 Ko
   par lot (64 × 1024 × 4 octets), puis le texte et les métadonnées rejoignent
   le docstore, reliés au vecteur par `index_to_docstore_id`.

Bilan pour le corpus de référence : **32 appels d'embedding**, plus un premier
appel isolé qui sert uniquement à connaître la dimension des vecteurs avant de
créer l'index vide. Durée mesurée : ~32 s pour 1 210 chunks.

### Pourquoi découper

- **Contrainte de l'API** : 2 030 textes en une requête représenteraient
  plusieurs mégaoctets de charge utile, au-delà des plafonds de taille et de
  tokens par appel.
- **Visibilité** : la vectorisation dure une trentaine de secondes ; sans
  journal d'avancement, rien ne distinguerait un traitement en cours d'un
  blocage réseau.

### Comportement en cas d'échec

L'écriture sur disque (`save_local`) intervient **après** la boucle. Si un lot
échoue, l'exception remonte et `index.faiss` n'est jamais écrit partiellement :
l'index précédent reste intact. Un index à moitié construit serait pire qu'une
absence d'index, puisque rien ne le signalerait à la recherche.

Le revers est qu'il n'y a pas de reprise : un échec au 30ᵉ lot sur 32 perd les
29 appels déjà payés. À cette échelle — trente secondes et quelques centimes —
c'est acceptable. Sur un corpus de plusieurs centaines de milliers de chunks, il
faudrait sauvegarder l'index tous les N lots pour permettre une reprise.

## 7. Garde-fou au chargement

`load_index()` refuse un index construit avec un autre fournisseur d'embeddings :
`mistral-embed` produit des vecteurs de dimension 1 024, `all-MiniLM-L6-v2` de
dimension 384. Sans ce contrôle, l'incompatibilité se manifesterait par une
erreur obscure de dimension au moment de la première recherche.
