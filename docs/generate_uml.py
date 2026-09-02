"""Génère les schémas UML du système, en PNG et en SVG.

Deux diagrammes, conformes à la notation UML 2.5 :

- **Diagramme de composants** — la structure statique : quels composants
  existent, quelles interfaces ils fournissent ou requièrent, et de quoi ils
  dépendent. C'est le schéma demandé en section 2 du rapport.
- **Diagramme de séquence** — le déroulé d'un appel à ``/ask``, du navigateur
  jusqu'à la réponse validée, avec les deux acteurs externes que sont l'API
  Mistral et l'index sur disque.

Les schémas sont dessinés plutôt qu'exportés d'un outil : ni Graphviz ni
PlantUML ne sont disponibles ici, et le tracé direct garantit que la notation et
la palette restent alignées sur les autres livrables.

Usage :
    uv run --with matplotlib python docs/generate_uml.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
from matplotlib.patches import Arc, Circle, FancyBboxPatch, Polygon, Rectangle

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DOSSIER = Path(__file__).resolve().parent

ENCRE = "#1B2430"
ENCRE_DOUCE = "#3C4757"
GRIS = "#5B6675"
PAPIER = "#FFFFFF"
SURFACE = "#F7F9FA"
ACCENT = "#B8420F"
ACCENT_PALE = "#FBF0EA"
DATA = "#26636F"
DATA_PALE = "#E4EFF1"
REGLE = "#C9D2DB"

SANS = "DejaVu Sans"


# --------------------------------------------------------------------------- #
# Primitives de notation UML
# --------------------------------------------------------------------------- #

def composant(ax, x, y, w, h, nom, sous_titre="", couleur=SURFACE,
              bordure=REGLE, stereotype="component"):
    """Composant UML : rectangle, stéréotype, et l'icône à deux ergots."""
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.06",
        facecolor=couleur, edgecolor=bordure, linewidth=1.1, zorder=2))

    # Icône de composant : petit rectangle et ses deux languettes, en haut à droite.
    ix, iy = x + w - 0.42, y + h - 0.30
    ax.add_patch(Rectangle((ix, iy), 0.26, 0.17, facecolor=PAPIER,
                           edgecolor=GRIS, linewidth=0.8, zorder=3))
    for dy in (0.115, 0.025):
        ax.add_patch(Rectangle((ix - 0.07, iy + dy), 0.10, 0.045, facecolor=PAPIER,
                               edgecolor=GRIS, linewidth=0.8, zorder=4))

    ax.text(x + 0.16, y + h - 0.16, f"«{stereotype}»", fontsize=6.4, color=GRIS,
            style="italic", family=SANS, va="center", zorder=5)
    ax.text(x + 0.16, y + h - 0.38, nom, fontsize=8.6, color=ENCRE, family=SANS,
            weight="bold", va="center", zorder=5)
    if sous_titre:
        for i, ligne in enumerate(sous_titre.split("\n")):
            ax.text(x + 0.16, y + h - 0.58 - i * 0.17, ligne, fontsize=6.9,
                    color=ENCRE_DOUCE, family=SANS, va="center", zorder=5)


def interface_fournie(ax, x, y, nom, cote="droite", couleur=DATA, longueur=0.30):
    """Interface fournie : la « sucette » — un trait et un cercle plein."""
    dx = longueur if cote == "droite" else -longueur
    ax.plot([x, x + dx], [y, y], color=couleur, linewidth=1.2, zorder=3)
    ax.add_patch(Circle((x + dx * 1.25, y), 0.075, facecolor=PAPIER,
                        edgecolor=couleur, linewidth=1.2, zorder=4))
    # Au-dessus du cercle plutôt qu'à côté : entre deux composants voisins,
    # une étiquette latérale recouvre le stéréotype du composant suivant.
    ax.text(x + dx * 1.25, y + 0.21, nom, fontsize=6.6, color=couleur, family=SANS,
            ha="center", va="center", zorder=5,
            bbox={"facecolor": PAPIER, "edgecolor": "none", "pad": 1.0})


