"""Tests fonctionnels de l'API REST.

Le système RAG est simulé : ces tests vérifient le contrat HTTP — validation des
entrées, codes de statut, forme des réponses, protection de l'administration —
sans dépendre d'un index construit ni consommer d'appels d'API.

Un test d'intégration réel contre un serveur lancé est décrit en fin de fichier.
"""

import pytest
from fastapi.testclient import TestClient

from puls_events_rag.api import main as api
from puls_events_rag.api.main import app

client = TestClient(app)

REPONSE_SIMULEE = {
    "answer": "**Django Lovers** — 1er octobre 2026, JASS CLUB (Paris). Jazz manouche.",
    "sources": [{
        "titre": "Django Lovers",
        "periode": "le 1 octobre 2026 à 17h30",
        "lieu": "JASS CLUB",
        "ville": "Paris",
        "url": "https://openagenda.com/jassclub-paris/events/django-lovers",
        "score": 0.422,
    }],
    "events_found": 1,
}


@pytest.fixture
def rag_simule(monkeypatch):
    """Remplace la chaîne RAG par une réponse figée."""
    appels = []

    def faux_answer(question, k=None):
        appels.append((question, k))
        return REPONSE_SIMULEE

    monkeypatch.setattr(api, "answer_question", faux_answer)
    return appels


# --- /health ------------------------------------------------------------------


def test_health_repond_toujours():
    """La sonde doit répondre même sans index, en le signalant."""
    reponse = client.get("/health")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["status"] == "ok"
    assert isinstance(corps["index_ready"], bool)


# --- /ask : cas nominal -------------------------------------------------------


def test_ask_retourne_reponse_et_sources(rag_simule):
    reponse = client.post("/ask", json={"question": "Quels concerts de jazz à Paris ?"})
    assert reponse.status_code == 200
    corps = reponse.json()
    assert "Django Lovers" in corps["answer"]
    assert corps["events_found"] == 1
    assert corps["sources"][0]["url"].startswith("https://openagenda.com/")


def test_ask_transmet_top_k(rag_simule):
    client.post("/ask", json={"question": "Une exposition à voir ?", "top_k": 3})
    assert rag_simule[-1][1] == 3


def test_ask_nettoie_les_espaces(rag_simule):
    client.post("/ask", json={"question": "   concert de jazz   "})
    assert rag_simule[-1][0] == "concert de jazz"


# --- /ask : entrées invalides -------------------------------------------------


@pytest.mark.parametrize("charge", [
    {},                                  # champ absent
    {"question": ""},                    # vide
    {"question": "ab"},                  # trop courte
    {"question": "     "},               # espaces seulement
    {"question": "x" * 501},             # trop longue
    {"question": "valide", "top_k": 0},  # hors bornes
    {"question": "valide", "top_k": 99},
])
def test_ask_rejette_les_entrees_invalides(charge):
    """FastAPI doit refuser avant d'atteindre le code métier."""
    assert client.post("/ask", json=charge).status_code == 422


def test_ask_refuse_le_json_malforme():
    reponse = client.post("/ask", content=b"pas du json",
                          headers={"Content-Type": "application/json"})
    assert reponse.status_code == 422


# --- /ask : pannes ------------------------------------------------------------


def test_ask_sans_index_repond_503(monkeypatch):
    def sans_index(question, k=None):
        raise FileNotFoundError("Aucun index dans data/index")

    monkeypatch.setattr(api, "answer_question", sans_index)
    reponse = client.post("/ask", json={"question": "concert de jazz"})
    assert reponse.status_code == 503
    assert "rebuild" in reponse.json()["detail"].lower()


def test_ask_ne_divulgue_pas_les_details_techniques(monkeypatch):
    """Une exception ne doit pas remonter au client : elle peut contenir une clé."""
    def panne(question, k=None):
        raise RuntimeError("Connexion refusée avec api_key=sk-secret-123")

    monkeypatch.setattr(api, "answer_question", panne)
    reponse = client.post("/ask", json={"question": "concert de jazz"})
    assert reponse.status_code == 502
    assert "sk-secret-123" not in reponse.text
    assert "api_key" not in reponse.text


# --- /rebuild : protection ----------------------------------------------------


def test_rebuild_ouvert_sans_jeton_configure(monkeypatch):
    """Mode POC local : pas de jeton configuré, pas d'authentification exigée."""
    monkeypatch.setattr(api.settings, "rebuild_token", "")
    monkeypatch.setattr(api, "answer_question", lambda *a, **k: REPONSE_SIMULEE)
    # On n'exécute pas la reconstruction : seule l'autorisation est testée.
    assert api.verifier_jeton(x_api_key=None) is None


def test_rebuild_exige_le_jeton_quand_il_est_configure(monkeypatch):
    monkeypatch.setattr(api.settings, "rebuild_token", "jeton-secret")
    reponse = client.post("/rebuild")
    assert reponse.status_code == 401

    reponse = client.post("/rebuild", headers={"X-API-Key": "mauvais-jeton"})
    assert reponse.status_code == 401


def test_rebuild_accepte_le_bon_jeton(monkeypatch):
    monkeypatch.setattr(api.settings, "rebuild_token", "jeton-secret")
    assert api.verifier_jeton(x_api_key="jeton-secret") is None


# --- Documentation ------------------------------------------------------------


def test_documentation_swagger_est_generee():
    assert client.get("/docs").status_code == 200

    schema = client.get("/openapi.json").json()
    assert "/ask" in schema["paths"]
    assert "/rebuild" in schema["paths"]
    assert schema["paths"]["/ask"]["post"]["description"]  # route documentée


def test_le_schema_ne_contient_aucun_secret():
    """La documentation publique ne doit exposer aucune valeur de configuration."""
    schema = client.get("/openapi.json").text
    from puls_events_rag.config import settings

    for secret in (settings.mistral_api_key, settings.rebuild_token):
        if secret:
            assert secret not in schema


# --- Intégration réelle (désactivé par défaut) --------------------------------


@pytest.mark.skip(reason="Nécessite un serveur lancé, un index construit et une clé Mistral")
def test_integration_serveur_reel():
    """Test de bout en bout contre un serveur en fonctionnement.

    Lancer d'abord :
        uv run python main.py
    puis retirer le décorateur skip.
    """
    import httpx

    base = "http://127.0.0.1:8000"
    assert httpx.get(f"{base}/health", timeout=10).json()["index_ready"]

    reponse = httpx.post(f"{base}/ask", timeout=60,
                         json={"question": "Quels concerts de jazz à Paris ?"})
    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps["answer"]) > 50
    assert corps["sources"]
    assert all(s["url"].startswith("https://openagenda.com/") for s in corps["sources"])
