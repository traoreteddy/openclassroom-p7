"""Évaluation du système RAG sur le jeu de test annoté, avec Ragas.

Interroge le système sur chaque question du jeu de test, puis mesure la qualité
des réponses avec quatre métriques Ragas, un modèle Mistral servant de juge :

- **faithfulness** : la réponse est-elle étayée par les extraits récupérés ?
  C'est la métrique anti-hallucination : elle vérifie que chaque affirmation
  découle du contexte, indépendamment de la réponse attendue.
- **answer_relevancy** : la réponse traite-t-elle bien la question posée ?
- **context_precision** : les extraits récupérés sont-ils pertinents, ou noyés
  dans du bruit ? Elle évalue le retriever, pas le générateur.
- **context_recall** : les extraits contiennent-ils tout ce qu'exige la réponse
  de référence ? Un rappel faible signale un problème d'indexation ou de
  découpage, pas de génération.

Usage :
    python evaluation/evaluate_rag.py
    python evaluation/evaluate_rag.py --test-set evaluation/test_set.json --limit 3

Chaque exécution consomme des appels d'API : une réponse par question, plus
plusieurs appels de jugement par métrique et par question.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
import warnings
from datetime import UTC, datetime
from pathlib import Path

warnings.filterwarnings("ignore")

EVALUATION_DIR = Path(__file__).resolve().parent
DEFAULT_TEST_SET = EVALUATION_DIR / "test_set.json"
RESULTS_DIR = EVALUATION_DIR / "results"

# Seuils d'acceptation du POC, à ajuster au vu des premières mesures.
SEUILS = {
    "faithfulness": 0.80,
    "answer_relevancy": 0.70,
    "semantic_similarity": 0.75,
    "llm_context_precision_with_reference": 0.60,
    "context_recall": 0.60,
}

logger = logging.getLogger("evaluation")


def _normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation, espaces compactés."""
    texte = unicodedata.normalize("NFD", texte.lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w\s]", " ", texte).split())


def exact_match(reponse: str, reference: str) -> float:
    """Correspondance exacte entre la réponse et la référence, après normalisation.

    Métrique stricte, empruntée aux tâches de question-réponse extractive. Sur des
    réponses génératives libres, elle vaut quasi systématiquement 0 : deux
    formulations d'une même recommandation ne coïncident jamais caractère pour
    caractère. Elle est calculée et rapportée telle quelle, comme point de
    comparaison qui montre justement pourquoi les métriques sémantiques sont
    nécessaires ici. Voir :func:`exact_match_faits` pour la variante utile.
    """
    return float(_normaliser(reponse) == _normaliser(reference))


def exact_match_faits(reponse: str, reference: str) -> float:
    """Part des faits saisissables de la référence repris à l'identique.

    Les faits retenus sont ceux qu'une réponse ne peut pas paraphraser sans se
    tromper : les dates (« 1er octobre 2026 ») et les nombres. Contrairement à
    l'Exact Match strict, cette variante tolère la reformulation tout en
    vérifiant que les informations factuelles coïncident.
    """
    faits = set(re.findall(
        r"\b\d{1,2}(?:er)?\s+(?:janvier|février|mars|avril|mai|juin|juillet|"
        r"août|septembre|octobre|novembre|décembre)\s+\d{4}\b",
        _normaliser(reference),
    ))
    if not faits:
        return float("nan")
    presents = sum(1 for f in faits if f in _normaliser(reponse))
    return presents / len(faits)


CLASSIFICATION_PROMPT = """\
Tu évalues la réponse d'un assistant de recommandation d'événements culturels.

Une réponse est CORRECTE si elle a le même sens et porte les mêmes informations
utiles que la référence, au regard de la consigne d'annotation.

Deux règles impératives, sans lesquelles ton verdict serait faux :

1. PLURALITÉ DES BONNES RÉPONSES. Le catalogue contient des dizaines
   d'événements de chaque type. Citer d'autres événements que ceux de la
   référence n'est PAS une erreur, dès lors qu'ils satisfont la demande. Ne
   compare pas les listes : vérifie que les événements cités répondent bien à
   la question.

2. REFUS LÉGITIME. Quand la consigne d'annotation attend que l'assistant signale
   l'absence de correspondance, une réponse qui le fait est CORRECTE. Proposer
   en complément des événements proches, en précisant qu'ils diffèrent de la
   demande, reste correct : ce n'est pas une erreur mais le comportement voulu.

Classe INCORRECTE uniquement si la réponse affirme une information fausse,
invente un événement absent du catalogue, ou ignore la consigne d'annotation.
Classe PARTIELLEMENT si une part de la demande reste sans réponse.

Réponds par un seul mot parmi : correcte, partiellement, incorrecte
Puis, après un point-virgule, une justification d'une phrase.

QUESTION : {question}
RÉFÉRENCE HUMAINE : {reference}
CONSIGNE D'ANNOTATION : {annotation}
RÉPONSE DE L'ASSISTANT : {reponse}

Verdict :"""


