"""Tests de la collecte et de la structuration des événements.

Ces tests fonctionnent hors ligne : les cas de test reprennent les anomalies
réellement observées dans le jeu OpenAgenda (HTML, titres en Unicode stylisé,
date en l'an 2503, contenu « lorem », doublons).
"""

from datetime import date
from itertools import pairwise

import pytest

from puls_events_rag.ingestion.open_agenda import _iter_windows, _where_clause
from puls_events_rag.ingestion.preprocessing import chunk_documents, clean_events


def evenement(**overrides) -> dict:
    """Événement brut valide, personnalisable par les tests."""
    base = {
        "uid": "1",
        "title_fr": "Concert de jazz",
        "description_fr": "Un concert de jazz au cœur de Paris avec un quartet international.",
        "longdescription_fr": None,
        "conditions_fr": "Entrée libre",
        "keywords_fr": "['jazz', 'concert']",
        "canonicalurl": "https://openagenda.com/agenda/events/concert-jazz",
        "firstdate_begin": "2026-09-12T18:00:00+00:00",
        "lastdate_end": "2026-09-12T21:00:00+00:00",
        "location_name": "Le Duc des Lombards",
        "location_address": "42 rue des Lombards, 75001 Paris",
        "location_city": "Paris",
        "location_postalcode": "75001",
        "location_coordinates": {"lat": 48.85, "lon": 2.34},
        "age_min": 12,
        "age_max": None,
        "accessibility_label_fr": "['handicap moteur']",
        "attendancemode": '{"id": 1, "label": {"fr": "Sur place", "en": "In situ"}}',
        "originagenda_title": "Agenda culturel",
    }
    return {**base, **overrides}


# --- Filtrage par période et par localisation ---------------------------------


def test_where_clause_selectionne_les_evenements_qui_chevauchent_la_periode():
    """Un événement déjà commencé mais toujours en cours doit être retenu."""
    clause = _where_clause(date(2026, 9, 1), date(2026, 9, 30))
    assert "lastdate_end >= date'2026-09-01'" in clause
    assert "firstdate_begin <= date'2026-09-30'" in clause


def test_decoupage_temporel_couvre_toute_la_periode_sans_recouvrement():
    """Le découpage contourne le plafond d'offset de l'API sans perdre de jours."""
    fenetres = list(_iter_windows(date(2026, 1, 1), date(2026, 3, 1), window_days=30))
    assert fenetres[0] == (date(2026, 1, 1), date(2026, 1, 30))
    assert fenetres[-1][1] == date(2026, 3, 1)
    for precedente, suivante in pairwise(fenetres):
        assert (suivante[0] - precedente[1]).days == 1


def test_le_plafond_est_reparti_entre_les_tranches(monkeypatch):
    """Une fenêtre dense ne doit pas absorber tout le budget de collecte."""
    from puls_events_rag.ingestion import open_agenda

    appels: list[tuple] = []

    def faux_fetch(client, city, start, end, budget, event_types=None):
        appels.append((start, budget))
        return [{"uid": f"{start}-{i}"} for i in range(budget)]  # tranche toujours saturée

    monkeypatch.setattr(open_agenda, "_fetch_window", faux_fetch)
    monkeypatch.setattr(open_agenda.settings, "window_days", 30)

    evenements = open_agenda.fetch_events(
        cities=["Paris"], history_days=60, period_days=30, max_events=90,
        reference_date=date(2026, 9, 1),
    )

    assert len(evenements) == 90
    assert len(appels) >= 3, "la collecte doit couvrir plusieurs fenêtres, pas une seule"
    assert all(budget < 90 for _, budget in appels), "aucune tranche ne prend tout le budget"


def test_evenements_longue_duree_ne_sont_pas_collectes_en_double(monkeypatch):
    """Un événement chevauchant plusieurs fenêtres ne doit être retenu qu'une fois."""
    from puls_events_rag.ingestion import open_agenda

    permanent = {"uid": "expo-permanente", "title_fr": "Exposition permanente"}

    def faux_fetch(client, city, start, end, budget, event_types=None):
        # L'API renvoie l'événement permanent dans chaque fenêtre, plus un unique.
        return [permanent, {"uid": f"ponctuel-{start}"}][:budget]

    monkeypatch.setattr(open_agenda, "_fetch_window", faux_fetch)
    monkeypatch.setattr(open_agenda.settings, "window_days", 30)

    evenements = open_agenda.fetch_events(
        cities=["Paris"], history_days=60, period_days=30, max_events=100,
        reference_date=date(2026, 9, 1),
    )

    uids = [e["uid"] for e in evenements]
    assert uids.count("expo-permanente") == 1
    assert len(uids) == len(set(uids))


