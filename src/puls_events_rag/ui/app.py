"""Interface de démonstration du chatbot Puls-Events.

Cette interface est un **client de l'API REST**, pas une seconde implémentation :
elle appelle `/ask`, `/health` et `/rebuild` par HTTP, exactement comme le ferait
une application tierce. Deux conséquences utiles : la démonstration prouve que
l'API fonctionne, et la logique métier reste à un seul endroit.

Lancement :
    uv run streamlit run src/puls_events_rag/ui/app.py
"""

from __future__ import annotations

import time

import httpx
import streamlit as st

from puls_events_rag.config import settings

TIMEOUT_QUESTION = 90.0
TIMEOUT_RECONSTRUCTION = 900.0

# Les trois scénarios préparés pour la soutenance : le cas nominal, l'aveu de
# limite, et une demande dont la réponse n'existe pas dans le catalogue.
EXEMPLES = [
    ("Concerts de jazz", "Quels concerts de jazz puis-je voir à Paris ?"),
    ("Sortie en famille", "Que faire avec des enfants à Paris ?"),
    ("Hors périmètre", "Y a-t-il des concerts à Marseille ?"),
]

STYLE = """
<style>
  .stApp { background: #F5F7F9; }
  .source-carte {
      background: #FFFFFF; border: 1px solid #DDE3EA; border-left: 3px solid #B8420F;
      border-radius: 5px; padding: .7rem .9rem; margin-bottom: .5rem;
  }
  .source-titre { font-weight: 600; color: #1B2430; font-size: .95rem; }
  .source-detail { color: #5B6675; font-size: .82rem; margin-top: .15rem; }
  .source-detail a { color: #26636F; }
  .reponse {
      background: #FFFFFF; border: 1px solid #DDE3EA; border-radius: 6px;
      padding: 1.1rem 1.3rem; line-height: 1.6;
  }
</style>
"""


def api(chemin: str) -> str:
    return f"{settings.api_base_url.rstrip('/')}{chemin}"


@st.cache_data(ttl=15)
def etat_index() -> dict | None:
    """Interroge /health. Retourne None si l'API est injoignable."""
    try:
        reponse = httpx.get(api("/health"), timeout=10.0)
        reponse.raise_for_status()
        return reponse.json()
    except httpx.HTTPError:
        return None


def poser_question(question: str, top_k: int) -> tuple[dict | None, str | None, float]:
    """Appelle /ask et retourne (résultat, message d'erreur, durée)."""
    depart = time.perf_counter()
    try:
        reponse = httpx.post(api("/ask"), timeout=TIMEOUT_QUESTION,
                             json={"question": question, "top_k": top_k})
        duree = time.perf_counter() - depart
        if reponse.status_code == 200:
            return reponse.json(), None, duree
        detail = reponse.json().get("detail", reponse.text)
        if isinstance(detail, list):  # erreur de validation Pydantic
            detail = " · ".join(e.get("msg", "") for e in detail)
        return None, f"L'API a répondu {reponse.status_code} : {detail}", duree
    except httpx.HTTPError as exc:
        return None, f"API injoignable : {exc}", time.perf_counter() - depart


def afficher_sources(sources: list[dict]) -> None:
    st.markdown(f"##### Sources — {len(sources)} événement(s) consulté(s)")
    for source in sources:
        lieu = " · ".join(x for x in (source.get("lieu"), source.get("ville")) if x)
        st.markdown(
            f"""<div class="source-carte">
              <div class="source-titre">{source.get('titre', 'Sans titre')}</div>
              <div class="source-detail">{source.get('periode', '')}{' — ' + lieu if lieu else ''}</div>
              <div class="source-detail">
                <a href="{source.get('url', '#')}" target="_blank">Voir la fiche Open Agenda</a>
                &nbsp;·&nbsp; distance {source.get('score', 0):.3f}
              </div>
            </div>""",
            unsafe_allow_html=True,
        )


