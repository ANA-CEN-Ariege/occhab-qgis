# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Choix d'un gabarit de mise en page et de ce qu'il faut y mettre.

Rien n'est inventé ici : les gabarits `.qpt` de l'ANA portent déjà le bandeau,
le logo, l'adresse et les mentions. Ce dialogue demande seulement ce qu'ils ne
peuvent pas deviner — quelle carte, quel titre, quel fond de plan citer.
"""
import os

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..processing import gabarits as gb
from .dialog_size import (ajuster_a_l_ecran, borner_largeur_combos,
                          rendre_defilant)
from .no_wheel import proteger_du_defilement

#: Clé de configuration du dossier de gabarits. Retenue d'une fois sur l'autre :
#: il vit sur un partage réseau, dont le chemin n'a pas à être ressaisi.
CLE_DOSSIER = "mise_en_page.dossier_gabarits"
#: Cadrage de la carte.
VUE_COURANTE = "vue"
TOUTE_LA_COUCHE = "couche"
EMPRISES = [
    (VUE_COURANTE, "Ce que montre la carte à l'écran"),
    (TOUTE_LA_COUCHE, "Toute la couche d'habitats"),
]


def dossiers_gabarits(dossier_retenu=None):
    """Où chercher les `.qpt`, du plus spécifique au plus général.

    Le dossier retenu par l'utilisateur passe devant : c'est le partage de la
    structure, où vivent les gabarits à jour. Les dossiers de QGIS suivent, pour
    qu'une installation neuve propose quand même quelque chose.
    """
    dossiers = [dossier_retenu] if dossier_retenu else []
    try:
        from qgis.core import QgsApplication

        dossiers.append(os.path.join(QgsApplication.qgisSettingsDirPath(),
                                     "composer_templates"))
        dossiers.append(os.path.join(QgsApplication.pkgDataPath(),
                                     "composer_templates"))
    except Exception:  # noqa: BLE001 - hors QGIS (tests) : les chemins suffisent
        pass
    return [d for d in dossiers if d]


class LayoutPicker(QDialog):
    """Quel gabarit, quel titre, quelle couche — puis `parametres()`."""

    def __init__(self, couches, dossier=None, titre_propose="",
                 sous_titre_propose="", parent=None):
        """Args : `couches` [(nom, QgsVectorLayer)], dossier de gabarits retenu."""
        super().__init__(parent)
        self.setWindowTitle("Créer une mise en page")
        self._dossier = dossier
        self._couches = list(couches or [])

        layout = QVBoxLayout(self)
        corps = QWidget()
        layout_corps = QVBoxLayout(corps)
        layout_corps.setContentsMargins(0, 0, 0, 0)
        intro = QLabel(
            "La planche reprend un gabarit de l'ANA : bandeau, logo, adresse et "
            "mentions y sont déjà. Elle s'ouvre ensuite dans QGIS, entièrement "
            "modifiable."
        )
        intro.setWordWrap(True)
        layout_corps.addWidget(intro)

        form = QFormLayout()

        self.combo_gabarit = QComboBox()
        bouton_parcourir = QPushButton("Dossier…")
        bouton_parcourir.setToolTip(
            "Choisir le dossier où sont rangés vos gabarits (.qpt)."
        )
        bouton_parcourir.clicked.connect(self._choisir_dossier)
        ligne = QHBoxLayout()
        ligne.addWidget(self.combo_gabarit, 1)
        ligne.addWidget(bouton_parcourir)
        form.addRow("Gabarit", ligne)
        self._remplir_gabarits()

        self.edit_titre = QLineEdit(titre_propose)
        self.edit_titre.setToolTip(
            "S'affiche dans le bandeau vert, et nomme la mise en page dans QGIS.\n"
            "Restez court : le bandeau est d'une hauteur fixe, un titre long "
            "passe à la ligne et le déborde."
        )
        form.addRow("Titre", self.edit_titre)

        self.edit_sous_titre = QLineEdit(sous_titre_propose)
        self.edit_sous_titre.setPlaceholderText("Jeu de données, année, projet…")
        form.addRow("Sous-titre", self.edit_sous_titre)

        self.combo_couche = QComboBox()
        for nom, couche in self._couches:
            self.combo_couche.addItem(nom, couche)
        if not self._couches:
            self.combo_couche.addItem("— aucune couche d'habitats chargée —", None)
            self.combo_couche.setEnabled(False)
        form.addRow("Couche à cartographier", self.combo_couche)

        self.combo_emprise = QComboBox()
        for cle, libelle in EMPRISES:
            self.combo_emprise.addItem(libelle, cle)
        form.addRow("Cadrage", self.combo_emprise)

        self.combo_fond = QComboBox()
        for cle, libelle in gb.FONDS:
            self.combo_fond.addItem(libelle, cle)
        self.combo_fond.setToolTip(
            "Le gabarit cite ce fond dans ses sources. Laissez vide si vous "
            "n'affichez aucun fond de plan : une source fausse est pire "
            "qu'une source absente."
        )
        form.addRow("Fond de plan cité", self.combo_fond)

        layout_corps.addLayout(form)

        self.label_aide = QLabel()
        self.label_aide.setWordWrap(True)
        self.label_aide.setStyleSheet("color: palette(mid); font-style: italic;")
        layout_corps.addWidget(self.label_aide)
        layout.addWidget(rendre_defilant(corps), 1)
        self._maj_aide()
        self.combo_gabarit.currentIndexChanged.connect(self._maj_aide)

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText("Créer")
        boutons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        boutons.accepted.connect(self._on_ok)
        boutons.rejected.connect(self.reject)
        layout.addWidget(boutons)

        self._filtre_molette = proteger_du_defilement(self)
        borner_largeur_combos(self)

    def showEvent(self, event):
        super().showEvent(event)
        ajuster_a_l_ecran(self, 560, 460)

    # ------------------------------------------------------------------ API
    def parametres(self):
        """Tout ce qu'attend `print_layout.creer`, en un dict."""
        return {
            "chemin_gabarit": self.combo_gabarit.currentData(),
            "titre": self.edit_titre.text().strip(),
            "sous_titre": self.edit_sous_titre.text().strip(),
            "couche": self.combo_couche.currentData(),
            "fond": self.combo_fond.currentData() or "",
            "emprise_vue": self.combo_emprise.currentData() == VUE_COURANTE,
        }

    def dossier(self):
        return self._dossier

    def validate(self):
        if not self.combo_gabarit.currentData():
            return False, ("Aucun gabarit trouvé. Cliquez « Dossier… » et "
                           "désignez celui qui contient vos fichiers .qpt.")
        if not self.edit_titre.text().strip():
            return False, "Donnez un titre : c'est lui qui s'affiche en bandeau."
        return True, ""

    # -------------------------------------------------------------- interne
    def _remplir_gabarits(self):
        self.combo_gabarit.clear()
        trouves = gb.trouver(dossiers_gabarits(self._dossier))
        for chemin in trouves:
            self.combo_gabarit.addItem(gb.libelle(chemin), chemin)
        if not trouves:
            self.combo_gabarit.addItem("— aucun gabarit trouvé —", None)

    def _choisir_dossier(self):
        dossier = QFileDialog.getExistingDirectory(
            self, "Dossier des gabarits de mise en page", self._dossier or ""
        )
        if not dossier:
            return
        self._dossier = dossier
        self._remplir_gabarits()
        self._maj_aide()

    def _maj_aide(self):
        chemin = self.combo_gabarit.currentData()
        if not chemin:
            self.label_aide.setText(
                "Les gabarits sont des fichiers .qpt. Ceux de l'ANA se trouvent "
                "dans le dossier partagé « composer_templates »."
            )
            return
        self.label_aide.setText(os.path.dirname(chemin))

    def _on_ok(self):
        ok, message = self.validate()
        if not ok:
            QMessageBox.warning(self, "Créer une mise en page", message)
            return
        self.accept()
