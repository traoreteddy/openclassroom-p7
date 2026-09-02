"""Tests du script d'évaluation.

Portent sur les parties déterministes — chargement du jeu de test et métrique
de précision thématique — sans consommer d'appel d'API.
"""

import json
import sys
from pathlib import Path

import pytest
from langchain_core.documents import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))

from evaluate_rag import load_test_set, precision_thematique

JEU_DE_TEST = Path(__file__).resolve().parents[1] / "evaluation" / "test_set.json"


def evenement(titre: str, mots_cles=None, lieu="JASS CLUB", texte="") -> Document:
    return Document(
        page_content=texte,
        metadata={"titre": titre, "mots_cles": mots_cles or [], "lieu": lieu},
    )


# --- Jeu de test annoté --------------------------------------------------------


def test_jeu_de_test_livre_est_valide():
    """Le jeu versionné doit rester exploitable par le script."""
    jeu = load_test_set(JEU_DE_TEST)
    assert len(jeu) >= 10
    for cas in jeu:
        assert cas["question"] and cas["reference"]
        assert cas["categorie"] and cas["annotation"]
        assert cas["verite_terrain"], "chaque cas doit dire d'où vient sa référence"


def test_jeu_de_test_couvre_les_cas_limites():
    """Un jeu qui ne teste que les cas favorables ne prouve rien."""
    categories = {c["categorie"] for c in load_test_set(JEU_DE_TEST)}
    assert "hors domaine" in categories
    assert "hors périmètre géographique" in categories


def test_fichier_manquant_donne_une_consigne(tmp_path):
    with pytest.raises(FileNotFoundError, match="test_set.example.json"):
        load_test_set(tmp_path / "absent.json")


# --- Précision thématique ------------------------------------------------------


def test_tous_les_evenements_conformes():
    cas = {"critere_lexical": r"\bjazz\b"}
    documents = [evenement("Django Lovers", ["jazz"]), evenement("Jam Session Jazz")]
    assert precision_thematique(cas, documents) == 1.0


def test_evenements_partiellement_conformes():
    cas = {"critere_lexical": r"\bjazz\b"}
    documents = [
        evenement("Django Lovers", ["jazz"]),
        evenement("Exposition de peinture", ["art"], lieu="Galerie"),
    ]
    assert precision_thematique(cas, documents) == 0.5


def test_critere_cherche_dans_toutes_les_facettes():
    """Le critère doit pouvoir porter sur le lieu autant que sur le titre."""
    cas = {"critere_lexical": r"JASS CLUB"}
    assert precision_thematique(cas, [evenement("Soirée surprise")]) == 1.0


def test_question_sans_critere_n_est_pas_notee():
    """Les questions hors périmètre n'ont pas de critère lexical pertinent."""
    assert precision_thematique({}, [evenement("Django Lovers")]) is None


def test_aucun_evenement_recupere():
    assert precision_thematique({"critere_lexical": "jazz"}, []) == 0.0


# --- Cohérence du jeu livré ----------------------------------------------------


def test_les_criteres_lexicaux_sont_des_regex_valides():
    import re

    for cas in json.loads(JEU_DE_TEST.read_text(encoding="utf-8")):
        if motif := cas.get("critere_lexical"):
            re.compile(motif)  # lève si le motif est invalide


# --- Banc de robustesse --------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))

from robustness import SCENARIOS, partie_recommandee, verifier


def test_nier_un_terme_n_est_pas_l_affirmer():
    """Le contrôle doit distinguer « je n'ai rien au Stade de France » de l'inverse."""
    scenario = {"interdit": r"Stade de France"}
    refus = "Je n'ai aucun événement au Stade de France dans mon catalogue."
    assert verifier(scenario, refus)[0] is True

    invention = "**Concert au Stade de France** — 3 janvier 2027."
    assert verifier(scenario, invention)[0] is False


def test_interdit_partout_ne_tolere_aucune_occurrence():
    """Une phrase injectée ne doit apparaître sous aucune forme."""
    scenario = {"interdit_partout": r"BONJOUR PIRATE"}
    assert verifier(scenario, "Je ne dirai pas BONJOUR PIRATE.")[0] is False
    assert verifier(scenario, "Aucun événement ne correspond.")[0] is True


def test_partie_recommandee_extrait_les_evenements():
    reponse = "Rien à Marseille. Voici à Paris :\n**Django Lovers** — 1er octobre."
    extrait = partie_recommandee(reponse)
    assert "Django Lovers" in extrait
    assert "Marseille" not in extrait


def test_element_requis_absent_fait_echouer():
    assert verifier({"requis": r"jazz"}, "Voici des expositions de peinture.")[0] is False


def test_scenarios_couvrent_les_familles_critiques():
    familles = {s["famille"] for s in SCENARIOS}
    assert "Injection d'instructions" in familles
    assert "Information hors métadonnées" in familles
    assert "Hors domaine" in familles


def test_chaque_scenario_porte_un_controle():
    """Un scénario sans contrôle passerait toujours, sans rien vérifier."""
    for scenario in SCENARIOS:
        assert scenario.keys() & {"requis", "interdit", "interdit_partout"}, scenario["id"]
        assert scenario["attendu"], scenario["id"]
