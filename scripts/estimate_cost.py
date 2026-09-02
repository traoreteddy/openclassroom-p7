"""Estime le coût d'exploitation du système, à partir du corpus réellement indexé.

Les volumes ne sont pas supposés : le nombre de jetons du corpus est déduit de
sa taille en caractères et d'un ratio mesuré sur un appel réel à l'API Mistral,
et le coût d'une question vient d'un relevé de consommation effectif.

Usage :
    python scripts/estimate_cost.py
    python scripts/estimate_cost.py --questions-par-jour 5000 --reconstructions-par-mois 30
    python scripts/estimate_cost.py --mesurer      # relève les jetons sur un appel réel
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from puls_events_rag.config import PROCESSED_DATA_DIR

# --------------------------------------------------------------------------- #
# Tarifs publics, en dollars par million de jetons.
# Relevés le 2 septembre 2026 sur mistral.ai/pricing/api et
# developers.openai.com/api/docs/pricing.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Tarif:
    nom: str
    embeddings: float          # $ / M jetons
    generation_entree: float   # $ / M jetons
    generation_sortie: float   # $ / M jetons


TARIFS = {
    "mistral": Tarif("Mistral (mistral-embed + mistral-small-latest)", 0.10, 0.15, 0.60),
    "openai": Tarif("OpenAI (text-embedding-3-small + gpt-4o-mini)", 0.02, 0.15, 0.60),
}

# Relevés sur un appel réel : voir --mesurer pour les reproduire.
JETONS_ENTREE_PAR_QUESTION = 1804   # prompt système + 5 fiches événement
JETONS_SORTIE_PAR_QUESTION = 196    # réponse rédigée
JETONS_QUESTION_EMBEDDING = 12
CARACTERES_PAR_JETON = 3.29         # mesuré sur un prompt français réel

CATALOGUE_NATIONAL = 1_233_842      # événements du jeu Open Agenda complet


def volume_corpus() -> tuple[int, int, int]:
    """Retourne (chunks, caractères, jetons) du corpus indexé."""
    chemin = PROCESSED_DATA_DIR / "chunks.json"
    if not chemin.exists():
        raise FileNotFoundError(
            f"{chemin} introuvable : lancez d'abord scripts/rebuild_all.py"
        )
    chunks = json.loads(chemin.read_text(encoding="utf-8"))
    caracteres = sum(len(c["text"]) for c in chunks)
    return len(chunks), caracteres, round(caracteres / CARACTERES_PAR_JETON)


def cout_indexation(jetons: int, tarif: Tarif) -> float:
    return jetons / 1_000_000 * tarif.embeddings


def cout_question(tarif: Tarif) -> float:
    return (
        JETONS_QUESTION_EMBEDDING / 1_000_000 * tarif.embeddings
        + JETONS_ENTREE_PAR_QUESTION / 1_000_000 * tarif.generation_entree
        + JETONS_SORTIE_PAR_QUESTION / 1_000_000 * tarif.generation_sortie
    )


def mesurer() -> None:
    """Relève la consommation réelle sur un appel, pour actualiser les constantes."""
    from puls_events_rag.rag.chain import format_context, get_llm, retrieve_events
    from puls_events_rag.rag.prompts import SYSTEM_PROMPT

    question = "Quels concerts de jazz puis-je voir à Paris ?"
    prompt = SYSTEM_PROMPT.format(
        context=format_context(retrieve_events(question)), question=question
    )
    reponse = get_llm().invoke(prompt)
    usage = reponse.response_metadata.get("token_usage", {})
    entree, sortie = usage.get("prompt_tokens"), usage.get("completion_tokens")
    print("Relevé sur un appel réel :")
    print(f"  jetons d'entrée          : {entree}")
    print(f"  jetons de sortie         : {sortie}")
    print(f"  caractères par jeton     : {len(prompt) / entree:.2f}")
    print("\nReportez ces valeurs dans les constantes du script si elles ont dérivé.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions-par-jour", type=int, default=1000)
    parser.add_argument("--reconstructions-par-mois", type=int, default=30)
    parser.add_argument("--mesurer", action="store_true",
                        help="Relève les jetons sur un appel réel et s'arrête")
    args = parser.parse_args()

    if args.mesurer:
        mesurer()
        return

    chunks, caracteres, jetons = volume_corpus()
    print(f"{'=' * 74}\nCORPUS INDEXÉ\n{'=' * 74}")
    print(f"  {chunks} chunks · {caracteres:,} caractères · "
          f"~{jetons:,} jetons".replace(",", " "))

    print(f"\n{'=' * 74}\nCOÛT UNITAIRE\n{'=' * 74}")
    print(f"{'Fournisseur':<46}{'Indexation':>13}{'Question':>15}")
    print("-" * 74)
    for tarif in TARIFS.values():
        print(f"{tarif.nom:<46}{cout_indexation(jetons, tarif):>12.4f}$"
              f"{cout_question(tarif):>14.6f}$")

    tarif = TARIFS["mistral"]
    par_mois_questions = args.questions_par_jour * 30 * cout_question(tarif)
    par_mois_index = args.reconstructions_par_mois * cout_indexation(jetons, tarif)

    print(f"\n{'=' * 74}\nEXPLOITATION MENSUELLE — MISTRAL\n{'=' * 74}")
    print(f"  {args.questions_par_jour} questions par jour, "
          f"{args.reconstructions_par_mois} reconstructions par mois\n")
    print(f"  {'Génération et embedding des questions':<52}{par_mois_questions:>10.2f}$")
    print(f"  {'Reconstruction de l index':<52}{par_mois_index:>10.2f}$")
    print(f"  {'':<52}{'-' * 10:>10}")
    print(f"  {'Total':<52}{par_mois_questions + par_mois_index:>10.2f}$")

    print(f"\n{'=' * 74}\nMONTÉE EN CHARGE\n{'=' * 74}")
    print(f"{'Questions / jour':>18}{'Génération / mois':>22}{'Total / mois':>18}")
    print("-" * 74)
    for volume in (100, 1_000, 10_000, 100_000):
        generation = volume * 30 * cout_question(tarif)
        print(f"{volume:>18,}{generation:>21.2f}${generation + par_mois_index:>17.2f}$"
              .replace(",", " "))

    jetons_national = jetons * CATALOGUE_NATIONAL / _evenements_indexes()
    print(f"\n{'=' * 74}\nEXTENSION AU CATALOGUE NATIONAL\n{'=' * 74}")
    print(f"  {CATALOGUE_NATIONAL:,} événements contre {_evenements_indexes()} indexés "
          f"aujourd'hui".replace(",", " "))
    print(f"  ~{jetons_national / 1e6:,.0f} millions de jetons à vectoriser"
          .replace(",", " "))
    print(f"  Reconstruction complète : {cout_indexation(jetons_national, tarif):,.0f}$"
          .replace(",", " "))
    print(f"  Une par jour            : "
          f"{cout_indexation(jetons_national, tarif) * 30:,.0f}$ par mois"
          .replace(",", " "))
    print("\n  À cette échelle, la reconstruction complète quotidienne devient le poste")
    print("  dominant. L'indexation incrémentale — ne vectoriser que les événements")
    print("  nouveaux ou modifiés — cesse d'être un raffinement pour devenir la")
    print("  condition de viabilité économique.")


def _evenements_indexes() -> int:
    chunks = json.loads((PROCESSED_DATA_DIR / "chunks.json").read_text(encoding="utf-8"))
    return len({c["metadata"]["uid"] for c in chunks})


if __name__ == "__main__":
    main()
