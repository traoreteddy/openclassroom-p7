"""Chaîne RAG : retriever FAISS -> prompt -> LLM Mistral.

Assemblée avec LangChain (LCEL). La chaîne récupère les chunks les plus proches
sémantiquement de la question, les met en forme dans un contexte lisible, puis
demande au modèle de rédiger une recommandation appuyée sur ces seuls éléments.

Deux traitements séparent cette chaîne d'un enchaînement naïf :

- **Déduplication par événement** : un même événement occupe plusieurs chunks et
  monopoliserait sinon les premières places, réduisant la recommandation à une
  seule sortie déclinée trois fois.
- **Sources structurées** : la réponse est accompagnée des événements réellement
  utilisés, avec leur URL Open Agenda, pour que l'utilisateur puisse vérifier.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from puls_events_rag.config import settings
from puls_events_rag.rag.prompts import EVENT_TEMPLATE, SYSTEM_PROMPT
from puls_events_rag.vectorstore.faiss_store import load_index

logger = logging.getLogger(__name__)

# Les chunks d'un même événement se ressemblent : on en récupère davantage que
# le nombre d'événements souhaité, avant de dédoublonner.
FACTEUR_SURECHANTILLONNAGE = 4


@lru_cache(maxsize=1)
def _get_store():
    """Index FAISS chargé une seule fois et réutilisé.

    Sans ce cache, chaque question relirait 8,3 Mo de vecteurs et réinstancierait
    le modèle d'embedding, soit ~580 ms mesurées avant d'avoir seulement commencé
    à chercher.
    """
    return load_index()


def reset_cache() -> None:
    """Vide les caches après une reconstruction de l'index.

    Sans cela, l'API continuerait de répondre à partir de l'index précédent,
    toujours en mémoire, jusqu'à son redémarrage.
    """
    _get_store.cache_clear()
    build_chain.cache_clear()
    logger.info("Caches de la chaîne RAG vidés")


def get_llm():
    """Retourne le modèle de génération Mistral configuré."""
    if not settings.mistral_api_key:
        raise ValueError(
            "MISTRAL_API_KEY est absente : la génération de réponses nécessite "
            "une clé d'API Mistral. Renseignez-la dans .env."
        )
    from langchain_mistralai import ChatMistralAI

    return ChatMistralAI(
        model=settings.llm_model,
        api_key=settings.mistral_api_key,
        temperature=0.2,  # bas : on veut des faits repris du contexte, pas du style
    )


def retrieve_events(question: str, k: int | None = None) -> list[Document]:
    """Récupère les chunks pertinents, en gardant un seul chunk par événement.

    Args:
        question: la question de l'utilisateur.
        k: nombre d'événements distincts souhaités (défaut : ``settings.top_k``).

    Returns:
        Les documents retenus, du plus proche au moins proche.
    """
    k = k or settings.top_k
    store = _get_store()
    candidats = store.similarity_search_with_score(question, k=k * FACTEUR_SURECHANTILLONNAGE)

    retenus: list[Document] = []
    vus: set[str] = set()
    for document, score in candidats:
        uid = document.metadata.get("uid")
        if uid in vus:
            continue
        vus.add(uid)
        document.metadata["score"] = float(score)
        retenus.append(document)
        if len(retenus) == k:
            break

    logger.info("Récupération : %s chunks -> %s événements distincts",
                len(candidats), len(retenus))
    return retenus


def format_event(document: Document, numero: int = 1) -> str:
    """Met en forme un événement : titre, date et lieu viennent des métadonnées.

    Le ``page_content`` d'un chunk ne porte que sa part de description ; le titre
    et la date, eux, sont dans les métadonnées. Un contexte bâti sur le seul
    ``page_content`` priverait le modèle — et l'évaluation — de ces éléments.
    """
    meta = document.metadata
    details = ""
    if meta.get("age_min") is not None:
        details += f"Âge minimum : {meta['age_min']} ans\n"
    if meta.get("accessibilite"):
        details += f"Accessibilité : {', '.join(meta['accessibilite'])}\n"
    if meta.get("mots_cles"):
        details += f"Mots-clés : {', '.join(meta['mots_cles'][:6])}\n"

    description = document.page_content
    if "Description :" in description:
        description = description.split("Description :", 1)[1].strip()

    return EVENT_TEMPLATE.format(
        numero=numero,
        titre=meta.get("titre", "(sans titre)"),
        periode=meta.get("periode", "date non précisée"),
        lieu=meta.get("lieu") or "lieu non précisé",
        adresse=f", {meta['adresse']}" if meta.get("adresse") else "",
        ville=meta.get("ville", ""),
        details=details,
        description=description,
    )


def format_context_blocks(documents: list[Document]) -> list[str]:
    """Un bloc de contexte par événement.

    Utilisé par l'évaluation : les métriques Ragas doivent porter sur les
    contextes réellement soumis au modèle, pas sur le texte brut des chunks.
    """
    return [format_event(d, numero) for numero, d in enumerate(documents, start=1)]


def format_context(documents: list[Document]) -> str:
    """Met en forme les événements récupérés pour le prompt."""
    if not documents:
        return "(aucun événement ne correspond à cette recherche)"
    return "\n\n".join(format_context_blocks(documents))


def to_sources(documents: list[Document]) -> list[dict]:
    """Extrait les sources citables des documents utilisés."""
    return [
        {
            "titre": d.metadata.get("titre", ""),
            "periode": d.metadata.get("periode", ""),
            "lieu": d.metadata.get("lieu", ""),
            "ville": d.metadata.get("ville", ""),
            "url": d.metadata.get("url", ""),
            "score": round(d.metadata.get("score", 0.0), 4),
        }
        for d in documents
    ]


@lru_cache(maxsize=1)
def build_chain() -> Runnable:
    """Assemble la chaîne LCEL : contexte + question -> prompt -> LLM -> texte.

    La chaîne attend un dictionnaire ``{"context": ..., "question": ...}``. La
    récupération est faite en amont par :func:`retrieve_events`, afin que les
    documents servent à la fois au prompt et aux sources renvoyées à l'appelant.
    """
    prompt = ChatPromptTemplate.from_template(SYSTEM_PROMPT)
    return prompt | get_llm() | StrOutputParser()


def answer_question(question: str, k: int | None = None) -> dict:
    """Répond à une question et retourne la réponse accompagnée de ses sources.

    Args:
        question: la question de l'utilisateur.
        k: nombre d'événements à considérer (défaut : ``settings.top_k``).

    Returns:
        ``{"answer": str, "sources": list[dict], "events_found": int}``
    """
    documents = retrieve_events(question, k=k)

    if not documents:
        return {
            "answer": "Aucun événement de notre catalogue ne correspond à cette "
                      "recherche. Essayez avec une autre ville, une autre période "
                      "ou un type d'événement différent.",
            "sources": [],
            "events_found": 0,
        }

    reponse = build_chain().invoke({
        "context": format_context(documents),
        "question": question,
    })
    return {
        "answer": reponse.strip(),
        "sources": to_sources(documents),
        "events_found": len(documents),
    }
