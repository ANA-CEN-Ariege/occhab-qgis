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
from qgis.PyQt.QtCore import QDate, Qt
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
    QWidget,
)

from .dialog_size import (ajuster_a_l_ecran, borner_largeur_combos,
                          rendre_defilant)
from .export_layers import MODE_DEFAUT, MODES
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

    def __init__(self, exports, datasets=None, id_dataset=None,
                 en_attente=None, parent=None):
        """Args : `exports` [{id, label, …}], `datasets` [(id, nom)], JDD courant.

        Le jeu de données n'est PAS à choisir ici : c'est celui du panneau, où
        l'on travaille déjà. Le redemander posait une question dont la bonne
        réponse était toujours la même, avec le risque de charger un export qui
        ne parle pas des mêmes stations que la saisie en cours. Reste une case à
        cocher pour le cas rare où l'on veut voir tous les JDD.

        `en_attente` : callable(id_dataset) rendant le nombre de stations locales
        pas encore synchronisées. Elles ne sont PAS dans l'export — celui-ci est
        une vue du serveur — et c'est le piège de la cartographie : on compose
        une planche en croyant y voir tout son travail, alors que les saisies du
        jour manquent.
        """
        super().__init__(parent)
        self.setWindowTitle("Charger un export du serveur")
        self._exports = exports or []

        layout = QVBoxLayout(self)
        # Tout le contenu défile, boutons exceptés : cette fenêtre s'est
        # enrichie au fil des besoins — avertissement de synchronisation, choix
        # du figuré des mosaïques, aide en clair — et une taille écrite une fois
        # pour toutes vieillit mal : les champs se compriment jusqu'à se couper,
        # sans que rien ne le signale.
        corps = QWidget()
        layout_corps = QVBoxLayout(corps)
        layout_corps.setContentsMargins(0, 0, 0, 0)
        intro = QLabel(
            "Chargement de l'export bâti sur la vue « %s » : données "
            "consolidées, identifiants déjà résolus en libellés, équivalents "
            "CORINE et EUNIS. Le résultat arrive en couche QGIS, en lecture "
            "seule." % VUE_EXPORT
        )
        intro.setWordWrap(True)
        layout_corps.addWidget(intro)

        self._compter_en_attente = en_attente
        self.label_attente = QLabel()
        self.label_attente.setWordWrap(True)
        self.label_attente.setStyleSheet(
            "background: #fbeedb; border: 1px solid #f0d6ac; "
            "color: #8a4d02; padding: 6px;"
        )
        layout_corps.addWidget(self.label_attente)

        form = QFormLayout()

        self.combo_export = QComboBox()
        for export in self._exports:
            libelle = export.get("label") or "export %s" % export.get("id")
            self.combo_export.addItem(libelle, export.get("id"))
        # Un seul export sur cette vue : le montrer, mais ne pas faire mine de
        # proposer un choix qui n'existe pas.
        self.combo_export.setEnabled(len(self._exports) > 1)
        form.addRow("Export", self.combo_export)

        self._id_dataset = id_dataset
        self._nom_dataset = dict(datasets or {}).get(id_dataset) if datasets else None
        if self._nom_dataset is None:
            self._nom_dataset = next(
                (nom for id_ds, nom in datasets or [] if id_ds == id_dataset), None
            )
        etiquette = QLabel(self._nom_dataset or "— aucun jeu de données choisi —")
        etiquette.setWordWrap(True)
        etiquette.setToolTip(
            "Celui du panneau OccHab. Pour en changer, changez-le là-bas : "
            "l'export doit parler des mêmes stations que votre saisie."
        )
        form.addRow("Jeu de données", etiquette)

        debut, fin = periode_annee_en_cours()
        self.check_periode = QCheckBox("Restreindre à une période")
        self.check_periode.setChecked(True)
        self.check_periode.setToolTip(
            "Décochez pour rapatrier tout l'export, sans filtre de date."
        )
        form.addRow("", self.check_periode)

        # Représentation des mosaïques : aucune convention nationale ne tranche,
        # donc on la choisit au chargement et on compare sur les mêmes données.
        self.combo_mode = QComboBox()
        for cle, libelle, description in MODES:
            self.combo_mode.addItem(libelle, cle)
            self.combo_mode.setItemData(
                self.combo_mode.count() - 1, description, Qt.ItemDataRole.ToolTipRole
            )
        position = self.combo_mode.findData(MODE_DEFAUT)
        if position >= 0:
            self.combo_mode.setCurrentIndex(position)
        self.combo_mode.currentIndexChanged.connect(self._maj_aide_mode)
        form.addRow("Mosaïques", self.combo_mode)

        self._maj_avertissement()

        self.label_mode = QLabel()
        self.label_mode.setWordWrap(True)
        self.label_mode.setStyleSheet("color: palette(mid); font-style: italic;")
        form.addRow("", self.label_mode)
        self._maj_aide_mode()

        self.date_debut = _date_edit(debut)
        self.date_fin = _date_edit(fin)
        form.addRow("Du", self.date_debut)
        form.addRow("Au", self.date_fin)
        self.check_periode.toggled.connect(self.date_debut.setEnabled)
        self.check_periode.toggled.connect(self.date_fin.setEnabled)

        layout_corps.addLayout(form)

        precision = QLabel(
            "La période retient les stations dont les dates de début ET de fin "
            "tombent dans l'intervalle. Par défaut : l'année en cours."
        )
        precision.setWordWrap(True)
        precision.setStyleSheet("color: palette(mid); font-style: italic;")
        layout_corps.addWidget(precision)

        layout.addWidget(rendre_defilant(corps), 1)
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
        ajuster_a_l_ecran(self, 500, 560)

    # ------------------------------------------------------------------ API
    def id_export(self):
        return self.combo_export.currentData()

    def libelle_export(self):
        return self.combo_export.currentText()

    def id_dataset(self):
        """JDD retenu : celui du panneau, toujours.

        Il n'y a pas de choix ici, et pas non plus d'échappatoire « tous les
        jeux de données » : une couche qui mélange le JDD courant et ceux des
        collègues ne se cartographie pas — la légende, les recouvrements et le
        compte des stations en attente parleraient de trois choses à la fois.
        """
        return self._id_dataset

    def mode(self):
        """Représentation retenue pour les stations à plusieurs habitats."""
        return self.combo_mode.currentData() or MODE_DEFAUT

    def libelle_mode(self):
        return self.combo_mode.currentText()

    def _maj_avertissement(self):
        """Compter les saisies en attente DANS LA PORTÉE choisie.

        Un compte tous JDD confondus serait du bruit : les stations d'un autre
        jeu de données n'ont rien à faire dans cet export, et leur absence n'est
        pas un oubli.
        """
        if not callable(self._compter_en_attente):
            self.label_attente.setVisible(False)
            return
        try:
            nombre = int(self._compter_en_attente(self.id_dataset()) or 0)
        except Exception:  # noqa: BLE001 - un compteur ne doit rien bloquer
            nombre = 0
        self.label_attente.setVisible(bool(nombre))
        if not nombre:
            return
        self.label_attente.setText(
            "⚠ <b>%d station(s) locale(s) dans « %s » ne sont pas encore "
            "synchronisées</b> : elles ne figureront pas dans cet export, donc "
            "pas sur les cartes que vous en tirerez. Synchronisez d'abord si "
            "vous voulez les voir."
            % (nombre, self._nom_dataset or "ce jeu de données")
        )

    def _maj_aide_mode(self):
        """Décrire le mode choisi : les libellés seuls ne disent pas ce qu'on voit."""
        cle = self.combo_mode.currentData()
        for candidat, _libelle, description in MODES:
            if candidat == cle:
                self.label_mode.setText(description)
                return
        self.label_mode.setText("")

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