def barre_laterale() -> tuple[int, dict | None]:
    """État de l'index, réglage de la récupération et administration."""
    with st.sidebar:
        st.markdown("### État du système")
        etat = etat_index()

        if etat is None:
            st.error("API injoignable.")
            st.code("docker compose up\n# ou : uv run python main.py", language="bash")
        elif not etat.get("index_ready"):
            st.warning("Aucun index vectoriel.")
            st.code("uv run python scripts/rebuild_all.py --yes", language="bash")
        else:
            st.success("Index chargé")
            gauche, droite = st.columns(2)
            gauche.metric("Chunks indexés", f"{etat.get('chunks_indexed', 0):,}".replace(",", " "))
            droite.metric("Embeddings", etat.get("embedding_provider", "—"))

        st.divider()
        st.markdown("### Récupération")
        top_k = st.slider(
            "Événements consultés", min_value=1, max_value=10, value=settings.top_k,
            help="Nombre d'événements distincts transmis au modèle pour rédiger la réponse.",
        )

        st.divider()
        with st.expander("Administration"):
            st.caption(
                "La reconstruction recollecte les événements et recalcule tout l'index. "
                "Compter environ une minute, et des appels facturés à l'API Mistral."
            )
            jeton = st.text_input("Jeton X-API-Key", type="password",
                                  help="Requis seulement si REBUILD_TOKEN est configuré.")
            if st.button("Reconstruire l'index", use_container_width=True):
                reconstruire(jeton)
        st.caption(f"API : {settings.api_base_url}")
    return top_k, etat


def reconstruire(jeton: str) -> None:
    entetes = {"X-API-Key": jeton} if jeton else {}
    with st.spinner("Collecte, nettoyage, vectorisation, indexation…"):
        try:
            reponse = httpx.post(api("/rebuild"), headers=entetes,
                                 timeout=TIMEOUT_RECONSTRUCTION)
        except httpx.HTTPError as exc:
            st.error(f"Reconstruction impossible : {exc}")
            return
    if reponse.status_code == 200:
        corps = reponse.json()
        st.success(
            f"{corps['events_collected']} événements collectés, "
            f"{corps['chunks_indexed']} chunks indexés en {corps['duration_seconds']} s."
        )
        etat_index.clear()
    elif reponse.status_code == 401:
        st.error("Jeton d'administration invalide ou absent.")
    else:
        st.error(f"Échec ({reponse.status_code}) : {reponse.json().get('detail', '')}")


def main() -> None:
    st.set_page_config(page_title="Puls-Events — Assistant culturel",
                       page_icon="🎭", layout="wide")
    st.markdown(STYLE, unsafe_allow_html=True)

    top_k, etat = barre_laterale()

    st.title("Assistant de recommandation d'événements culturels")
    st.caption(
        "Les réponses sont rédigées à partir des seuls événements Open Agenda indexés. "
        "Chaque recommandation est accompagnée de sa fiche source, vérifiable."
    )

    # La clé d'état ne doit pas coïncider avec celle d'un widget : Streamlit
    # refuse alors l'affectation (StreamlitValueAssignmentNotAllowedError).
    if "question_choisie" not in st.session_state:
        st.session_state.question_choisie = ""

    st.markdown("**Exemples**")
    colonnes = st.columns(len(EXEMPLES))
    for colonne, (libelle, question) in zip(colonnes, EXEMPLES, strict=True):
        if colonne.button(libelle, use_container_width=True):
            st.session_state.question_choisie = question

    with st.form("formulaire_question"):
        question = st.text_input(
            "Votre question", value=st.session_state.question_choisie,
            placeholder="Quels concerts de jazz puis-je voir à Paris ?",
        )
        envoyer = st.form_submit_button("Demander une recommandation", type="primary")

    if not envoyer:
        return
    if len(question.strip()) < 3:
        st.warning("Formulez une question d'au moins trois caractères.")
        return

    st.session_state.question_choisie = question
    with st.spinner("Recherche dans le catalogue, puis rédaction…"):
        resultat, erreur, duree = poser_question(question.strip(), top_k)

    if erreur:
        st.error(erreur)
        if etat is None:
            st.info("Démarrez l'API, puis rechargez cette page.")
        return

    if resultat.get("warnings"):
        st.warning(
            "**Validation des sorties** — anomalie détectée dans la réponse du modèle :\n\n"
            + "\n".join(f"- {a}" for a in resultat["warnings"])
        )

    st.markdown(f'<div class="reponse">{resultat["answer"]}</div>', unsafe_allow_html=True)
    st.caption(
        f"Réponse en {duree:.1f} s · {resultat.get('events_found', 0)} événements retenus "
        f"parmi les {top_k * 4} chunks les plus proches"
    )

    if resultat.get("sources"):
        st.divider()
        afficher_sources(resultat["sources"])


if __name__ == "__main__":
    main()
