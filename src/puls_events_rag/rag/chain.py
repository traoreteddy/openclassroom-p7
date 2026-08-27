"""Chaîne RAG LangChain : retriever FAISS + LLM Mistral + prompt."""

from puls_events_rag.config import settings  # noqa: F401
from puls_events_rag.rag.prompts import SYSTEM_PROMPT  # noqa: F401


def build_chain():
    """Assemble et retourne la chaîne RAG (retriever -> prompt -> LLM)."""
    raise NotImplementedError("TODO: assembler la chaîne LangChain")


def answer_question(question: str) -> dict:
    """Répond à une question utilisateur et retourne la réponse + les sources."""
    raise NotImplementedError("TODO: invoquer la chaîne RAG")
