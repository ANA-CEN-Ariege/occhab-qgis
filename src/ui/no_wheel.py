# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Empêcher la molette de modifier une valeur saisie.

Par défaut, Qt fait varier un `QSpinBox`, un `QComboBox` ou un `QDateEdit` sous
le curseur quand on utilise la molette. Dans un formulaire long, on fait défiler
le panneau et on modifie des données **sans le voir** : c'est ainsi qu'une
altitude maximale est passée de 344 à 343 — un cran de molette — et que la
station a été refusée par GeoNature (`altitude_max >= altitude_min`).

La molette est donc neutralisée sur ces champs, et transmise au conteneur
défilant pour que le panneau continue de défiler normalement.
"""
from qgis.PyQt.QtCore import QEvent, QObject
from qgis.PyQt.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDateTimeEdit,
)

#: Widgets dont la molette change la valeur.
SENSIBLES = (QAbstractSpinBox, QComboBox, QDateTimeEdit)


def _zone_defilante(widget):
    """Premier ancêtre défilant, pour lui transmettre la molette."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


class FiltreMolette(QObject):
    """Consomme les événements molette et les renvoie au conteneur défilant."""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.Wheel:
            return False
        zone = _zone_defilante(obj)
        if zone is not None:
            # Le panneau doit continuer de défiler : sans cela, survoler un champ
            # bloquerait le défilement, ce qui serait tout aussi déroutant.
            QApplication.sendEvent(zone.viewport(), event)
        return True  # jamais transmis au champ : la valeur ne bouge pas


def proteger_du_defilement(racine, filtre=None):
    """Neutraliser la molette sur `racine` et tous ses champs de saisie.

    Renvoie le filtre installé — l'appelant DOIT le garder référencé, un QObject
    Python détruit cesse de filtrer.
    """
    filtre = filtre or FiltreMolette(racine)
    cibles = list(racine.findChildren(SENSIBLES))
    if isinstance(racine, SENSIBLES):
        cibles.append(racine)
    for widget in cibles:
        widget.installEventFilter(filtre)
    return filtre