def interface_requise(ax, x, y, cote="gauche", couleur=DATA, nom="", longueur=0.30):
    """Interface requise : le « socket » — un trait et un demi-cercle ouvert.

    La coupe doit s'ouvrir vers la sucette qui la sert, pour que l'une paraisse
    emboîtée dans l'autre. Avec un socket sur l'arête gauche d'un composant, la
    sucette arrive de la gauche : l'ouverture regarde donc à gauche, soit la
    moitié droite du cercle, sans rotation.
    """
    dx = -longueur if cote == "gauche" else longueur
    ax.plot([x, x + dx], [y, y], color=couleur, linewidth=1.2, zorder=3)
    angle = 0 if cote == "gauche" else 180
    ax.add_patch(Arc((x + dx * 1.25, y), 0.2, 0.2, angle=angle,
                     theta1=-90, theta2=90, color=couleur, linewidth=1.4, zorder=4))
    if nom:
        ax.text(x + dx * 1.25, y + 0.21, nom, fontsize=6.6, color=couleur, family=SANS,
                ha="center", va="center", zorder=5,
                bbox={"facecolor": PAPIER, "edgecolor": "none", "pad": 1.0})


def dependance(ax, xy1, xy2, etiquette="", couleur=GRIS, courbure=0.0,
               etiquette_xy=None):
    """Dépendance UML : flèche en pointillés, pointe ouverte."""
    ax.annotate("", xy=xy2, xytext=xy1,
                arrowprops={"arrowstyle": "-|>", "color": couleur, "linewidth": 1.0,
                            "linestyle": (0, (4, 2.5)), "shrinkA": 2, "shrinkB": 2,
                            "connectionstyle": f"arc3,rad={courbure}",
                            "mutation_scale": 11})
    if etiquette:
        # Sur une flèche courbe, le milieu du segment n'est pas sur le tracé :
        # la position est alors donnée explicitement.
        mx, my = etiquette_xy or ((xy1[0] + xy2[0]) / 2, (xy1[1] + xy2[1]) / 2)
        vertical = abs(xy2[0] - xy1[0]) < 0.2 and not etiquette_xy
        ax.text(mx + (0.12 if vertical else 0), my + (0 if vertical else 0.13),
                etiquette, fontsize=6.3, color=couleur, family=SANS,
                ha="left" if vertical else "center", va="center", style="italic",
                bbox={"facecolor": PAPIER, "edgecolor": "none", "pad": 1.2}, zorder=6)


def note(ax, x, y, w, h, texte, ancre=None):
    """Note UML : rectangle au coin supérieur droit replié, reliée à son élément.

    Un simple texte en italique sous un composant n'appartient pas à la notation :
    la note est un élément UML à part entière, et le trait dit à quoi elle se
    rapporte.
    """
    pli = 0.16
    contour = [(x, y), (x + w, y), (x + w, y + h - pli), (x + w - pli, y + h),
               (x, y + h), (x, y)]
    ax.add_patch(Polygon(contour, closed=True, facecolor="#FFFBF5",
                         edgecolor=GRIS, linewidth=0.9, zorder=2))
    ax.plot([x + w - pli, x + w - pli, x + w],
            [y + h, y + h - pli, y + h - pli],
            color=GRIS, linewidth=0.9, zorder=3)
    for i, ligne in enumerate(texte.split("\n")):
        ax.text(x + 0.11, y + h - 0.20 - i * 0.17, ligne, fontsize=6.5, color=ENCRE_DOUCE,
                family=SANS, va="center", zorder=4)
    if ancre:
        ax.plot([x + w, ancre[0]], [y + h / 2, ancre[1]], color=GRIS, linewidth=0.8,
                linestyle=(0, (2, 2)), zorder=1)


