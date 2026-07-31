# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dimensionnement des dialogues : ne jamais dépasser l'écran qui les accueille.

Un poste de terrain passe d'un grand écran de bureau à l'écran du portable seul,
avec des résolutions différentes. Un dialogue dimensionné par son contenu — le
formulaire station compte désormais une vingtaine de champs — dépasse alors la
hauteur disponible, et ses boutons « OK / Annuler » se retrouvent sous le bord de
l'écran : l'utilisateur ne peut plus valider sa saisie, ni même savoir pourquoi.

Deux mesures complémentaires :

- le contenu devient **défilant** (`rendre_defilant`), les boutons restant
  ancrés hors de la zone qui défile — c'est ce qui garantit qu'ils sont
  toujours atteignables ;
- la taille est **bornée à l'écran courant** (`ajuster_a_l_ecran`), recalculée
  **à chaque affichage** : entre deux ouvertures, l'utilisateur a pu débrancher
  un écran, changer de résolution, ou déplacer QGIS sur un autre moniteur.

L'écran retenu est celui qui accueille réellement le dialogue (ou son parent),
pas l'écran principal : sur deux moniteurs de tailles différentes, borner sur le
mauvais donnerait soit une fenêtre tronquée, soit une fenêtre inutilement petite.
"""
from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import QFrame, QScrollArea

# Marge laissée autour du dialogue : barre des tâches, décorations de fenêtre,
# et de quoi attraper les bords à la souris.
MARGE = 80
_LARGEUR_MINI = 320
_HAUTEUR_MINI = 240


def ecran_de(widget):
    """Écran qui accueille le widget (à défaut celui du parent, sinon le principal)."""
    candidats = [widget, widget.parent() if widget is not None else None]
    for candidat in candidats:
        if candidat is None:
            continue
        ecran = getattr(candidat, "screen", None)
        ecran = ecran() if callable(ecran) else None
        if ecran is not None:
            return ecran
    return QGuiApplication.primaryScreen()


def ajuster_a_l_ecran(dialog, largeur=0, hauteur=0, marge=MARGE):
    """Borner la taille du dialogue à l'écran courant et le ramener dedans.

    `largeur` / `hauteur` sont les dimensions *souhaitées* ; 0 laisse le contenu
    décider. Le résultat ne dépasse jamais la zone disponible de l'écran.
    """
    ecran = ecran_de(dialog)
    if ecran is None:  # pragma: no cover - aucun écran (tests hors session graphique)
        return
    dispo = ecran.availableGeometry()
    max_largeur = max(_LARGEUR_MINI, dispo.width() - marge)
    max_hauteur = max(_HAUTEUR_MINI, dispo.height() - marge)

    souhaitee = dialog.sizeHint()
    dialog.resize(
        min(largeur or souhaitee.width(), max_largeur),
        min(hauteur or souhaitee.height(), max_hauteur),
    )

    # Recentrer si le dialogue déborde : après un débranchement d'écran, la
    # position héritée peut le placer entièrement hors du moniteur restant.
    geometrie = dialog.frameGeometry()
    if not dispo.contains(geometrie):
        geometrie.moveCenter(dispo.center())
        dialog.move(geometrie.topLeft())


def rendre_defilant(contenu):
    """Envelopper un widget dans une zone défilante sans cadre."""
    zone = QScrollArea()
    zone.setWidgetResizable(True)
    zone.setFrameShape(QFrame.Shape.NoFrame)
    zone.setWidget(contenu)
    return zone
