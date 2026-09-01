"""Nettoyage et structuration des événements avant vectorisation.

Le jeu OpenAgenda est ouvert à la contribution : il contient donc du bruit que
la collecte remonte tel quel. Les défauts observés sur les données réelles et
traités ici :

- descriptions au format HTML (``<p>…</p>``) et espaces insécables ;
- titres stylisés en caractères Unicode mathématiques, illisibles pour un
  modèle d'embedding (normalisation NFKC) ;
- dates de saisie aberrantes (un événement daté de l'an 2503) ;
- contenus de test (« lorem ») et descriptions vides ;
- doublons d'un même ``uid`` entre deux fenêtres de collecte ;
- agendas hors périmètre culturel (offres d'emploi, annuaires de structures).

Chaque événement retenu devient un document ``{"id", "text", "metadata"}`` :
``text`` est la chaîne qui sera vectorisée, ``metadata`` accompagne le chunk
dans l'index pour permettre de citer la source dans la réponse.
"""

from __future__ import annotations

import ast
import html
import json
import logging
import re
import unicodedata
from datetime import UTC, datetime

from langchain_text_splitters import RecursiveCharacterTextSplitter

from puls_events_rag.config import settings

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t  ]+")
_NEWLINE_RE = re.compile(r"\n{3,}")
_PLACEHOLDERS = {"lorem", "lorem ipsum", "test", "à venir", "a venir", "-"}
MIN_YEAR = 1970  # borne basse de plausibilité des dates saisies

MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _clean_text(value: str | None) -> str:
    """Retire le HTML, normalise l'Unicode et compacte les espaces."""
    if not value:
        return ""
    text = _TAG_RE.sub(" ", html.unescape(str(value)))
    # NFKC ramène les caractères stylisés (𝑮𝒆́𝒐…) à leur forme lisible.
    text = unicodedata.normalize("NFKC", text)
    text = _SPACE_RE.sub(" ", text)
    return _NEWLINE_RE.sub("\n\n", text).strip()


def _parse_keywords(value: str | None) -> list[str]:
    """``keywords_fr`` arrive sous forme de liste sérialisée en texte."""
    if not value:
        return []
    raw = value
    if isinstance(value, str) and value.startswith("["):
        try:
            raw = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            raw = [value]
    items = raw if isinstance(raw, list) else [raw]
    return [k for k in (_clean_text(str(i)) for i in items) if k]


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # fromisoformat gère le suffixe « Z » depuis Python 3.11.
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _is_plausible(moment: datetime | None) -> bool:
    """Écarte les dates de saisie manifestement erronées (ex. un événement en 2503).

    Ce contrôle ne filtre pas la période demandée — c'est le rôle de la requête
    de collecte. Un événement démarré il y a plusieurs années mais toujours en
    cours (exposition permanente, festival pluriannuel) reste valide.
    """
    if moment is None:
        return False
    return MIN_YEAR <= moment.year <= datetime.now(UTC).year + settings.max_years_ahead


def _format_period(begin: datetime | None, end: datetime | None) -> str:
    """Formule la période en français, pour que le LLM puisse la citer telle quelle."""
    if begin is None:
        return ""
    debut = f"{begin.day} {MOIS[begin.month - 1]} {begin.year}"
    if end is None or end.date() == begin.date():
        return f"le {debut} à {begin:%Hh%M}"
    fin = f"{end.day} {MOIS[end.month - 1]} {end.year}"
    return f"du {debut} au {fin}"


def _format_age(age_min: int | None, age_max: int | None) -> str:
    """Formule la tranche d'âge, en tolérant une borne manquante."""
    if age_min is not None and age_max is not None:
        return f"de {age_min} à {age_max} ans"
    if age_min is not None:
        return f"à partir de {age_min} ans"
    if age_max is not None:
        return f"jusqu'à {age_max} ans"
    return ""