def flux(ax, xy1, xy2, etiquette=""):
    """Flux d'objets entre deux étapes du pipeline.

    Distinct de la dépendance : preprocessing n'importe pas open_agenda, c'est le
    script d'orchestration qui les enchaîne. Une flèche « use » entre les deux
    affirmerait un couplage qui n'existe pas.
    """
    ax.annotate("", xy=xy2, xytext=xy1,
                arrowprops={"arrowstyle": "-|>", "color": DATA, "linewidth": 1.1,
                            "shrinkA": 2, "shrinkB": 2, "mutation_scale": 11})
    if etiquette:
        ax.text((xy1[0] + xy2[0]) / 2 + 0.12, (xy1[1] + xy2[1]) / 2, etiquette,
                fontsize=6.3, color=DATA, family=SANS, ha="left", va="center",
                style="italic", zorder=6)


def paquet(ax, x, y, w, h, nom, couleur=REGLE):
    """Paquet UML : rectangle à onglet."""
    onglet_l, onglet_h = 1.5, 0.24
    ax.add_patch(Rectangle((x, y + h), onglet_l, onglet_h, facecolor="none",
                           edgecolor=couleur, linewidth=1.0, linestyle=(0, (3, 2)),
                           zorder=1))
    ax.add_patch(Rectangle((x, y), w, h, facecolor="none", edgecolor=couleur,
                           linewidth=1.0, linestyle=(0, (3, 2)), zorder=1))
    ax.text(x + 0.12, y + h + onglet_h / 2, nom, fontsize=7, color=GRIS,
            family=SANS, weight="bold", va="center", zorder=2)


# --------------------------------------------------------------------------- #
# Diagramme de composants
# --------------------------------------------------------------------------- #

