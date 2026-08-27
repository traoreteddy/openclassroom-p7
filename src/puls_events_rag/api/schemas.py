"""Schémas Pydantic des requêtes/réponses de l'API."""

from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: list[dict] = []


class RebuildResponse(BaseModel):
    status: str
    documents_indexed: int
