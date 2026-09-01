# Source de données et API de collecte

Caractéristiques de l'API interrogée par `src/puls_events_rag/ingestion/open_agenda.py`.
Toutes les valeurs ci-dessous ont été mesurées sur l'API elle-même (relevés du
31 août 2026), et non reprises d'une documentation.

## 1. Identification de la source

| Caractéristique | Valeur |
|---|---|
| Jeu de données | « Public events - OpenAgenda » |
| Éditeur déclaré | OpenAgenda (`references: https://openagenda.com/`) |
| Portail | `https://public.opendatasoft.com` |
| Identifiant | `evenements-publics-openagenda` |
| API | Opendatasoft Explore **v2.1** |
| Licence | Licence Ouverte v1.0 (Etalab) |
| Volume total | 1 233 842 enregistrements |
| Volume Paris | 72 902 événements |

**Authentification : aucune.** C'est la raison du choix de cette source. L'API
OpenAgenda native est fermée sans clé :

```
GET https://api.openagenda.com/v2/agendas
→ 403 {"message":"could not find user or agenda matching key"}
```

Les données restent celles d'OpenAgenda : sur un échantillon de 300 événements
collectés, **300 URL canoniques sur 300** pointent vers `openagenda.com`, et ces
pages existent (HTTP 200, titre identique à l'enregistrement).

**Portail fédéré.** `data.opendatasoft.com` sert la même donnée sous
`evenements-publics-openagenda@public` (totaux identiques à filtres égaux), mais
son catalogue contient aussi des déclinaisons locales homonymes bien plus
petites (`…@ville-de-roubaix` : 7 363 enregistrements). Le projet reste sur le
portail d'origine, où l'identifiant est sans suffixe.

## 2. Endpoint et paramètres

```
GET {ODS_BASE_URL}/catalog/datasets/{ODS_DATASET_ID}/records
```

| Paramètre | Usage dans le projet |
|---|---|
| `where` | Filtre ODSQL : période + types d'événement |
| `refine` | `location_city:<ville>` — filtre par localisation |
| `select` | 22 champs (voir §5), pour alléger la réponse |
| `order_by` | `firstdate_begin ASC` — pagination déterministe |
| `limit` | Taille de page, **100 maximum** |
| `offset` | Décalage, `offset + limit` **≤ 10 000** |

Réponse : `{"total_count": <int>, "results": [ … ]}`.

## 3. Filtres implémentés

### Localisation

`refine=location_city:Paris` plutôt qu'une clause ODSQL `location_city='Paris'` :
l'approche par facette évite l'échappement des apostrophes et fonctionne donc
sans traitement particulier pour des villes comme « L'Haÿ-les-Roses ».

### Période

```
lastdate_end >= date'<début>' and firstdate_begin <= date'<fin>'
```

Le filtre porte sur le **chevauchement**, pas sur la seule date de démarrage :
une exposition commencée avant la fenêtre mais toujours en cours reste
pertinente pour une recommandation. Effet mesuré sur Paris, septembre 2026:

| Filtre | Événements |
|---|---|
| Démarrant dans la fenêtre | 1 214 |
| **Chevauchant la fenêtre** | **1 450** |

La fenêtre couvre un historique et l'avenir : `[référence − history_days,
référence + period_days]`, soit un an d'historique et 90 jours à venir par
défaut — 9 839 événements pour Paris.

### Type d'événement

```
and (search("concert") or search("exposition"))
```

Le champ `category` du jeu **est vide sur 100 % des enregistrements**
(`where=category is not null` → 0 résultat) : il est inexploitable. Le filtre
s'appuie donc sur la recherche plein texte, qui couvre titre, description et
mots-clés, avec les types combinés en OU. Mesures sur Paris, 1 an d'historique
+ 90 jours : `concert` → 159 ; `concert or exposition` → 696.

## 4. Limites de l'API et stratégie de pagination

Les deux plafonds ont été vérifiés en provoquant l'erreur :

```
limit=101   → "Invalid value for limit API parameter: 101 was found
               but -1 <= limit <= 100 is expected."
offset=10000 (avec limit=1)
            → "Invalid value for sum of offset + limit API parameter:
               10001 was found but <= 10000 is expected."
