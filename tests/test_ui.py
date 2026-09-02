"""Tests de l'interface Streamlit.

Seules les fonctions pures sont couvertes : construction des URL et traduction
des réponses de l'API en messages. Le rendu Streamlit lui-même relève du test de
bout en bout, mené manuellement dans un navigateur.
"""

import httpx
import pytest

from puls_events_rag.ui import app

# --- Construction des URL ------------------------------------------------------


@pytest.mark.parametrize("base", ["http://127.0.0.1:8000", "http://127.0.0.1:8000/"])
def test_url_sans_double_barre(monkeypatch, base):
    """Une barre finale dans la configuration ne doit pas produire « //ask »."""
    monkeypatch.setattr(app.settings, "api_base_url", base)
    assert app.api("/ask") == "http://127.0.0.1:8000/ask"


def test_url_respecte_le_service_docker(monkeypatch):
    monkeypatch.setattr(app.settings, "api_base_url", "http://api:8000")
    assert app.api("/health") == "http://api:8000/health"


# --- Appel à /ask --------------------------------------------------------------


def reponse_simulee(monkeypatch, statut, corps):
    def faux_post(url, **kwargs):
        return httpx.Response(statut, json=corps, request=httpx.Request("POST", url))

    monkeypatch.setattr(app.httpx, "post", faux_post)


def test_reponse_reussie_est_transmise(monkeypatch):
    attendu = {"answer": "Django Lovers…", "sources": [], "events_found": 3, "warnings": []}
    reponse_simulee(monkeypatch, 200, attendu)
    resultat, erreur, duree = app.poser_question("concert de jazz", 3)
    assert resultat == attendu
    assert erreur is None
    assert duree >= 0


def test_index_absent_donne_un_message_lisible(monkeypatch):
    reponse_simulee(monkeypatch, 503, {"detail": "Aucun index vectoriel disponible."})
    resultat, erreur, _ = app.poser_question("concert de jazz", 3)
    assert resultat is None
    assert "503" in erreur
    assert "Aucun index" in erreur


def test_erreur_de_validation_est_aplatie(monkeypatch):
    """FastAPI renvoie une liste d'erreurs : elle doit devenir une phrase."""
    reponse_simulee(monkeypatch, 422, {"detail": [
        {"msg": "String should have at least 3 characters"},
        {"msg": "Input should be greater than 0"},
    ]})
    _, erreur, _ = app.poser_question("ab", 3)
    assert "at least 3 characters" in erreur
    assert "greater than 0" in erreur


def test_api_injoignable_ne_leve_pas(monkeypatch):
    """L'interface doit rester utilisable quand l'API est arrêtée."""
    def faux_post(url, **kwargs):
        raise httpx.ConnectError("connexion refusée")

    monkeypatch.setattr(app.httpx, "post", faux_post)
    resultat, erreur, _ = app.poser_question("concert de jazz", 3)
    assert resultat is None
    assert "injoignable" in erreur


# --- Scénarios de démonstration -------------------------------------------------


def test_exemples_couvrent_les_scenarios_de_soutenance():
    questions = [q for _, q in app.EXEMPLES]
    assert any("jazz" in q.lower() for q in questions), "le cas nominal"
    assert any("marseille" in q.lower() for q in questions), "l'aveu de limite"
    assert all(len(q) >= 3 for q in questions), "chaque exemple doit passer la validation"