def diagramme_composants() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(11.6, 7.4))
    ax.set_xlim(0, 11.6)
    ax.set_ylim(0, 7.4)
    ax.axis("off")
    fig.patch.set_facecolor(PAPIER)

    ax.text(0.15, 7.12, "Diagramme de composants — Puls-Events RAG", fontsize=12.5,
            color=ENCRE, family=SANS, weight="bold")
    ax.text(0.15, 6.86, "Structure statique : composants, interfaces fournies et requises, "
                        "dépendances", fontsize=7.6, color=GRIS, family=SANS)

    # ---- systèmes externes ----
    paquet(ax, 0.15, 4.05, 2.60, 2.30, "Systèmes externes")
    composant(ax, 0.32, 5.42, 2.26, 0.85, "Opendatasoft",
              "API Explore v2.1\nsans clé requise",
              couleur=DATA_PALE, bordure=DATA, stereotype="external system")
    composant(ax, 0.32, 4.25, 2.26, 0.85, "Mistral AI",
              "mistral-embed\nmistral-small-latest",
              couleur=DATA_PALE, bordure=DATA, stereotype="external system")

    # ---- configuration, transverse ----
    composant(ax, 0.32, 2.62, 2.26, 0.85, "config",
              "paramètres centralisés\nlus depuis .env")
    note(ax, 0.32, 1.62, 2.26, 0.78,
         "Lue par tous les composants :\nvilles, période, modèles,\nseuils, jetons d'API.",
         ancre=(2.58, 2.90))

    # ---- pipeline hors ligne ----
    paquet(ax, 3.20, 3.55, 3.55, 2.80, "Pipeline d'indexation  «hors ligne»")
    composant(ax, 3.40, 5.45, 3.15, 0.72, "ingestion.open_agenda",
              "collecte filtrée, pagination")
    composant(ax, 3.40, 4.55, 3.15, 0.72, "ingestion.preprocessing",
              "nettoyage, chunking")
    composant(ax, 3.40, 3.72, 3.15, 0.72, "vectorstore.embeddings",
              "Mistral ou HuggingFace")

    # ---- base vectorielle ----
    composant(ax, 7.35, 4.95, 3.15, 0.85, "vectorstore.faiss_store",
              "construction, persistance,\nvérification",
              couleur=ACCENT_PALE, bordure=ACCENT)
    ax.add_patch(FancyBboxPatch((7.35, 3.62), 3.15, 0.85,
                                boxstyle="round,pad=0,rounding_size=0.06",
                                facecolor=SURFACE, edgecolor=REGLE, linewidth=1.1))
    ax.text(7.51, 4.31, "«artifact»", fontsize=6.4, color=GRIS, style="italic", family=SANS)
    ax.text(7.51, 4.09, "data/index/", fontsize=8.6, color=ENCRE, family=SANS, weight="bold")
    ax.text(7.51, 3.89, "index.faiss · index.pkl", fontsize=6.9,
            color=ENCRE_DOUCE, family=SANS)
    ax.text(7.51, 3.72, "index_meta.json", fontsize=6.9, color=ENCRE_DOUCE, family=SANS)

    # ---- chaîne temps réel ----
    paquet(ax, 3.20, 0.72, 7.30, 2.35, "Chaîne d'inférence  «temps réel»")
    composant(ax, 3.40, 1.92, 3.15, 0.85, "rag.chain",
              "récupération, déduplication,\naugmentation, validation",
              couleur=ACCENT_PALE, bordure=ACCENT)
    composant(ax, 3.40, 0.92, 3.15, 0.72, "rag.prompts",
              "prompt système, gabarit de fiche")
    composant(ax, 7.15, 1.92, 3.15, 0.85, "api.main",
              "/ask · /rebuild · /health\n/docs (Swagger)",
              couleur=ACCENT_PALE, bordure=ACCENT)
    composant(ax, 7.15, 0.92, 3.15, 0.72, "api.schemas",
              "validation des requêtes")

    # ---- interfaces ----
    interface_fournie(ax, 2.58, 5.84, "IEvenements", "droite", DATA)
    interface_requise(ax, 3.40, 5.84, "gauche", DATA)
    interface_fournie(ax, 2.58, 4.67, "IModeles", "droite", DATA)
    # Coupes légèrement rapprochées du composant : le tronc de IModeles descend
    # à l'aplomb de la bille et ne doit pas les traverser.
    interface_requise(ax, 3.40, 4.08, "gauche", DATA, longueur=0.20)
    interface_requise(ax, 3.40, 2.35, "gauche", DATA, longueur=0.20)
    interface_fournie(ax, 10.50, 5.37, "IRecherche", "droite", ACCENT)
    interface_fournie(ax, 10.30, 2.34, "IReponse", "droite", ACCENT)

    # ---- dépendances ----
    # Flux de données du pipeline : événements bruts, puis chunks.
    flux(ax, (4.98, 5.45), (4.98, 5.29), "événements bruts")
    flux(ax, (4.98, 4.55), (4.98, 4.46), "chunks")

    # faiss_store dépend de embeddings, et non l'inverse : c'est lui qui appelle
    # le modèle pour vectoriser. La flèche pointait dans le mauvais sens.
    # Point d'attache haut sur faiss_store : plus bas, cette flèche s'emmêlait
    # avec celle de rag.chain qui arrive sur la même arête.
    dependance(ax, (7.35, 5.62), (6.55, 4.32), "«use»", etiquette_xy=(7.02, 5.08))
    dependance(ax, (8.92, 4.95), (8.92, 4.52), "«create»")

    # rag.chain lit l'index : c'est donc lui le dépendant. La flèche partait de
    # l'artefact, ce qui affirmait que l'index dépendait de la chaîne. Elle vise
    # maintenant faiss_store, qui fournit IRecherche, et non l'artefact lui-même.
    dependance(ax, (5.30, 2.79), (7.33, 4.98), "«use» IRecherche", courbure=-0.10,
               etiquette_xy=(6.55, 3.42))
    dependance(ax, (4.98, 1.92), (4.98, 1.66), "«use»")
    dependance(ax, (8.72, 1.92), (8.72, 1.66), "«use»")
    dependance(ax, (7.15, 2.34), (6.55, 2.34), "appelle")
    # Connecteur d'assemblage : IModeles est fournie une fois et requise deux
    # fois. Le tronc part de la bille elle-même — il bifurquait auparavant en
    # amont, si bien que la bille paraissait sans suite — et chaque dérivation
    # rejoint l'ouverture de sa coupe.
    ax.plot([2.955, 2.955], [4.67, 2.35], color=DATA, linewidth=1.1,
            solid_capstyle="round", zorder=1)
    # La dérivation rejoint l'ouverture de la coupe, à l'aplomb de son centre :
    # s'arrêter à son bord extérieur laissait un jeu visible.
    ax.plot([2.955, 3.15], [4.08, 4.08], color=DATA, linewidth=1.1, zorder=1)
    ax.plot([2.955, 3.15], [2.35, 2.35], color=DATA, linewidth=1.1, zorder=1)
    ax.add_patch(Circle((2.955, 4.08), 0.035, facecolor=DATA, edgecolor="none", zorder=3))

    # ---- légende ----
    y = 0.28
    ax.plot([0.20, 0.50], [y, y], color=DATA, linewidth=1.2)
    ax.add_patch(Circle((0.58, y), 0.075, facecolor=PAPIER, edgecolor=DATA, linewidth=1.2))
    ax.text(0.72, y, "interface fournie", fontsize=6.8, color=GRIS, family=SANS, va="center")
    ax.plot([2.30, 2.60], [y, y], color=DATA, linewidth=1.2)
    ax.add_patch(Arc((2.68, y), 0.2, 0.2, angle=270, theta1=-90, theta2=90,
                     color=DATA, linewidth=1.4))
    ax.text(2.85, y, "interface requise", fontsize=6.8, color=GRIS, family=SANS, va="center")
    ax.annotate("", xy=(5.05, y), xytext=(4.55, y),
                arrowprops={"arrowstyle": "-|>", "color": GRIS, "linewidth": 1.0,
                            "linestyle": (0, (4, 2.5)), "mutation_scale": 11})
    ax.text(5.20, y, "dépendance", fontsize=6.8, color=GRIS, family=SANS, va="center")
    ax.add_patch(Rectangle((6.65, y - 0.08), 0.22, 0.16, facecolor=ACCENT_PALE,
                           edgecolor=ACCENT, linewidth=1.0))
    ax.text(6.97, y, "composant du cœur métier", fontsize=6.8, color=GRIS,
            family=SANS, va="center")
    ax.add_patch(Rectangle((8.85, y - 0.08), 0.22, 0.16, facecolor=DATA_PALE,
                           edgecolor=DATA, linewidth=1.0))
    ax.text(9.17, y, "système externe", fontsize=6.8, color=GRIS, family=SANS, va="center")

    fig.tight_layout(pad=0.4)
    return fig


