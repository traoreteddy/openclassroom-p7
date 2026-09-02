"""API REST exposant le système RAG de recommandation d'événements.

La logique métier vit entièrement dans ``puls_events_rag.rag`` et
``puls_events_rag.vectorstore`` : ce module ne fait que l'exposer en HTTP,
valider les entrées et traduire les erreurs en codes de statut.

Lancement : uvicorn puls_events_rag.api.main:app --reload
Documentation interactive : http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import collections
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from puls_events_rag.api.schemas import (
    AskRequest,
    AskResponse,
    CorpusInfo,
    HealthResponse,
    IndexInfo,
    MetadataResponse,
    RebuildResponse,
    SourceAgenda,
)
from puls_events_rag.config import INDEX_DIR, PROCESSED_DATA_DIR, settings
from puls_events_rag.ingestion import open_agenda
from puls_events_rag.ingestion.open_agenda import fetch_events, save_raw_events
from puls_events_rag.ingestion.preprocessing import chunk_documents, clean_events
from puls_events_rag.rag.chain import answer_question, reset_cache
from puls_events_rag.vectorstore.faiss_store import build_index

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Charge l'index au démarrage plutôt qu'à la première question.

    Sans ce préchargement, le premier utilisateur paierait les ~580 ms de
    lecture de l'index en plus du temps de réponse habituel.
    """
    try:
        from puls_events_rag.rag.chain import _get_store

        _get_store()
        logger.info("Index chargé au démarrage")
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("Index indisponible au démarrage : %s", exc)
    yield


app = FastAPI(
    title="Puls-Events RAG API",
    description=(
        "Assistant de recommandation d'événements culturels.\n\n"
        "Les réponses sont générées par un modèle Mistral à partir des seuls "
        "événements Open Agenda indexés dans FAISS, et accompagnées de leurs "
        "sources vérifiables."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


def verifier_jeton(x_api_key: str | None = Header(default=None)) -> None:
    """Protège les endpoints d'administration.

    Tant que ``REBUILD_TOKEN`` n'est pas défini, l'endpoint reste ouvert : c'est
    le mode POC en local. Dès qu'un jeton est configuré, il devient obligatoire.
    La comparaison est faite en temps constant pour ne pas fuiter le jeton.
    """
    if not settings.rebuild_token:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.rebuild_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton d'administration invalide ou absent (en-tête X-API-Key).",
        )


@app.get("/health", response_model=HealthResponse, tags=["Service"])
def health() -> HealthResponse:
    """État du service et disponibilité de l'index.

    Utilisable comme sonde de vivacité : répond même sans index, en le signalant.
    """
    meta_path = INDEX_DIR / "index_meta.json"
    if not meta_path.exists():
        return HealthResponse(status="ok", index_ready=False)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return HealthResponse(
        status="ok",
        index_ready=True,
        chunks_indexed=meta.get("chunks"),
        embedding_provider=meta.get("embedding_provider"),
    )


@lru_cache(maxsize=1)
def _documents() -> list[dict]:
    """Documents nettoyés, lus une fois.

    Le fichier pèse plus d'un mégaoctet : le relire à chaque appel de /metadata
    coûterait plus cher que la recherche vectorielle elle-même.
    """
    chemin = PROCESSED_DATA_DIR / "documents.json"
    if not chemin.exists():
        return []
    return json.loads(chemin.read_text(encoding="utf-8"))


@app.get("/metadata", response_model=MetadataResponse, tags=["Service"])
def metadata(
    limit: int = Query(default=20, ge=1, le=200,
                       description="Nombre d'agendas source retournés"),
    offset: int = Query(default=0, ge=0, description="Rang du premier agenda retourné"),
) -> MetadataResponse:
    """Décrit le catalogue interrogeable : périmètre, volumétrie, sources.

    Destiné aux équipes produit et marketing : avant de se fier à une réponse,
    il faut savoir quelles villes et quelle période le catalogue couvre, et d'où
    viennent les événements.

    La liste des agendas source est paginée par `limit` et `offset` : le
    catalogue en compte plusieurs dizaines, et tout renvoyer alourdirait la
    réponse sans servir l'appelant.

    Codes d'erreur :
    - **503** : aucun corpus indexé — lancer `/rebuild` au préalable
    """
    documents = _documents()
    if not documents:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Aucun corpus indexé. Lancez /rebuild au préalable.",
        )

    meta_path = INDEX_DIR / "index_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    construit_le = (
        datetime.fromtimestamp(meta_path.stat().st_mtime, UTC).isoformat()
        if meta_path.exists() else None
    )

    metadonnees = [d["metadata"] for d in documents]
    debuts = sorted(m["date_debut"] for m in metadonnees if m.get("date_debut"))
    fins = sorted(m["date_fin"] for m in metadonnees if m.get("date_fin"))
    maintenant = datetime.now(UTC).isoformat()

    agendas = collections.Counter(m.get("agenda_source") or "(non précisé)"
                                  for m in metadonnees)
    classes = agendas.most_common()

    return MetadataResponse(
        index=IndexInfo(
            chunks=meta.get("chunks", 0),
            events=meta.get("documents", len(documents)),
            dimension=meta.get("dimension"),
            index_type=meta.get("index_type"),
            embedding_provider=meta.get("embedding_provider"),
            embedding_model=meta.get("embedding_model"),
            chunk_size=meta.get("chunk_size"),
            chunk_overlap=meta.get("chunk_overlap"),
            built_at=construit_le,
        ),
        corpus=CorpusInfo(
            cities=sorted({m["ville"] for m in metadonnees if m.get("ville")}),
            period_start=debuts[0] if debuts else None,
            period_end=fins[-1] if fins else None,
            events=len(documents),
            upcoming_events=sum(1 for f in fins if f >= maintenant),
            with_url=sum(1 for m in metadonnees if m.get("url")),
            with_coordinates=sum(1 for m in metadonnees if m.get("latitude") is not None),
        ),
        sources=[SourceAgenda(agenda=nom, events=n)
                 for nom, n in classes[offset : offset + limit]],
        sources_total=len(classes),
        limit=limit,
        offset=offset,
    )


