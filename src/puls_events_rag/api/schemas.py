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


class IndexInfo(BaseModel):
    """Caractéristiques techniques de l'index vectoriel."""

    chunks: int
    events: int
    dimension: int | None = None
    index_type: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    built_at: str | None = Field(default=None, description="Date de construction (ISO)")


class CorpusInfo(BaseModel):
    """Périmètre métier du catalogue interrogeable."""

    cities: list[str] = Field(description="Villes couvertes par l'index")
    period_start: str | None = Field(default=None, description="Début de la période, ISO")
    period_end: str | None = Field(default=None, description="Fin de la période, ISO")
    events: int
    upcoming_events: int = Field(description="Événements dont la date de fin est à venir")
    with_url: int = Field(description="Événements disposant d'une fiche source")
    with_coordinates: int


class SourceAgenda(BaseModel):
    """Agenda Open Agenda ayant alimenté le catalogue."""

    agenda: str
    events: int


class MetadataResponse(BaseModel):
    """Description du catalogue, pour qu'une équipe métier sache ce qu'elle interroge."""

    index: IndexInfo
    corpus: CorpusInfo
    sources: list[SourceAgenda] = Field(
        description="Agendas source, du plus fourni au moins fourni"
    )
    sources_total: int = Field(description="Nombre total d'agendas, avant pagination")
    limit: int
    offset: int


class HealthResponse(BaseModel):
    """État du service et de l'index."""

    status: str
    index_ready: bool
    chunks_indexed: int | None = None
    embedding_provider: str | None = None