```

Conséquence : une requête ne peut jamais ramener plus de 10 000 enregistrements.
La collecte est donc découpée en tranches **ville × fenêtre de 30 jours**
(`WINDOW_DAYS`), chacune paginée par pages de 100 sous le plafond d'offset. Si
une tranche sature malgré tout, un avertissement invite à réduire `WINDOW_DAYS`
plutôt que de tronquer silencieusement la collecte.

Un plafond global `MAX_EVENTS` borne le volume total et interrompt la collecte
dès qu'il est atteint.

## 5. Champs récupérés

22 champs, choisis pour couvrir le texte à vectoriser et les métadonnées de
citation :

- **Identité** : `uid`, `canonicalurl`, `originagenda_title`, `updatedat`
- **Contenu** : `title_fr`, `description_fr`, `longdescription_fr`,
  `conditions_fr`, `keywords_fr`
- **Dates** : `firstdate_begin`, `lastdate_end`
- **Lieu** : `location_name`, `location_address`, `location_city`,
  `location_postalcode`, `location_department`, `location_region`,
  `location_coordinates`
- **Public** : `age_min`, `age_max`, `accessibility_label_fr`, `attendancemode`

## 6. Robustesse

| Aspect | Comportement |
|---|---|
| Délai d'attente | 30 s par requête (`ODS_TIMEOUT`) |
| Nouvelles tentatives | 3 (`ODS_MAX_RETRIES`) |
| Codes retentés | 429, 500, 502, 503, 504, et erreurs de transport |
| Attente entre tentatives | Exponentielle : 1 s puis 2 s |
| Échec définitif | `RuntimeError` explicite, la collecte s'arrête |

Connexion HTTP réutilisée sur toute la collecte (`httpx.Client`).

## 7. Qualité des données remontées

Le jeu est alimenté par contribution : la collecte remonte le bruit tel quel, et
c'est `ingestion/preprocessing.py` qui le traite. Anomalies constatées :

| Anomalie | Exemple réel |
|---|---|
| HTML dans les descriptions | `<p>Le FIAP Paris est un Centre…</p>` |
| Contenu de test | `<p>lorem</p>` |
| Titre en Unicode stylisé | `𝑮𝒆́𝒐𝒍𝒐𝒈𝒊𝒆𝒔 𝒅𝒆 𝒍’𝒂𝒃𝒔𝒆𝒏𝒄𝒆` |
| Date de saisie aberrante | Événement daté du 26 mars **2503** |
| `keywords_fr` sérialisé en texte | `"['jazz', 'concert']"` |
| Champ multilingue brut | `attendancemode` = `{"id":1,"label":{"fr":"Sur place"}}` |
| Agendas hors périmètre culturel | « Mes événements France Travail » (35 sur 300) |

## 8. Paramètres de configuration

Tous surchargeables dans `.env` (voir `config.py`) :

| Variable | Défaut | Rôle |
|---|---|---|
| `ODS_BASE_URL` | `https://public.opendatasoft.com/api/explore/v2.1` | Racine de l'API |
| `ODS_DATASET_ID` | `evenements-publics-openagenda` | Jeu de données |
| `ODS_PAGE_SIZE` | 100 | Taille de page (plafond API) |
| `ODS_MAX_OFFSET` | 10 000 | Plafond `offset + limit` |
| `ODS_TIMEOUT` | 30.0 | Délai d'attente, en secondes |
| `ODS_MAX_RETRIES` | 3 | Tentatives par requête |
| `CITIES` | `["Paris"]` | Localisations collectées |
| `HISTORY_DAYS` | 365 | Profondeur d'historique |
| `PERIOD_DAYS` | 90 | Fenêtre à venir |
| `WINDOW_DAYS` | 30 | Découpage temporel des requêtes |
| `EVENT_TYPES` | `[]` | Types recherchés (vide = tous) |
| `MAX_EVENTS` | 2000 | Plafond global de collecte |

## 9. Requête de référence

Reproductible dans la console `https://public.opendatasoft.com/api-console/explore/v2.1/` :

```bash
curl -G "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/evenements-publics-openagenda/records" \
  --data-urlencode "where=lastdate_end >= date'2025-08-31' and firstdate_begin <= date'2026-11-29'" \
  --data-urlencode "refine=location_city:Paris" \
  --data-urlencode "order_by=firstdate_begin ASC" \
  --data-urlencode "limit=100" \
  --data-urlencode "offset=0"
```