@app.post("/ask", response_model=AskResponse, tags=["RAG"])
def ask(request: AskRequest) -> AskResponse:
    """Répond à une question sur les événements culturels indexés.

    Recherche les événements sémantiquement proches de la question dans l'index
    FAISS, puis demande au modèle Mistral de rédiger une recommandation à partir
    de ces seuls événements.

    La réponse est accompagnée des sources réellement utilisées, avec leur URL
    Open Agenda : l'utilisateur peut vérifier chaque événement cité.

    Codes d'erreur :
    - **422** : question absente, trop courte ou trop longue
    - **503** : index absent — lancer `/rebuild` ou `scripts/build_index.py`
    - **502** : le modèle de génération est injoignable
    """
    try:
        resultat = answer_question(request.question, k=request.top_k)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Aucun index vectoriel disponible. Lancez /rebuild au préalable.",
        ) from exc
    except ValueError as exc:
        # Clé d'API manquante ou index construit avec un autre fournisseur.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Échec de génération de la réponse")
        # Le détail de l'exception peut contenir des éléments de configuration :
        # on journalise côté serveur et on reste générique côté client.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Le service de génération est momentanément indisponible.",
        ) from exc

    return AskResponse(**resultat)


@app.post(
    "/rebuild",
    response_model=RebuildResponse,
    tags=["Administration"],
    dependencies=[Depends(verifier_jeton)],
)
def rebuild() -> RebuildResponse:
    """Reconstruit l'index vectoriel à partir de données fraîchement collectées.

    Enchaîne collecte Open Agenda, nettoyage, chunking, vectorisation et
    indexation, en suivant le périmètre défini dans la configuration
    (`CITIES`, `HISTORY_DAYS`, `PERIOD_DAYS`, `EVENT_TYPES`, `MAX_EVENTS`).

    Opération longue — de l'ordre de la minute — et coûteuse en appels d'API.
    Protégée par l'en-tête `X-API-Key` dès que `REBUILD_TOKEN` est configuré.

    Les caches de la chaîne RAG sont vidés à la fin : les questions suivantes
    utilisent le nouvel index sans redémarrage du service.

    Note : toutes les dépendances lourdes (FAISS, torch via les text splitters)
    sont importées au chargement du module, dans le thread principal. Les
    importer paresseusement dans ce handler — qui s'exécute dans un thread du
    pool FastAPI — provoquait un conflit OpenMP fatal entre les copies de
    libomp embarquées par faiss et par torch, et le serveur s'arrêtait.
    """
    depart = time.perf_counter()
    try:
        evenements = fetch_events()
        save_raw_events(evenements, params=open_agenda.DERNIER_PERIMETRE)
        documents = clean_events(evenements)
        chunks = chunk_documents(documents)
        if not chunks:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La collecte n'a produit aucun document : élargissez le périmètre.",
            )

        PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        (PROCESSED_DATA_DIR / "documents.json").write_text(
            json.dumps(documents, ensure_ascii=False, indent=2), encoding="utf-8")
        (PROCESSED_DATA_DIR / "chunks.json").write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

        build_index(chunks)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Échec de la reconstruction de l'index")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="La reconstruction a échoué. Consultez les journaux du serveur.",
        ) from exc

    reset_cache()
    _documents.cache_clear()
    return RebuildResponse(
        status="ok",
        events_collected=len(evenements),
        documents_indexed=len(documents),
        chunks_indexed=len(chunks),
        duration_seconds=round(time.perf_counter() - depart, 1),
    )