# --------------------------------------------------------------------------- #
# Diagramme de séquence
# --------------------------------------------------------------------------- #

def ligne_de_vie(ax, x, y_haut, y_bas, nom, sous_titre="", couleur=SURFACE,
                 bordure=REGLE, acteur=False):
    largeur = 1.62
    hauteur = 0.52
    ax.add_patch(FancyBboxPatch(
        (x - largeur / 2, y_haut), largeur, hauteur,
        boxstyle="round,pad=0,rounding_size=0.05",
        facecolor=couleur, edgecolor=bordure, linewidth=1.1, zorder=3))
    ax.text(x, y_haut + hauteur - 0.17, ("«actor» " if acteur else "") + nom,
            fontsize=7.8, color=ENCRE, family=SANS, weight="bold",
            ha="center", va="center", zorder=4)
    if sous_titre:
        ax.text(x, y_haut + 0.14, sous_titre, fontsize=6.3, color=GRIS,
                family=SANS, ha="center", va="center", zorder=4)
    ax.plot([x, x], [y_bas, y_haut], color=REGLE, linewidth=0.9,
            linestyle=(0, (3, 3)), zorder=1)


def activation(ax, x, y_bas, y_haut, couleur=ACCENT):
    ax.add_patch(Rectangle((x - 0.055, y_bas), 0.11, y_haut - y_bas,
                           facecolor=PAPIER, edgecolor=couleur, linewidth=1.0, zorder=2))


