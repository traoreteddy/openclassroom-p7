"""Évaluation du système RAG sur le jeu de test annoté.

Mesure quantitative (similarité sémantique réponse/référence, couverture des
sources attendues) et qualitative (détection d'hallucinations hors catalogue).

Usage : python evaluation/evaluate_rag.py --test-set evaluation/test_set.json
Les résultats sont écrits dans evaluation/results/.
"""

from pathlib import Path

EVALUATION_DIR = Path(__file__).resolve().parent
DEFAULT_TEST_SET = EVALUATION_DIR / "test_set.json"
RESULTS_DIR = EVALUATION_DIR / "results"


def load_test_set(path: Path = DEFAULT_TEST_SET) -> list[dict]:
    """Charge le jeu de test annoté (voir test_set.example.json pour le format)."""
    raise NotImplementedError("TODO: lire le fichier JSON du jeu de test")


def run_evaluation(test_set: list[dict]) -> list[dict]:
    """Interroge la chaîne RAG sur chaque question et collecte réponses + sources."""
    raise NotImplementedError("TODO: appeler rag.chain.answer_question sur chaque question")


def compute_metrics(results: list[dict]) -> dict:
    """Calcule les métriques agrégées (similarité, couverture, taux d'abstention)."""
    raise NotImplementedError("TODO: calcul des métriques d'évaluation")


def save_report(results: list[dict], metrics: dict, output_dir: Path = RESULTS_DIR) -> None:
    """Persiste le détail par question et la synthèse des métriques."""
    raise NotImplementedError("TODO: écrire le rapport d'évaluation")


def main() -> None:
    test_set = load_test_set()
    results = run_evaluation(test_set)
    metrics = compute_metrics(results)
    save_report(results, metrics)
    print(f"Évaluation terminée : {len(results)} questions — métriques : {metrics}")


if __name__ == "__main__":
    main()
