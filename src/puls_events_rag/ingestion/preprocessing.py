"""Nettoyage et préparation des événements avant vectorisation.

- Suppression des doublons et des champs vides
- Nettoyage HTML / caractères parasites dans les descriptions
- Construction du texte à vectoriser + métadonnées associées
"""


def clean_events(raw_events: list[dict]) -> list[dict]:
    """Nettoie les événements bruts et retourne des documents prêts au chunking."""
    raise NotImplementedError("TODO: nettoyage des données Open Agenda")


def chunk_documents(documents: list[dict]) -> list[dict]:
    """Découpe les documents en chunks (taille/chevauchement définis dans config)."""
    raise NotImplementedError("TODO: chunking des documents")