def message(ax, x1, x2, y, texte, retour=False, couleur=ENCRE_DOUCE, decalage=0.11):
    style = "-|>" if not retour else "->"
    ax.annotate("", xy=(x2, y), xytext=(x1, y),
                arrowprops={"arrowstyle": style, "color": couleur, "linewidth": 1.0,
                            "linestyle": (0, (4, 2.5)) if retour else "solid",
                            "shrinkA": 3, "shrinkB": 3, "mutation_scale": 11})
    ax.text((x1 + x2) / 2, y + decalage, texte, fontsize=6.6,
            color=couleur if not retour else GRIS, family=SANS, ha="center",
            va="bottom", style="italic" if retour else "normal",
            bbox={"facecolor": PAPIER, "edgecolor": "none", "pad": 1.0}, zorder=6)


def auto_message(ax, x, y, texte, couleur=ENCRE_DOUCE, hauteur=0.30, largeur=0.42):
    """Message réflexif : le crochet UML, et son libellé dégagé de la ligne de vie."""
    x0 = x + 0.055
    ax.plot([x0, x0 + largeur, x0 + largeur, x0 + 0.08],
            [y, y, y - hauteur, y - hauteur],
            color=couleur, linewidth=1.0, solid_capstyle="butt", zorder=4)
    ax.annotate("", xy=(x0, y - hauteur), xytext=(x0 + 0.09, y - hauteur),
                arrowprops={"arrowstyle": "-|>", "color": couleur, "linewidth": 1.0,
                            "mutation_scale": 10})
    for i, ligne in enumerate(texte.split("\n")):
        ax.text(x0 + largeur + 0.12, y - 0.05 - i * 0.16, ligne, fontsize=6.4,
                color=GRIS, family=SANS, va="center", zorder=5)


def fragment(ax, x, y, w, h, operateur, condition="", texte="", decalage_texte=0.12):
    """Fragment combiné UML : cadre, onglet d'opérateur, garde."""
    ax.add_patch(Rectangle((x, y), w, h, facecolor="none", edgecolor=DATA,
                           linewidth=0.9, zorder=1))
    ax.add_patch(Rectangle((x, y + h - 0.24), 0.62, 0.24, facecolor=DATA_PALE,
                           edgecolor=DATA, linewidth=0.9, zorder=2))
    ax.text(x + 0.31, y + h - 0.12, operateur, fontsize=6.4, color=DATA, family=SANS,
            weight="bold", ha="center", va="center", zorder=3)
    if condition:
        ax.text(x + 0.70, y + h - 0.12, f"[{condition}]", fontsize=6.3, color=DATA,
                family=SANS, va="center", zorder=3,
                bbox={"facecolor": PAPIER, "edgecolor": "none", "pad": 1.0})
    if texte:
        # Décalé à droite de la ligne de vie : à gauche, le fond blanc du libellé
        # perforait la barre d'activation, qui paraissait alors discontinue.
        for i, ligne in enumerate(texte.split("\n")):
            ax.text(x + decalage_texte, y + h - 0.44 - i * 0.17, ligne, fontsize=6.3,
                    color=DATA, family=SANS, va="center", zorder=3)


