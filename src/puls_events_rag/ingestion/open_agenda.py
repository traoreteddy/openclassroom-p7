"""Collecte des événements OpenAgenda, filtrés par localisation et par période.

Les données proviennent du jeu « Public events - OpenAgenda » exposé par l'API
Opendatasoft Explore v2.1 (https://public.opendatasoft.com) : ce sont les
événements publics OpenAgenda, accessibles sans clé d'API.

Deux contraintes de l'API dictent la stratégie de pagination :

- ``limit`` ne peut pas dépasser 100 ;
- ``offset + limit`` ne peut pas dépasser 10 000.

La collecte est donc découpée en tranches (ville × fenêtre temporelle), chacune
restant sous le plafond d'offset. Un événement est retenu s'il *chevauche* la
période demandée, et pas seulement s'il y démarre : une exposition commencée
avant la période mais toujours en cours reste pertinente.

La période couvre un historique (``history_days``, un an par défaut) et les
événements à venir (``period_days``). Un filtre optionnel par type d'événement
(``event_types``) s'appuie sur la recherche plein texte : le champ ``category``
du jeu est vide sur la totalité des enregistrements, il n'est donc pas
exploitable pour cet usage.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from puls_events_rag.config import RAW_DATA_DIR, settings

logger = logging.getLogger(__name__)

# Périmètre de la dernière collecte, repris dans le manifeste écrit sur disque.
DERNIER_PERIMETRE: dict = {}

# Champs récupérés : le strict nécessaire au texte à vectoriser et aux métadonnées.
FIELDS = [
    "uid",
    "title_fr",
    "description_fr",
    "longdescription_fr",
    "conditions_fr",
    "keywords_fr",
    "canonicalurl",
    "firstdate_begin",
    "lastdate_end",
    "location_name",
    "location_address",
    "location_city",
    "location_postalcode",
    "location_department",
    "location_region",
    "location_coordinates",
    "age_min",
    "age_max",
    "accessibility_label_fr",
    "attendancemode",
    "originagenda_title",
    "updatedat",
]


def _records_url() -> str:
    return f"{settings.ods_base_url}/catalog/datasets/{settings.ods_dataset_id}/records"


def _iter_windows(start: date, end: date, window_days: int):
    """Découpe [start, end] en fenêtres successives d'au plus ``window_days`` jours."""
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=window_days - 1), end)
        yield current, window_end
        current = window_end + timedelta(days=1)


def _where_clause(start: date, end: date, event_types: list[str] | None = None) -> str:
    """Filtre ODSQL : période chevauchant [start, end], et types d'événement optionnels."""
    clause = (
        f"lastdate_end >= date'{start.isoformat()}' "
        f"and firstdate_begin <= date'{end.isoformat()}'"
    )
    if event_types:
        # search() couvre titre, description et mots-clés ; les types sont en OU.
        types = " or ".join(f'search("{t}")' for t in event_types)
        clause += f" and ({types})"
    return clause


def _get(client: httpx.Client, params: dict) -> dict:
    """Appelle l'API avec quelques tentatives en cas d'erreur transitoire."""
    last_error: Exception | None = None
    for attempt in range(settings.ods_max_retries):
        try:
            response = client.get(_records_url(), params=params)
            if response.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}", request=response.request, response=response
                )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < settings.ods_max_retries - 1:
                delay = 2**attempt
                logger.warning("Appel API en échec (%s), nouvelle tentative dans %ss", exc, delay)
                time.sleep(delay)
    raise RuntimeError(f"API Opendatasoft injoignable après {settings.ods_max_retries} tentatives") from last_error


def _fetch_window(
    client: httpx.Client,
    city: str,
    start: date,
    end: date,
    budget: int,
    event_types: list[str] | None = None,
) -> list[dict]:
    """Récupère les événements d'une ville sur une fenêtre, en paginant."""
    collected: list[dict] = []
    offset = 0
    page_size = settings.ods_page_size

    while len(collected) < budget:
        if offset + page_size > settings.ods_max_offset:
            logger.warning(
                "Plafond d'offset atteint pour %s (%s → %s) : réduire window_days "
                "pour ne pas tronquer la collecte.",
                city, start, end,
            )
            break

        payload = _get(client, {
            "where": _where_clause(start, end, event_types),
            "refine": f"location_city:{city}",
            "select": ",".join(FIELDS),
            "order_by": "firstdate_begin ASC",
            "limit": min(page_size, budget - len(collected)),
            "offset": offset,
        })

        results = payload.get("results", [])
        collected.extend(results)
        total = payload.get("total_count", 0)
        offset += page_size
        if not results or offset >= total:
            break

    return collected


