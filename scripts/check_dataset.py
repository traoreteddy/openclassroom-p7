"""Contrôle de cohérence du jeu de données, à lancer avant la vectorisation.

Vérifie que les artefacts de la chaîne — événements bruts, documents nettoyés,
chunks, index — décrivent bien le même corpus, que le périmètre demandé a été
respecté, et que le texte envoyé au modèle d'embedding est exploitable.

Usage :
    python scripts/check_dataset.py
    python scripts/check_dataset.py --strict   # code de sortie 1 si un contrôle échoue

Sans index existant, les contrôles qui le concernent sont ignorés : le script
sert précisément à valider les données *avant* de payer la vectorisation.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

from puls_events_rag.config import INDEX_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR, settings

BALISE_HTML = re.compile(r"<[a-z/][^>]*>")


class Rapport:
    """Accumule les résultats des contrôles et en fait la synthèse."""

    def __init__(self) -> None:
        self.echecs: list[str] = []
        self.ignores: list[str] = []

    def section(self, titre: str) -> None:
        print(f"\n{titre}")

    def check(self, nom: str, ok: bool, detail: str = "") -> bool:
        print(f"  {'OK   ' if ok else 'ÉCHEC'} {nom}{f' — {detail}' if detail else ''}")
        if not ok:
            self.echecs.append(f"{nom}{f' — {detail}' if detail else ''}")
        return ok

    def info(self, texte: str) -> None:
        print(f"        {texte}")

    def ignore(self, nom: str, raison: str) -> None:
        print(f"  —     {nom} (ignoré : {raison})")
        self.ignores.append(nom)

    def synthese(self) -> bool:
        print()
        if self.echecs:
            print(f"{len(self.echecs)} incohérence(s) :")
            for e in self.echecs:
                print(f"  - {e}")
        else:
            print("Jeu de données cohérent : prêt pour la vectorisation.")
        if self.ignores:
            print(f"({len(self.ignores)} contrôle(s) ignoré(s))")
        return not self.echecs


def charger(chemin: Path):
    return json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="Retourne un code de sortie non nul si un contrôle échoue")
    args = parser.parse_args()

    bruts = sorted(RAW_DATA_DIR.glob("events_*.json"))
    bruts = [b for b in bruts if not b.name.endswith(".meta.json")]
    if not bruts:
        print("Aucun événement brut : lancez d'abord scripts/collect_events.py")
        return 1

    raw_path = bruts[-1]
    raw = charger(raw_path)
    manifeste = charger(raw_path.with_suffix(".meta.json")) or {}
    documents = charger(PROCESSED_DATA_DIR / "documents.json")
    chunks = charger(PROCESSED_DATA_DIR / "chunks.json")
    index_meta = charger(INDEX_DIR / "index_meta.json")

    r = Rapport()
    print(f"Brut le plus récent : {raw_path.name} ({len(raw)} événements)")
    if manifeste:
        print(f"Périmètre collecté  : {', '.join(manifeste.get('villes', []))} | "
              f"{manifeste.get('debut')} → {manifeste.get('fin')} | "
              f"types : {', '.join(manifeste.get('types') or ['tous'])}")

    if documents is None or chunks is None:
        print("\ndocuments.json ou chunks.json absent : lancez scripts/collect_events.py")
        return 1

    uid_raw = {str(e.get("uid")) for e in raw}
    uid_doc = {d["metadata"]["uid"] for d in documents}
    uid_chunk = {c["metadata"]["uid"] for c in chunks}

    r.section("A. Chaînage des artefacts")
    r.check("A1 aucun doublon dans le brut", len(uid_raw) == len(raw),
            f"{len(raw) - len(uid_raw)} doublons")
    r.check("A2 documents.json issu du brut courant", uid_doc <= uid_raw,
            f"{len(uid_doc - uid_raw)} uid orphelins")
    r.check("A3 chunks.json issu du brut courant", uid_chunk <= uid_raw,
            f"{len(uid_chunk - uid_raw)} uid orphelins")
    r.check("A4 documents.json et chunks.json décrivent le même corpus", uid_doc == uid_chunk,
            f"{len(uid_doc)} vs {len(uid_chunk)} événements")
    if index_meta:
        r.check("A5 index construit sur ces chunks", index_meta["chunks"] == len(chunks),
                f"{index_meta['chunks']} vs {len(chunks)}")
        from puls_events_rag.vectorstore.faiss_store import verify_index

        rapport = verify_index(chunks)
        r.check("A6 tous les chunks présents dans l'index", rapport["complet"],
                f"{rapport['vecteurs']} vecteurs / {rapport['chunks_attendus']} attendus, "
                f"{len(rapport['chunks_manquants'])} manquants")
        r.info(f"événements couverts : {rapport['evenements_indexes']}/"
               f"{rapport['evenements_attendus']} | index {index_meta.get('index_type', 'flat')}")
    else:
        r.ignore("A5/A6 exhaustivité de l'index", "pas encore d'index")

    r.section("B. Respect du périmètre demandé")
    villes = collections.Counter(d["metadata"]["ville"] for d in documents)
    if manifeste.get("villes"):
        attendues = set(manifeste["villes"])
        r.check("B1 villes conformes au manifeste", set(villes) <= attendues,
                f"inattendues : {set(villes) - attendues or '—'}")
    else:
        r.ignore("B1 villes conformes au manifeste", "manifeste absent")
    debuts = [d["metadata"]["date_debut"][:10] for d in documents if d["metadata"]["date_debut"]]
    fins = [d["metadata"]["date_fin"][:10] for d in documents if d["metadata"]["date_fin"]]
    r.check("B2 dates de début toutes renseignées", len(debuts) == len(documents),
            f"{len(documents) - len(debuts)} manquantes")
    if debuts:
        r.info(f"période couverte : {min(debuts)} → {max(debuts)}")
    if manifeste.get("debut"):
        hors = [f for f in fins if f < manifeste["debut"]]
        r.check("B3 aucun événement déjà terminé", not hors, f"{len(hors)} terminés avant la fenêtre")
        tard = [d for d in debuts if d > manifeste["fin"]]
        r.check("B4 aucun début hors fenêtre", not tard, f"{len(tard)} après la fenêtre")
    else:
        r.ignore("B3/B4 bornes de période", "manifeste absent")

    r.section("C. Intégrité du chunking")
    par_doc = collections.Counter(c["metadata"]["uid"] for c in chunks)
    totaux = {c["metadata"]["uid"]: c["metadata"]["chunk_total"] for c in chunks}
    r.check("C1 chunk_total conforme au nombre réel de chunks",
            all(par_doc[u] == t for u, t in totaux.items()),
            f"{sum(1 for u, t in totaux.items() if par_doc[u] != t)} incohérents")
    r.check("C2 identifiants de chunk uniques", len({c["id"] for c in chunks}) == len(chunks))
    r.check("C3 aucun chunk vide", all(c["text"].strip() for c in chunks))
    # La taille attendue vient de la configuration, pas de l'index : ce contrôle
    # doit fonctionner avant toute vectorisation.
    trop = [c for c in chunks if len(c["text"]) > settings.chunk_size]
    r.check("C4 taille de chunk respectée", not trop,
            f"{len(trop)} au-delà de {settings.chunk_size} caractères")
    indices = collections.defaultdict(list)
    for c in chunks:
        indices[c["metadata"]["uid"]].append(c["metadata"]["chunk_index"])
    r.check("C5 indices de chunk contigus",
            all(sorted(v) == list(range(len(v))) for v in indices.values()))
    r.info(f"{len(chunks)} chunks pour {len(documents)} événements "
           f"({len(chunks) / len(documents):.1f} par événement)")

    r.section("D. Qualité du texte à vectoriser")
    r.check("D1 aucune balise HTML résiduelle",
            not [c for c in chunks if BALISE_HTML.search(c["text"])])
    r.check("D2 aucun « None » textuel", not [c for c in chunks if "None" in c["text"]])
    r.check("D3 aucun espace insécable", not [c for c in chunks if "\xa0" in c["text"]])
    r.check("D4 aucun caractère de substitution", not [c for c in chunks if "�" in c["text"]])
    r.check("D5 titre présent sur chaque chunk",
            all(c["metadata"]["titre"] for c in chunks))

    r.section("E. Métadonnées de citation")
    for champ in ("url", "periode", "ville"):
        manquants = [c for c in chunks if not c["metadata"].get(champ)]
        r.check(f"E1 « {champ} » renseigné partout", not manquants, f"{len(manquants)} manquants")
    hors_domaine = [c for c in chunks
                    if not c["metadata"]["url"].startswith("https://openagenda.com/")]
    r.check("E2 URL pointant vers openagenda.com", not hors_domaine,
            f"{len(hors_domaine)} hors domaine")
    geo = sum(1 for d in documents if d["metadata"]["latitude"] is not None)
    r.info(f"coordonnées GPS disponibles : {geo}/{len(documents)} événements")

    ok = r.synthese()
    return 0 if ok or not args.strict else 1


if __name__ == "__main__":
    sys.exit(main())