def _label_fr(value) -> str:
    """Extrait le libellé français d'un champ multilingue (``attendancemode``)."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return _clean_text(value)
    if isinstance(value, dict):
        label = value.get("label", {})
        if isinstance(label, dict):
            return _clean_text(label.get("fr") or next(iter(label.values()), ""))
        return _clean_text(label)
    return _clean_text(str(value))


def _build_text(event: dict, keywords: list[str], periode: str) -> str:
    """Compose le texte vectorisé : un bloc lisible, champs nommés explicitement."""
    lieu = ", ".join(
        p for p in (
            _clean_text(event.get("location_name")),
            _clean_text(event.get("location_address")),
        ) if p
    )
    description = _clean_text(event.get("longdescription_fr")) or _clean_text(
        event.get("description_fr")
    )

    lignes = [f"Événement : {_clean_text(event.get('title_fr'))}"]
    if periode:
        lignes.append(f"Date : {periode}")
    if lieu:
        lignes.append(f"Lieu : {lieu}")
    if event.get("location_city"):
        ville = _clean_text(event.get("location_city"))
        code = _clean_text(event.get("location_postalcode"))
        lignes.append(f"Ville : {ville}{f' ({code})' if code else ''}")
    if keywords:
        lignes.append(f"Mots-clés : {', '.join(keywords)}")
    public = _format_age(event.get("age_min"), event.get("age_max"))
    if public:
        lignes.append(f"Public : {public}")
    acces = _parse_keywords(event.get("accessibility_label_fr"))
    if acces:
        lignes.append(f"Accessibilité : {', '.join(acces)}")
    conditions = _clean_text(event.get("conditions_fr"))
    if conditions:
        lignes.append(f"Conditions : {conditions}")
    lignes.append(f"Description : {description}")
    return "\n".join(lignes)


def clean_events(raw_events: list[dict]) -> list[dict]:
    """Nettoie les événements bruts et retourne des documents prêts au chunking.

    Args:
        raw_events: événements bruts issus de :func:`fetch_events`.

    Returns:
        Documents ``{"id", "text", "metadata"}``, dédoublonnés et triés par date.
    """
    documents: dict[str, dict] = {}
    rejets = {"sans_uid": 0, "date_aberrante": 0, "description_courte": 0, "agenda_exclu": 0}

    for event in raw_events:
        uid = event.get("uid")
        if not uid:
            rejets["sans_uid"] += 1
            continue

        agenda = _clean_text(event.get("originagenda_title"))
        if agenda in settings.excluded_agendas:
            rejets["agenda_exclu"] += 1
            continue

        begin = _parse_date(event.get("firstdate_begin"))
        end = _parse_date(event.get("lastdate_end"))
        if not _is_plausible(begin) or (end is not None and not _is_plausible(end)):
            rejets["date_aberrante"] += 1
            continue

        description = _clean_text(event.get("longdescription_fr")) or _clean_text(
            event.get("description_fr")
        )
        if (
            len(description) < settings.min_description_length
            or description.lower() in _PLACEHOLDERS
        ):
            rejets["description_courte"] += 1
            continue

        keywords = _parse_keywords(event.get("keywords_fr"))
        periode = _format_period(begin, end)
        coords = event.get("location_coordinates") or {}

        documents[str(uid)] = {
            "id": str(uid),
            "text": _build_text(event, keywords, periode),
            "metadata": {
                "uid": str(uid),
                "titre": _clean_text(event.get("title_fr")),
                "url": event.get("canonicalurl") or "",
                "date_debut": begin.isoformat() if begin else "",
                "date_fin": end.isoformat() if end else "",
                "periode": periode,
                "lieu": _clean_text(event.get("location_name")),
                "adresse": _clean_text(event.get("location_address")),
                "ville": _clean_text(event.get("location_city")),
                "code_postal": _clean_text(event.get("location_postalcode")),
                "departement": _clean_text(event.get("location_department")),
                "region": _clean_text(event.get("location_region")),
                "latitude": coords.get("lat"),
                "longitude": coords.get("lon"),
                "mots_cles": keywords,
                "agenda_source": agenda,
                "modalite": _label_fr(event.get("attendancemode")),
                "accessibilite": _parse_keywords(event.get("accessibility_label_fr")),
                "age_min": event.get("age_min"),
                "age_max": event.get("age_max"),
            },
        }

    retenus = sorted(documents.values(), key=lambda d: d["metadata"]["date_debut"])
    doublons = len(raw_events) - sum(rejets.values()) - len(retenus)
    logger.info(
        "Nettoyage : %s bruts → %s documents (%s doublons, rejets : %s)",
        len(raw_events), len(retenus), doublons, rejets,
    )
    return retenus


def chunk_documents(documents: list[dict]) -> list[dict]:
    """Découpe les documents en chunks, en conservant les métadonnées de l'événement.

    La taille et le chevauchement viennent de la configuration
    (``chunk_size`` / ``chunk_overlap``). Les événements courts tiennent en un
    seul chunk ; les longues descriptions sont découpées et chaque morceau
    conserve l'identité de son événement (``uid``, ``chunk_index``).
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[dict] = []
    for document in documents:
        morceaux = splitter.split_text(document["text"])
        for index, morceau in enumerate(morceaux):
            chunks.append({
                "id": f"{document['id']}::{index}",
                "text": morceau,
                "metadata": {
                    **document["metadata"],
                    "chunk_index": index,
                    "chunk_total": len(morceaux),
                },
            })

    logger.info("Chunking : %s documents → %s chunks", len(documents), len(chunks))
    return chunks
