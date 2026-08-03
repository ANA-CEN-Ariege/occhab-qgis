# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Disposition qui passe à la ligne quand la largeur manque.

Une `QHBoxLayout` ne sait pas replier : ses widgets sont rognés dès que le
conteneur rétrécit. Dans un dock ancré — dont l'utilisateur choisit la largeur —
c'est la barre d'actions qui imposait alors sa largeur au panneau entier
(547 px mesurés), et tout ce qui dépassait était coupé sans être atteignable.

Ici les éléments gardent leur taille naturelle, donc leurs libellés, et
s'écoulent sur autant de rangées que nécessaire.

Portage de l'exemple « Flow Layout » de Qt.
"""
from qgis.PyQt.QtCore import QPoint, QRect, QSize, Qt
from qgis.PyQt.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    """Place les éléments de gauche à droite, en repliant sur plusieurs rangées."""

    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    # -- interface QLayout ---------------------------------------------
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._disposer(QRect(0, 0, width, 0), essai=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._disposer(rect, essai=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        """Le plus large élément seul — c'est ce qui autorise le dock à rétrécir."""
        taille = QSize()
        for item in self._items:
            taille = taille.expandedTo(item.minimumSize())
        marges = self.contentsMargins()
        taille += QSize(marges.left() + marges.right(),
                        marges.top() + marges.bottom())
        return taille

    # -- calcul ---------------------------------------------------------
    def _disposer(self, rect, essai):
        """Écouler les éléments ; renvoie la hauteur totale nécessaire."""
        marges = self.contentsMargins()
        zone = rect.adjusted(marges.left(), marges.top(),
                             -marges.right(), -marges.bottom())
        x, y = zone.x(), zone.y()
        hauteur_ligne = 0
        ecart = self.spacing()
        if ecart < 0:
            ecart = 0
        for item in self._items:
            taille = item.sizeHint()
            suivant = x + taille.width() + ecart
            if suivant - ecart > zone.right() and hauteur_ligne > 0:
                x = zone.x()                       # rangée suivante
                y = y + hauteur_ligne + ecart
                suivant = x + taille.width() + ecart
                hauteur_ligne = 0
            if not essai:
                item.setGeometry(QRect(QPoint(x, y), taille))
            x = suivant
            hauteur_ligne = max(hauteur_ligne, taille.height())
        return y + hauteur_ligne - rect.y() + marges.bottom()


def widget_reflowable(widgets, spacing=3):
    """Widget prêt à poser dans une disposition verticale, contenant `widgets`.

    Le `heightForWidth` d'une disposition n'est pris en compte par le parent que
    si la politique de taille du widget le déclare : sans cela, les rangées
    supplémentaires seraient calculées mais jamais affichées.
    """
    from qgis.PyQt.QtWidgets import QWidget

    conteneur = QWidget()
    flow = FlowLayout(conteneur, margin=0, spacing=spacing)
    for widget in widgets:
        flow.addWidget(widget)
    politique = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    politique.setHeightForWidth(True)
    conteneur.setSizePolicy(politique)
    return conteneur