def diagramme_sequence() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(11.5, 7.0))
    ax.set_xlim(0, 11.5)
    ax.set_ylim(0, 7.0)
    ax.axis("off")
    fig.patch.set_facecolor(PAPIER)

    ax.text(0.15, 6.75, "Diagramme de séquence — traitement d'un appel POST /ask",
            fontsize=12.5, color=ENCRE, family=SANS, weight="bold")
    ax.text(0.15, 6.48, "Du navigateur à la réponse validée, avec les deux acteurs externes",
            fontsize=7.6, color=GRIS, family=SANS)

    colonnes = [
        (0.95, "Utilisateur", "navigateur / curl", SURFACE, REGLE, True),
        (2.95, "api.main", "FastAPI", ACCENT_PALE, ACCENT, False),
        (4.95, "rag.chain", "LangChain LCEL", ACCENT_PALE, ACCENT, False),
        (6.95, "faiss_store", "index en cache", SURFACE, REGLE, False),
        (9.55, "Mistral AI", "API distante", DATA_PALE, DATA, True),
    ]
    y_haut, y_bas = 5.72, 0.48
    for x, nom, sous, couleur, bordure, acteur in colonnes:
        ligne_de_vie(ax, x, y_haut, y_bas, nom, sous, couleur, bordure, acteur)

    xu, xa, xc, xf, xm = (c[0] for c in colonnes)

    activation(ax, xa, 0.58, 5.55)
    activation(ax, xc, 0.80, 4.82)
    activation(ax, xf, 3.22, 4.60)
    activation(ax, xm, 4.18, 4.40, DATA)
    activation(ax, xm, 1.90, 2.34, DATA)

    message(ax, xu, xa, 5.48, "POST /ask  {question, top_k}")
    auto_message(ax, xa, 5.32, "valider le schéma\n422 si le format est invalide",
                 hauteur=0.28)

    message(ax, xa, xc, 4.72, "answer_question(question, k)")
    message(ax, xc, xf, 4.50, "similarity_search(k × 4)")
    message(ax, xf, xm, 4.28, "embed_query(question)", couleur=DATA)
    message(ax, xm, xf, 4.00, "vecteur 1 024 dimensions  ·  80 ms", retour=True)
    auto_message(ax, xf, 3.80, "recherche L2 exhaustive  ·  0,17 ms", hauteur=0.28)
    message(ax, xf, xc, 3.30, "20 chunks + métadonnées", retour=True)

    # Les fragments sont centrés sur la ligne de vie de rag.chain, seul
    # participant : un cadre décalé laisserait croire qu'il en couvre d'autres.
    fragment(ax, 4.30, 2.52, 2.30, 0.68, "loop", "sur les 20 chunks",
             "déduplication par uid\n5 événements distincts retenus", decalage_texte=0.82)

    message(ax, xc, xm, 2.24, "chat(prompt augmenté)", couleur=DATA)
    message(ax, xm, xc, 1.94, "réponse rédigée  ·  ~2 s", retour=True)

    # « opt » et non « alt » : le fragment n'a qu'un opérande, exécuté ou non
    # selon la garde. Un « alt » exigerait une alternative séparée par un trait.
    fragment(ax, 4.30, 1.10, 2.30, 0.68, "opt", "URL hors sources",
             "retirée de la réponse\net signalée dans warnings", decalage_texte=0.82)

    message(ax, xc, xa, 0.80, "{answer, sources, warnings}", retour=True)
    message(ax, xa, xu, 0.62, "200 OK  ·  JSON", retour=True)

    ax.text(0.15, 0.22, "Total ≈ 2,4 s — dominé par les deux appels à l'API Mistral. "
                        "La recherche vectorielle en représente 0,007 %.",
            fontsize=6.9, color=GRIS, family=SANS, style="italic")

    fig.tight_layout(pad=0.4)
    return fig


# --------------------------------------------------------------------------- #

def main() -> None:
    for nom, fabrique in [("uml-composants", diagramme_composants),
                          ("uml-sequence", diagramme_sequence)]:
        figure = fabrique()
        for extension, dpi in [("png", 220), ("svg", None)]:
            chemin = DOSSIER / f"{nom}.{extension}"
            figure.savefig(chemin, format=extension, dpi=dpi,
                           facecolor=PAPIER, bbox_inches="tight", pad_inches=0.12)
            print(f"  {chemin.name}")
        plt.close(figure)


if __name__ == "__main__":
    main()
