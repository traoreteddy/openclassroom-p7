"""Point d'entrée pratique : lance l'API en local.

Équivalent à : uvicorn puls_events_rag.api.main:app --reload
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("puls_events_rag.api.main:app", host="127.0.0.1", port=8000, reload=True)
