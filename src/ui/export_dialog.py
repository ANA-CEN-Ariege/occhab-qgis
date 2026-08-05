# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Choix d'un export serveur à charger : lequel, quel JDD, quelle période.

Le module Exports de GeoNature publie des vues à plat (cf. README §6). Sa route
`GET /exports/api/<id>` filtre **sur les colonnes de la vue** : on compose donc
ici des filtres nommés d'après elles (`id_dataset`, `date_min`, `date_max`), et
non d'après le modèle OccHab.

Un filtre portant sur une colonne absente de la vue est **ignoré en silence** par
GeoNature. Le dialogue le dit plutôt que de laisser croire à un filtrage qui
n'aurait pas lieu, et l'appelant compare ensuite `total` et `total_filtered`.
"""
from qgis.PyQt.QtCore import QDate
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from .dialog_size import ajuster_a_l_ecran, borner_largeur_combos
from .no_wheel import proteger_du_defilement

#: Colonnes attendues dans la vue exportée pour que les filtres s'appliquent.
#: Ce sont celles de `v_occhab_complet` (README §6).
COLONNE_JDD = "id_dataset"
COLONNE_DATE_DEBUT = "date_min"
COLONNE_DATE_FIN = "date_max"
#: Seule vue exploitée. Une instance GeoNature publie souvent des exports sans
#: rapport avec OccHab (synthèse, taxons, métadonnées…) : les proposer ici
#: reviendrait à promettre des filtres « JDD » et « période » qui ne
#: s'appliqueraient pas, et une couche dont on ne saurait rien.
VUE_EXPORT = "v_occhab_complet"


def exports_occhab(exports, vue=VUE_EXPORT):
    """Ne garder que les exports bâtis sur la vue OccHab.

    Le module Exports sérialise tout le modèle : `view_name` est donc présent.
    Repli sur le libellé si une version plus ancienne ne l'exposait pas — mieux
    vaut une correspondance approximative qu'une liste vide.
    """
    retenus = [e for e in exports or [] if (e or {}).get("view_name") == vue]
    if retenus:
        return retenus
    return [
        e for e in exports or []
        if not (e or {}).get("view_name") and vue in (e or {}).get("label", "")
    ]


def periode_annee_en_cours(aujourdhui=None):
    """(1er janvier, 31 décembre) de l'année en cours."""
    jour = aujourdhui or QDate.currentDate()
    return QDate(jour.year(), 1, 1), QDate(jour.year(), 12, 31)


class ExportPicker(QDialog):
    """Quel export, quel JDD, quelle période — puis `filtres()`."""

    def __init__(self, exports, datasets=None, id_dataset=None, parent=None):
        """Args : `exports` [{id, label, …}], `datasets` [(id, nom)], JDD courant."""
        super().__init__(parent)
        self.setWindowTitle("Charger un export du serveur")
        self._exports = exports or []

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Chargement de l'export bâti sur la vue « %s » : données "
            "consolidées, identifiants déjà résolus en libellés, équivalents "
            "CORINE et EUNIS. Le résultat arrive en couche QGIS, en lecture "
            "seule." % VUE_EXPORT
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()

        self.combo_export = QComboBox()
        for export in self._exports:
            libelle = export.get("label") or "export %s" % export.get("id")
            self.combo_export.addItem(libelle, export.get("id"))
        # Un seul export sur cette vue : le montrer, mais ne pas faire mine de
        # proposer un choix qui n'existe pas.
        self.combo_export.setEnabled(len(self._exports) > 1)
        form.addRow("Export", self.combo_export)

        self.combo_jdd = QComboBox()
        self.combo_jdd.addItem("— tous les jeux de données —", None)
        for id_ds, nom in datasets or []:
            self.combo_jdd.addItem(nom, id_ds)
        position = self.combo_jdd.findData(id_dataset)
        if position >= 0:
            self.combo_jdd.setCurrentIndex(position)
        form.addRow("Jeu de données", self.combo_jdd)

        debut, fin = periode_annee_en_cours()
        self.check_periode = QCheckBox("Restreindre à une période")
        self.check_periode.setChecked(True)
        self.check_periode.setToolTip(
            "Décochez pour rapatrier tout l'export, sans filtre de date."
        )
        form.addRow("", self.check_periode)

        self.date_debut = _date_edit(debut)
        self.date_fin = _date_edit(fin)
        form.addRow("Du", self.date_debut)
        form.addRow("Au", self.date_fin)
        self.check_periode.toggled.connect(self.date_debut.setEnabled)
        self.check_periode.toggled.connect(self.date_fin.setEnabled)

        layout.addLayout(form)

        precision = QLabel(
            "La période retient les stations dont les dates de début ET de fin "
            "tombent dans l'intervalle. Par défaut : l'année en cours."
        )
        precision.setWordWrap(True)
        precision.setStyleSheet("color: palette(mid); font-style: italic;")
        layout.addWidget(precision)

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText("Charger")
        boutons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        boutons.accepted.connect(self._on_ok)
        boutons.rejected.connect(self.reject)
        layout.addWidget(boutons)

        # Mêmes garde-fous qu'ailleurs : la molette ne modifie pas une valeur, et
        # une liste déroulante n'impose pas sa largeur au dialogue.
        self._filtre_molette = proteger_du_defilement(self)
        borner_largeur_combos(self)

    def showEvent(self, event):
        super().showEvent(event)
        ajuster_a_l_ecran(self, 480, 320)

    # ------------------------------------------------------------------ API
    def id_export(self):
        return self.combo_export.currentData()

    def libelle_export(self):
        return self.combo_export.currentText()

    def id_dataset(self):
        return self.combo_jdd.currentData()

    def filtres(self):
        """Paramètres de requête pour `GET /exports/api/<id>`.

        `filter_d_up_<col>` = « à partir de », `filter_d_lo_<col>` = « jusqu'à » :
        conventions de la route, pas les nôtres.
        """
        filtres = {}
        id_dataset = self.id_dataset()
        if id_dataset is not None:
            filtres[COLONNE_JDD] = id_dataset
        if self.check_periode.isChecked():
            filtres["filter_d_up_%s" % COLONNE_DATE_DEBUT] = (
                self.date_debut.date().toString("yyyy-MM-dd")
            )
            filtres["filter_d_lo_%s" % COLONNE_DATE_FIN] = (
                self.date_fin.date().toString("yyyy-MM-dd")
            )
        return filtres

    def validate(self):
        if self.id_export() is None:
            return False, "Choisissez un export."
        if (self.check_periode.isChecked()
                and self.date_debut.date() > self.date_fin.date()):
            return False, "La date de début doit précéder la date de fin."
        return True, ""

    def _on_ok(self):
        ok, message = self.validate()
        if not ok:
            QMessageBox.warning(self, "Charger un export", message)
            return
        self.accept()


def _date_edit(date):
    widget = QDateEdit(date)
    widget.setCalendarPopup(True)
    widget.setDisplayFormat("yyyy-MM-dd")
    return widget