def fetch_events(
    cities: list[str] | None = None,
    period_days: int | None = None,
    history_days: int | None = None,
    event_types: list[str] | None = None,
    max_events: int | None = None,
    reference_date: date | None = None,
) -> list[dict]:
    """Récupère les événements bruts, filtrés par localisation, période et type.

    Args:
        cities: villes à collecter (défaut : ``settings.cities``).
        period_days: profondeur de la fenêtre à venir, en jours.
        history_days: profondeur d'historique, en jours (un an par défaut).
        event_types: types d'événement recherchés (vide = tous).
        max_events: plafond global d'événements collectés.
        reference_date: date pivot de la fenêtre (défaut : aujourd'hui).

    Returns:
        Liste d'événements bruts (dictionnaires JSON de l'API).
    """
    cities = cities or settings.cities
    period_days = settings.period_days if period_days is None else period_days
    history_days = settings.history_days if history_days is None else history_days
    event_types = settings.event_types if event_types is None else event_types
    max_events = max_events or settings.max_events
    reference = reference_date or datetime.now(UTC).date()
    start = reference - timedelta(days=history_days)
    end = reference + timedelta(days=period_days)

    logger.info(
        "Collecte : %s | %s → %s (historique %s j + à venir %s j) | types : %s | plafond %s",
        ", ".join(cities), start, end, history_days, period_days,
        ", ".join(event_types) if event_types else "tous", max_events,
    )

    # Le plafond est réparti entre les tranches, et non consommé par la première :
    # sans cela, une fenêtre dense (un mois de Journées du patrimoine) épuise le
    # budget et l'index ne contient plus aucun événement à venir.
    tranches = [
        (city, *fenetre)
        for city in cities
        for fenetre in _iter_windows(start, end, settings.window_days)
    ]

    # Un événement longue durée chevauche toutes les fenêtres de sa période et
    # revient donc dans chacune : la déduplication est faite ici, pour que le
    # budget achète des événements distincts et non des copies.
    events: list[dict] = []
    vus: set[str] = set()

    with httpx.Client(timeout=settings.ods_timeout) as client:
        for rang, (city, window_start, window_end) in enumerate(tranches):
            restant = max_events - len(events)
            if restant <= 0:
                logger.info("Plafond max_events atteint, collecte interrompue.")
                break
            # Part équitable du budget restant ; les tranches peu fournies
            # laissent mécaniquement leur reliquat aux suivantes.
            quota = -(-restant // (len(tranches) - rang))
            window = _fetch_window(client, city, window_start, window_end, quota, event_types)

            nouveaux = []
            for event in window:
                uid = str(event.get("uid"))
                if uid not in vus:
                    vus.add(uid)
                    nouveaux.append(event)

            logger.info(
                "  %s | %s → %s : %s nouveaux (%s reçus, quota %s)",
                city, window_start, window_end, len(nouveaux), len(window), quota,
            )
            events.extend(nouveaux)

    global DERNIER_PERIMETRE
    DERNIER_PERIMETRE = {
        "villes": cities,
        "debut": start.isoformat(),
        "fin": end.isoformat(),
        "history_days": history_days,
        "period_days": period_days,
        "window_days": settings.window_days,
        "types": event_types,
        "max_events": max_events,
    }
    logger.info("Collecte terminée : %s événements bruts.", len(events))
    return events


def save_raw_events(
    events: list[dict], path: Path | None = None, params: dict | None = None
) -> Path:
    """Persiste les événements bruts dans data/raw/ (horodatés).

    Un manifeste ``<fichier>.meta.json`` accompagne la collecte : sans lui, le
    périmètre réellement demandé (villes, fenêtre, types) serait perdu et les
    contrôles de cohérence en aval ne pourraient que le supposer.
    """
    path = path or RAW_DATA_DIR / f"events_{datetime.now(UTC):%Y%m%d_%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

    manifeste = {
        "collecte": f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%S%z}",
        "evenements": len(events),
        "source": {"base_url": settings.ods_base_url, "dataset": settings.ods_dataset_id},
        **(params or {}),
    }
    path.with_suffix(".meta.json").write_text(
        json.dumps(manifeste, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Événements bruts écrits dans %s", path)
    return path
