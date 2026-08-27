"""API FastAPI exposant le système RAG.

Lancement : uvicorn puls_events_rag.api.main:app --reload
"""

from fastapi import FastAPI, HTTPException

from puls_events_rag.api.schemas import AskRequest, AskResponse, RebuildResponse

app = FastAPI(
    title="Puls-Events RAG API",
    description="Assistant intelligent de recommandation d'événements culturels",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """Répond à une question utilisateur à partir des événements indexés."""
    raise HTTPException(status_code=501, detail="TODO: brancher rag.chain.answer_question")


@app.post("/rebuild", response_model=RebuildResponse)
def rebuild() -> RebuildResponse:
    """Reconstruit l'index FAISS (collecte -> nettoyage -> embeddings -> index)."""
    raise HTTPException(status_code=501, detail="TODO: brancher le pipeline d'indexation")