# --- Nettoyage ----------------------------------------------------------------


def test_html_et_entites_sont_retires():
    brut = "<p>Un <b>concert</b> &amp; une exposition au Palais de la découverte.</p>"
    doc = clean_events([evenement(longdescription_fr=brut)])[0]
    assert "<p>" not in doc["text"] and "<b>" not in doc["text"]
    assert "Un concert & une exposition au Palais de la découverte." in doc["text"]


def test_titre_en_unicode_stylise_est_normalise():
    """Les titres en caractères mathématiques sont illisibles pour un embedding."""
    doc = clean_events([evenement(title_fr="𝑮𝒆́𝒐𝒍𝒐𝒈𝒊𝒆𝒔")])[0]
    assert "Géologies" in doc["metadata"]["titre"]


def test_date_aberrante_est_rejetee():
    """Un événement daté de l'an 2503 est une erreur de saisie de la source."""
    assert clean_events([evenement(firstdate_begin="2503-03-26T13:00:00+00:00")]) == []


def test_evenement_longue_duree_est_conserve():
    """Une exposition démarrée en 2021 et toujours en cours reste pertinente."""
    docs = clean_events([evenement(
        firstdate_begin="2021-06-26T12:20:00+00:00",
        lastdate_end="2026-12-19T14:20:00+00:00",
    )])
    assert len(docs) == 1
    assert docs[0]["metadata"]["periode"] == "du 26 juin 2021 au 19 décembre 2026"


@pytest.mark.parametrize("description", ["lorem", "", "court"])
def test_description_non_exploitable_est_rejetee(description):
    assert clean_events([evenement(description_fr=description, longdescription_fr=None)]) == []


def test_agenda_hors_perimetre_est_exclu():
    """Le jeu OpenAgenda mêle des offres d'emploi aux événements culturels."""
    hors_sujet = evenement(originagenda_title="Mes événements France Travail")
    assert clean_events([hors_sujet]) == []


def test_doublons_dedupliques_sur_uid():
    docs = clean_events([evenement(uid="42"), evenement(uid="42"), evenement(uid="43")])
    assert sorted(d["id"] for d in docs) == ["42", "43"]


# --- Structuration ------------------------------------------------------------


def test_document_structure_pour_la_base_vectorielle():
    doc = clean_events([evenement()])[0]
    assert set(doc) == {"id", "text", "metadata"}
    for champ in ("Événement :", "Date :", "Lieu :", "Ville :", "Description :"):
        assert champ in doc["text"]


def test_metadonnees_permettent_de_citer_la_source():
    meta = clean_events([evenement()])[0]["metadata"]
    assert meta["url"].startswith("https://openagenda.com/")
    assert meta["ville"] == "Paris"
    assert meta["periode"] == "le 12 septembre 2026 à 18h00"
    assert (meta["latitude"], meta["longitude"]) == (48.85, 2.34)
    assert meta["mots_cles"] == ["jazz", "concert"]
    assert meta["modalite"] == "Sur place"


def test_borne_d_age_manquante_ne_produit_pas_de_none():
    doc = clean_events([evenement(age_min=15, age_max=None)])[0]
    assert "Public : à partir de 15 ans" in doc["text"]
    assert "None" not in doc["text"]


def test_documents_tries_par_date_de_debut():
    docs = clean_events([
        evenement(uid="tard", firstdate_begin="2026-10-01T10:00:00+00:00"),
        evenement(uid="tot", firstdate_begin="2026-09-01T10:00:00+00:00"),
    ])
    assert [d["id"] for d in docs] == ["tot", "tard"]


# --- Chunking -----------------------------------------------------------------


def test_chunks_respectent_la_taille_configuree():
    from puls_events_rag.config import settings

    docs = clean_events([evenement(longdescription_fr="Une description très détaillée. " * 80)])
    chunks = chunk_documents(docs)
    assert len(chunks) > 1
    assert all(len(c["text"]) <= settings.chunk_size for c in chunks)


def test_chaque_chunk_conserve_l_identite_de_son_evenement():
    chunks = chunk_documents(clean_events([evenement(uid="99")]))
    assert all(c["metadata"]["uid"] == "99" for c in chunks)
    assert all(c["id"].startswith("99::") for c in chunks)
    assert chunks[0]["metadata"]["chunk_total"] == len(chunks)
