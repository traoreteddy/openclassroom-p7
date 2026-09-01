"""Banc d'essai des algorithmes d'index FAISS : latence et rappel.

Compare la recherche exhaustive (`IndexFlatL2`, exacte) au graphe navigable
(`IndexHNSWFlat`, approché) sur le corpus réellement indexé, afin de choisir
l'algorithme sur des mesures plutôt qu'au jugé.

Les vecteurs sont relus depuis l'index existant : aucun appel d'embedding n'est
refacturé, hormis celui des quelques requêtes de test.

Usage :
    python scripts/benchmark_search.py
    python scripts/benchmark_search.py --repeat 200 --k 5
"""

from __future__ import annotations

import argparse
import statistics
import time

import faiss
import numpy as np

from puls_events_rag.config import settings
from puls_events_rag.vectorstore.faiss_store import load_index

REQUETES = [
    "concert de jazz en soirée",
    "exposition de photographies contemporaines",
    "activité gratuite pour les enfants",
    "atelier scientifique pour adolescents",
    "visite guidée d'un monument historique",
    "spectacle de danse contemporaine",
    "conférence sur l'environnement",
    "marché de créateurs le week-end",
]


def latence(index: faiss.Index, requetes: np.ndarray, k: int, repeat: int) -> dict:
    """Mesure la latence de recherche, hors calcul des embeddings."""
    mesures = []
    for _ in range(repeat):
        q = requetes[np.random.randint(len(requetes))]
        depart = time.perf_counter()
        index.search(q.reshape(1, -1), k)
        mesures.append((time.perf_counter() - depart) * 1000)
    mesures.sort()
    return {
        "moyenne": statistics.mean(mesures),
        "p50": mesures[len(mesures) // 2],
        "p95": mesures[int(len(mesures) * 0.95)],
    }


def rappel(approche: faiss.Index, exact: faiss.Index, requetes: np.ndarray, k: int) -> float:
    """Part des k meilleurs résultats exacts retrouvés par l'index approché."""
    _, refs = exact.search(requetes, k)
    _, obtenus = approche.search(requetes, k)
    trouves = sum(len(set(a) & set(b)) for a, b in zip(refs, obtenus, strict=True))
    return trouves / (len(requetes) * k)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=settings.top_k)
    parser.add_argument("--repeat", type=int, default=200)
    args = parser.parse_args()

    store = load_index()
    vecteurs = store.index.reconstruct_n(0, store.index.ntotal).astype("float32")
    dimension = vecteurs.shape[1]
    print(f"Corpus indexé : {len(vecteurs)} vecteurs de dimension {dimension}")

    # La latence d'embedding sert de référence : c'est elle qui domine le temps
    # de réponse, et donc elle qui décide si un gain sur la recherche compte.
    depart = time.perf_counter()
    requetes = np.array(store.embedding_function.embed_documents(REQUETES), dtype="float32")
    latence_embedding = (time.perf_counter() - depart) / len(REQUETES) * 1000
    print(f"Requêtes de test : {len(REQUETES)}")
    print(f"Embedding d'une requête : {latence_embedding:.1f} ms "
          f"({settings.embedding_provider})\n")

    plat = faiss.IndexFlatL2(dimension)
    plat.add(vecteurs)

    debut = time.perf_counter()
    hnsw = faiss.IndexHNSWFlat(dimension, settings.hnsw_m)
    hnsw.hnsw.efConstruction = settings.hnsw_ef_construction
    hnsw.hnsw.efSearch = settings.hnsw_ef_search
    hnsw.add(vecteurs)
    construction_hnsw = time.perf_counter() - debut

    print(f"{'Index':<12}{'moyenne':>10}{'p50':>9}{'p95':>9}{'rappel@' + str(args.k):>12}"
          f"{'construction':>14}")
    print("-" * 66)

    lat_plat = latence(plat, requetes, args.k, args.repeat)
    print(f"{'Flat (exact)':<12}{lat_plat['moyenne']:>9.3f}ms{lat_plat['p50']:>8.3f}ms"
          f"{lat_plat['p95']:>8.3f}ms{'1.000':>12}{'immédiate':>14}")

    lat_hnsw = latence(hnsw, requetes, args.k, args.repeat)
    r = rappel(hnsw, plat, requetes, args.k)
    print(f"{'HNSW':<12}{lat_hnsw['moyenne']:>9.3f}ms{lat_hnsw['p50']:>8.3f}ms"
          f"{lat_hnsw['p95']:>8.3f}ms{r:>12.3f}{construction_hnsw:>13.2f}s")

    print(f"\nefSearch={settings.hnsw_ef_search}, M={settings.hnsw_m}")

    gain_ms = lat_plat["moyenne"] - lat_hnsw["moyenne"]
    part_embedding = gain_ms / latence_embedding * 100
    print(f"\nGain absolu de HNSW : {gain_ms:.3f} ms, soit {part_embedding:.2f} % "
          f"du coût d'embedding d'une requête ({latence_embedding:.1f} ms).")

    # Le ratio de latence ne suffit pas : diviser par trois une durée déjà
    # négligeable devant l'embedding ne se voit pas, alors que la perte de
    # rappel, elle, se voit dans les réponses.
    if gain_ms < latence_embedding * 0.05:
        cout_rappel = (
            "sans perte de rappel sur ce petit corpus, mais l'approximation "
            "reste une source d'erreur inutile ici"
            if r >= 0.999
            else f"et le rappel tombe à {r:.3f} : "
                 f"{(1 - r) * 100:.0f} % des meilleurs résultats sont manqués"
        )
        print(f"\nConclusion : à {len(vecteurs)} vecteurs, le gain est invisible "
              f"à l'échelle d'une requête, {cout_rappel}.")
        print("L'index Flat reste le bon choix : exact, sans paramétrage ni "
              "coût de construction. HNSW deviendra pertinent quand la "
              "recherche pèsera dans le temps de réponse, "
              "typiquement au-delà de quelques centaines de milliers de vecteurs.")
    else:
        print(f"\nConclusion : HNSW fait gagner {gain_ms:.1f} ms par requête "
              f"({part_embedding:.0f} % du coût d'embedding) pour un rappel de {r:.3f}.")
        print("Basculer avec FAISS_INDEX_TYPE=hnsw, puis reconstruire l'index.")


if __name__ == "__main__":
    main()
