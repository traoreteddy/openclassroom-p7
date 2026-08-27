"""Client de collecte des événements via l'API Open Agenda.

Documentation : https://developers.openagenda.com/
"""

from puls_events_rag.config import settings  # noqa: F401


def fetch_events() -> list[dict]:
    """Récupère les événements bruts depuis l'API Open Agenda.

    Returns:
        Liste d'événements au format JSON (dictionnaires).
    """
    raise NotImplementedError("TODO: appeler l'API Open Agenda avec les filtres du POC")