def classifier_reponse(juge, cas: dict, reponse: str) -> dict:
    """Classe la réponse en correcte / partiellement correcte / incorrecte.

    La mission prévoit une classification manuelle. Elle est ici produite
    automatiquement par le modèle juge, et le rapport réserve un champ
    ``classification_humaine`` vide : un relecteur peut confirmer ou corriger
    chaque verdict, la classification automatique servant de première passe.
    """
    sortie = juge.invoke(CLASSIFICATION_PROMPT.format(
        question=cas["question"],
        reference=cas["reference"],
        annotation=cas.get("annotation", ""),
        reponse=reponse,
    ))
    texte = (sortie.content if hasattr(sortie, "content") else str(sortie)).strip()
    verdict, _, justification = texte.partition(";")
    verdict = _normaliser(verdict).split()[0] if verdict.strip() else "indetermine"
    etiquettes = {"correcte": "correcte", "partiellement": "partiellement correcte",
                  "incorrecte": "incorrecte"}
    return {
        "classification_auto": etiquettes.get(verdict, "indéterminée"),
        "justification": justification.strip()[:300],
        "classification_humaine": "",
    }


def precision_thematique(cas: dict, documents) -> float | None:
    """Part des événements récupérés qui satisfont le critère de la question.

    Les métriques Ragas de contexte comparent les extraits récupérés à *une*
    réponse de référence. Or une question de recommandation admet une multitude
    de réponses correctes : sur 35 concerts de jazz au catalogue, le système en
    renvoie cinq, tous pertinents, mais rarement ceux que l'annotation cite.
    Ragas y voit un défaut de rappel là où il n'y en a pas.

    Cette métrique contourne le problème en vérifiant une propriété plutôt
    qu'une liste : chaque événement récupéré satisfait-il le critère lexical de
    la question ? Elle est déterministe et ne consomme aucun appel d'API.

    Returns:
        La proportion d'événements conformes, ou ``None`` si la question ne se
        prête pas à un critère lexical (questions hors périmètre).
    """
    motif = cas.get("critere_lexical")
    if not motif:
        return None
    regex = re.compile(motif, re.IGNORECASE)
    conformes = sum(
        1 for d in documents
        if regex.search(f"{d.metadata.get('titre', '')} "
                        f"{' '.join(d.metadata.get('mots_cles') or [])} "
                        f"{d.metadata.get('lieu', '')} {d.page_content}")
    )
    return conformes / len(documents) if documents else 0.0


def make_juge():
    """Construit le modèle juge, en contournant un bogue de langchain-mistralai.

    ``ResponseRelevancy`` demande plusieurs générations pour une même entrée.
    LangChain agrège alors les compteurs de jetons via
    ``ChatMistralAI._combine_llm_outputs``, qui fait ``overall[k] += v`` sans
    vérifier le type de ``v``. Or l'API Mistral renvoie des sous-dictionnaires
    (détail des jetons de prompt), d'où un ``TypeError`` qui fait échouer la
    métrique et la laisse à NaN.

    L'agrégation est donc réécrite pour ne sommer que les valeurs numériques.
    """
    from langchain_mistralai import ChatMistralAI

    from puls_events_rag.config import settings

    class ChatMistralAIJuge(ChatMistralAI):
        def _combine_llm_outputs(self, llm_outputs: list[dict | None]) -> dict:
            total: dict = {}
            for sortie in llm_outputs:
                if not sortie:
                    continue
                for cle, valeur in (sortie.get("token_usage") or {}).items():
                    if isinstance(valeur, int | float):
                        total[cle] = total.get(cle, 0) + valeur
            return {"token_usage": total, "model_name": self.model}

    return ChatMistralAIJuge(
        model=settings.llm_model,
        api_key=settings.mistral_api_key,
        temperature=0.0,  # un juge doit être reproductible
    )


