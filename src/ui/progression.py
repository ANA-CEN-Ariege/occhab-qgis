# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Progression annulable des traitements longs menés dans le fil de l'interface.

La synchronisation, l'export de la cartographie d'un JDD et la création d'un lot
de stations enchaînent des appels réseau sans rendre la main : QGIS paraissait
planté, parfois de longues minutes sur un réseau dégradé, sans rien pour dire où
l'on en était ni pour arrêter. Cette fenêtre le dit, et laisse arrêter.

Elle est modale à la fenêtre : pendant que les événements sont traités, on ne
peut ni relancer la synchronisation ni modifier une station en cours d'envoi.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication, QProgressDialog

#: En deçà, pas de fenêtre : un traitement court ne doit pas clignoter.
DELAI_AFFICHAGE_MS = 400


class Progression:
    """`with Progression(parent, "Synchronisation…", total) as p: p.avancer(i)`."""

    def __init__(self, parent, titre, total):
        self._total = max(int(total), 1)
        self._fenetre = QProgressDialog(titre, "Arrêter", 0, self._total, parent)
        self._fenetre.setWindowTitle("OccHab")
        self._fenetre.setWindowModality(Qt.WindowModality.WindowModal)
        self._fenetre.setMinimumDuration(DELAI_AFFICHAGE_MS)
        self._fenetre.setAutoClose(False)
        self._fenetre.setAutoReset(False)
        self._fenetre.setValue(0)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.fermer()
        return False

    def avancer(self, valeur, texte=None):
        """Poser l'avancement ; False si l'utilisateur a demandé l'arrêt."""
        if texte:
            self._fenetre.setLabelText(texte)
        self._fenetre.setValue(min(int(valeur), self._total))
        QApplication.processEvents()
        return not self._fenetre.wasCanceled()

    @property
    def arretee(self):
        return self._fenetre.wasCanceled()

    def fermer(self):
        self._fenetre.close()
        self._fenetre.deleteLater()
