"""Schémas Pydantic des requêtes et réponses de l'API.

Les contraintes déclarées ici sont appliquées par FastAPI avant même d'atteindre
le code métier : une question vide est rejetée avec un 422 explicite plutôt que
de déclencher une recherche vectorielle inutile.
"""

from pydantic import BaseModel, Field, field_validator


class AskRequest(BaseModel):
    """Question posée au système RAG."""

    question: str = Field(
        min_length=3,
        max_length=500,
        description="Question en langage naturel sur les événements culturels",
        examples=["Quels concerts de jazz puis-je voir à Paris ?"],
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="Nombre d'événements à considérer (défaut : configuration du serveur)",
    )

    @field_validator("question")
    @classmethod
    def question_non_vide(cls, valeur: str) -> str:
        """Une question faite d'espaces passerait la contrainte de longueur."""
        nettoyee = valeur.strip()
        if len(nettoyee) < 3:
            raise ValueError("La question doit contenir au moins 3 caractères significatifs")
        return nettoyee


class Source(BaseModel):
    """Événement effectivement utilisé pour rédiger la réponse."""

    titre: str
    periode: str
    lieu: str
    ville: str
    url: str = Field(description="Page Open Agenda de l'événement, pour vérification")
    score: float = Field(description="Distance sémantique à la question (plus bas = plus proche)")


class AskResponse(BaseModel):
    """Réponse générée, accompagnée des sources qui l'étayent."""

    answer: str = Field(description="Réponse rédigée par le modèle à partir des sources")
    sources: list[Source] = Field(default_factory=list)
    events_found: int = Field(description="Nombre d'événements distincts retenus")
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Anomalies relevées par la validation de sortie : URL absente des "
            "sources et retirée, événement cité sans fiche correspondante. "
            "Une liste non vide signale une possible injection dans les données."
        ),
    )


class RebuildResponse(BaseModel):
    """Compte rendu d'une reconstruction de l'index."""

    status: str
    events_collected: int
    documents_indexed: int
    chunks_indexed: int
    duration_seconds: float


class HealthResponse(BaseModel):
    """État du service et de l'index."""

    status: str
    index_ready: bool
    chunks_indexed: int | None = None
    embedding_provider: str | None = None