def load_test_set(path: Path = DEFAULT_TEST_SET) -> list[dict]:
    """Charge le jeu de test annoté.

    Chaque entrée porte une ``question``, une ``reference`` rédigée à la main à
    partir du catalogue réellement indexé, et une ``categorie`` qui permet de
    lire les résultats par type de scénario.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Jeu de test introuvable : {path}. Voir test_set.example.json pour le format."
        )
    jeu = json.loads(path.read_text(encoding="utf-8"))
    logger.info("Jeu de test : %s questions (%s)", len(jeu), path.name)
    return jeu


def run_evaluation(test_set: list[dict]) -> list[dict]:
    """Interroge le système RAG sur chaque question et collecte réponses et contextes.

    Les contextes retenus sont ceux effectivement transmis au modèle : c'est sur
    eux que portent les métriques de fidélité et de pertinence du contexte.
    """
    from puls_events_rag.rag.chain import (
        answer_question,
        format_context_blocks,
        retrieve_events,
    )

    juge = make_juge()
    resultats = []
    for numero, cas in enumerate(test_set, start=1):
        question = cas["question"]
        logger.info("[%s/%s] %s", numero, len(test_set), question)

        documents = retrieve_events(question)
        reponse = answer_question(question)

        resultats.append({
            "precision_thematique": precision_thematique(cas, documents),
            "exact_match": exact_match(reponse["answer"], cas["reference"]),
            "exact_match_faits": exact_match_faits(reponse["answer"], cas["reference"]),
            **classifier_reponse(juge, cas, reponse["answer"]),
            "id": cas.get("id", f"q{numero}"),
            "categorie": cas.get("categorie", ""),
            "question": question,
            "reference": cas["reference"],
            "annotation": cas.get("annotation", ""),
            "response": reponse["answer"],
            # Les contextes soumis à Ragas doivent être ceux vus par le modèle :
            # le page_content brut d'un chunk ne porte ni le titre ni la date.
            "retrieved_contexts": format_context_blocks(documents),
            "sources": reponse["sources"],
        })
    return resultats


def compute_metrics(resultats: list[dict]) -> dict:
    """Calcule les métriques Ragas, avec Mistral comme juge.

    Returns:
        ``{"global": {métrique: score}, "par_question": [...]}``
    """
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
        SemanticSimilarity,
    )

    from puls_events_rag.vectorstore.embeddings import get_embedding_model

    juge = LangchainLLMWrapper(make_juge())
    embeddings = LangchainEmbeddingsWrapper(get_embedding_model())

    dataset = EvaluationDataset(samples=[
        SingleTurnSample(
            user_input=r["question"],
            response=r["response"],
            retrieved_contexts=r["retrieved_contexts"],
            reference=r["reference"],
        )
        for r in resultats
    ])

    logger.info("Évaluation Ragas sur %s échantillons (juge : Mistral)…", len(dataset))
    scores = evaluate(
        dataset=dataset,
        metrics=[
            Faithfulness(),
            ResponseRelevancy(),
            SemanticSimilarity(),
            LLMContextPrecisionWithReference(),
            LLMContextRecall(),
        ],
        llm=juge,
        embeddings=embeddings,
    )

    par_question = scores.to_pandas().to_dict(orient="records")
    globales = {
        colonne: float(valeur)
        for colonne, valeur in scores.to_pandas().mean(numeric_only=True).items()
    }
    return {"global": globales, "par_question": par_question}


def save_report(resultats: list[dict], metriques: dict, output_dir: Path = RESULTS_DIR) -> Path:
    """Persiste le détail par question et la synthèse des métriques."""
    output_dir.mkdir(parents=True, exist_ok=True)
    chemin = output_dir / f"evaluation_{datetime.now(UTC):%Y%m%d_%H%M%S}.json"

    rapport = {
        "date": f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%S%z}",
        "questions": len(resultats),
        "metriques_globales": {
            **metriques["global"],
            "exact_match": sum(r["exact_match"] for r in resultats) / len(resultats),
            "classification": {
                e: sum(1 for r in resultats if r["classification_auto"] == e)
                for e in {r["classification_auto"] for r in resultats}
            },
            "precision_thematique": (
                sum(r["precision_thematique"] for r in resultats
                    if r["precision_thematique"] is not None)
                / max(1, sum(1 for r in resultats if r["precision_thematique"] is not None))
            ),
        },
        "seuils": SEUILS,
        "detail": [
            {
                **{k: r[k] for k in ("id", "categorie", "question", "reference",
                                     "annotation", "response", "sources",
                                     "precision_thematique", "exact_match",
                                     "exact_match_faits", "classification_auto",
                                     "justification", "classification_humaine")},
                "scores": {
                    m: mesure.get(m)
                    for mesure in [metriques["par_question"][i]]
                    for m in SEUILS
                    if m in mesure
                },
            }
            for i, r in enumerate(resultats)
        ],
    }
    chemin.write_text(json.dumps(rapport, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    return chemin


def afficher_synthese(metriques: dict, resultats: list[dict]) -> bool:
    """Affiche les scores et retourne True si tous les seuils sont tenus."""
    print(f"\n{'=' * 72}\nSYNTHÈSE\n{'=' * 72}")
    print(f"{'Métrique':<42}{'Score':>10}{'Seuil':>10}{'':>8}")
    print("-" * 72)

    tenu = True
    for metrique, seuil in SEUILS.items():
        score = metriques["global"].get(metrique)
        if score is None:
            print(f"{metrique:<42}{'—':>10}{seuil:>10.2f}{'  non calculée':>8}")
            continue
        ok = score >= seuil
        tenu &= ok
        print(f"{metrique:<42}{score:>10.3f}{seuil:>10.2f}{'  OK' if ok else '  SOUS SEUIL':>8}")

    mesurables = [r["precision_thematique"] for r in resultats
                  if r["precision_thematique"] is not None]
    if mesurables:
        moyenne = sum(mesurables) / len(mesurables)
        seuil = 0.80
        etat = "OK" if moyenne >= seuil else "SOUS SEUIL"
        print(f"{'precision_thematique (hors Ragas)':<42}{moyenne:>10.3f}{seuil:>10.2f}  {etat}")
        print(f"{'':<42}{f'sur {len(mesurables)} questions à critère lexical':>28}")

    em = [r["exact_match"] for r in resultats]
    em_faits = [r["exact_match_faits"] for r in resultats
                if r["exact_match_faits"] == r["exact_match_faits"]]
    print(f"\n{'exact_match (strict, hors Ragas)':<42}{sum(em) / len(em):>10.3f}"
          f"{'—':>10}  informatif")
    if em_faits:
        print(f"{'exact_match sur les dates citées':<42}"
              f"{sum(em_faits) / len(em_faits):>10.3f}{'—':>10}  informatif")

    print(f"\n{'=' * 72}\nCLASSIFICATION\n{'=' * 72}")
    comptes: dict[str, int] = {}
    for r in resultats:
        comptes[r["classification_auto"]] = comptes.get(r["classification_auto"], 0) + 1
    for etiquette in ("correcte", "partiellement correcte", "incorrecte", "indéterminée"):
        if etiquette in comptes:
            n = comptes[etiquette]
            print(f"  {etiquette:<26} {n:>2} / {len(resultats)}  "
                  f"({n / len(resultats):.0%})  {'█' * n}")

    print(f"\n{'=' * 72}\nDÉTAIL PAR QUESTION\n{'=' * 72}")
    for resultat, mesure in zip(resultats, metriques["par_question"], strict=True):
        scores = "  ".join(
            f"{m.split('_')[0][:4]}={mesure[m]:.2f}" for m in SEUILS if m in mesure
            and mesure[m] == mesure[m]  # écarte les NaN
        )
        theme = resultat["precision_thematique"]
        theme_txt = f"  them={theme:.2f}" if theme is not None else ""
        print(f"  [{resultat['id']:<22}] {scores}{theme_txt}")
        print(f"     {resultat['classification_auto']:<24}{resultat['question'][:44]}")
    return tenu


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-set", type=Path, default=DEFAULT_TEST_SET)
    parser.add_argument("--limit", type=int, default=None,
                        help="N'évaluer que les N premières questions")
    parser.add_argument("--strict", action="store_true",
                        help="Code de sortie non nul si un seuil n'est pas tenu")
    args = parser.parse_args()

    jeu = load_test_set(args.test_set)
    if args.limit:
        jeu = jeu[: args.limit]

    resultats = run_evaluation(jeu)
    metriques = compute_metrics(resultats)
    chemin = save_report(resultats, metriques)
    tenu = afficher_synthese(metriques, resultats)

    print(f"\nRapport détaillé : {chemin}")
    return 0 if tenu or not args.strict else 1


if __name__ == "__main__":
    sys.exit(main())
