# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Formulaire de saisie d'un habitat (aligné sur le formulaire GeoNature).

`cd_hab` (code HABREF) et `nom_cite` (texte cité) sont **deux champs distincts,
tous deux obligatoires** côté OccHab. Le champ « Nom cité » propose une
autocomplétion HABREF : choisir une proposition remplit le `cd_hab` ET propose le
libellé comme nom cité. Le nom cité reste ensuite librement modifiable sans
effacer le cd_hab ; le cd_hab est aussi saisissable à la main.
"""
from qgis.PyQt.QtCore import Qt, QModelIndex, QTimer
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QTextEdit,
    QWidget,
)

from ..processing.eval_fields import (
    ETATS_CONSERVATION,
    NIVEAUX_ENJEU,
    cover_class,
    decode_eval,
    encode_eval,
    fill_eval_combo,
    select_combo_data,
    strip_eval,
)

# Repli hors-ligne : id None (pas un faux id) → comblé par le défaut à la synchro.
PLACEHOLDER_TECHNIQUES = [(None, "— à renseigner en ligne —")]
_MIN_SEARCH = 3


class HabitatForm(QWidget):
    """Champs de l'habitat + niveau d'enjeu / état de conservation (extension ANA)."""

    def __init__(self, nomenclatures=None, habref_search=None, typologies=None,
                 user_names=None, default_determiner=None, defaults=None,
                 abundance_cover_map=None, parent=None):
        super().__init__(parent)
        self.nomenclatures = nomenclatures or {}
        # Technique obligatoire seulement si les nomenclatures ont pu être chargées
        # (connecté). Hors-ligne on autorise None → comblé par le défaut à la synchro.
        self._has_technique = bool(self.nomenclatures.get("technique"))
        self._defaults = defaults or {}  # id_nomenclature par défaut (instance)
        self._abundance_cover_map = abundance_cover_map or {}  # {classe(1-5): id_nomenclature}
        self._habref_search = habref_search
        self._typologies = typologies or []  # [(cd_typo, nom)]
        self._typo_names = {cd: name for cd, name in self._typologies}
        self._user_names = user_names or []  # noms proposés pour le déterminateur
        self._default_determiner = default_determiner  # utilisateur connecté par défaut
        self.combo_typo = None
        self._pending_query = ""
        self._build()

    def _build(self):
        form = QFormLayout(self)

        # --- Nom cité (obligatoire) + autocomplétion HABREF ---
        self.edit_nom_cite = QLineEdit()
        if self._habref_search is not None:
            # Filtre par typologie (Corine Biotopes, EUNIS…) pour cibler la recherche.
            self.combo_typo = QComboBox()
            self.combo_typo.addItem("Toutes les typologies", None)
            for cd_typo, name in self._typologies:
                self.combo_typo.addItem(name, cd_typo)
            form.addRow("Typologie", self.combo_typo)

            self.edit_nom_cite.setPlaceholderText("Tapez le nom (ou code) de l'habitat…")
            self._hab_model = QStandardItemModel(self)
            completer = QCompleter(self._hab_model, self)
            completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.activated[QModelIndex].connect(self._on_habitat_chosen)
            self.edit_nom_cite.setCompleter(completer)
            self.edit_nom_cite.textEdited.connect(self._on_nom_cite_edited)

            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.setInterval(300)
            self._search_timer.timeout.connect(self._run_habref_search)
        form.addRow("Nom cité *", self.edit_nom_cite)

        # --- Code habitat cd_hab (obligatoire), rempli par l'autocomplétion ---
        self.spin_cdhab = QSpinBox()
        self.spin_cdhab.setRange(0, 9_999_999)
        self.spin_cdhab.setSpecialValueText("—")  # 0 = non renseigné
        form.addRow("Code habitat (cd_hab / HABREF) *", self.spin_cdhab)

        self.combo_community = QComboBox()
        fill_eval_combo(self.combo_community, self.nomenclatures.get("community_interest", []))
        select_combo_data(self.combo_community, self._defaults.get("community_interest"))
        form.addRow("Habitat d'intérêt communautaire", self.combo_community)

        # Déterminateur : liste d'utilisateurs GeoNature MAIS saisie libre autorisée
        # (OccHab stocke ce champ en texte, pas en lien utilisateur).
        self.combo_determiner = QComboBox()
        self.combo_determiner.setEditable(True)
        self.combo_determiner.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_determiner.addItem("")
        self.combo_determiner.addItems(self._user_names)
        self.combo_determiner.setCurrentText(self._default_determiner or "")
        form.addRow("Déterminateur", self.combo_determiner)

        self.combo_determination = QComboBox()
        fill_eval_combo(self.combo_determination, self.nomenclatures.get("determination", []))
        select_combo_data(self.combo_determination, self._defaults.get("determination"))
        form.addRow("Type de détermination", self.combo_determination)

        self.combo_technique = QComboBox()
        for id_nom, label in (self.nomenclatures.get("technique") or PLACEHOLDER_TECHNIQUES):
            self.combo_technique.addItem(label, id_nom)
        select_combo_data(self.combo_technique, self._defaults.get("technique"))  # défaut « In situ »
        form.addRow("Technique de collecte *", self.combo_technique)

        self.text_precision = QTextEdit()
        self.text_precision.setPlaceholderText("Précision sur la technique de collecte…")
        self.text_precision.setMaximumHeight(60)
        form.addRow("Précision technique", self.text_precision)

        # Recouvrement (%) : encodé dans technical_precision ET pilote l'abondance.
        self.spin_recouvrement = QDoubleSpinBox()
        self.spin_recouvrement.setRange(0, 100)
        self.spin_recouvrement.setDecimals(1)
        self.spin_recouvrement.setSuffix(" %")
        self.spin_recouvrement.setSpecialValueText("—")  # 0 = non renseigné
        self.spin_recouvrement.valueChanged.connect(self._on_recouvrement_changed)
        form.addRow("Recouvrement", self.spin_recouvrement)

        self.combo_abundance = QComboBox()
        fill_eval_combo(self.combo_abundance, self.nomenclatures.get("abundance", []))
        select_combo_data(self.combo_abundance, self._defaults.get("abundance"))
        form.addRow("Abondance", self.combo_abundance)

        # Sensibilité : absente de certaines instances → menu créé seulement si dispo.
        self.combo_sensitivity = None
        if self.nomenclatures.get("sensitivity"):
            self.combo_sensitivity = QComboBox()
            fill_eval_combo(self.combo_sensitivity, self.nomenclatures["sensitivity"])
            select_combo_data(self.combo_sensitivity, self._defaults.get("sensitivity"))
            form.addRow("Sensibilité", self.combo_sensitivity)

        # Extension ANA : encodés dans technical_precision (voir README §6).
        self.combo_enjeu = QComboBox()
        fill_eval_combo(self.combo_enjeu, NIVEAUX_ENJEU)
        form.addRow("Niveau d'enjeu", self.combo_enjeu)

        self.combo_etat = QComboBox()
        fill_eval_combo(self.combo_etat, ETATS_CONSERVATION)
        form.addRow("État de conservation", self.combo_etat)

    # ------------------------------------------------ autocomplétion HABREF
    def _on_nom_cite_edited(self, text):
        # On (re)lance la recherche mais on ne touche PAS au cd_hab déjà renseigné.
        self._pending_query = text.strip()
        if len(self._pending_query) >= _MIN_SEARCH:
            self._search_timer.start()

    def _run_habref_search(self):
        query = self._pending_query
        if len(query) < _MIN_SEARCH or self._habref_search is None:
            return
        cd_typo = self.combo_typo.currentData() if self.combo_typo is not None else None
        try:
            results = self._habref_search(query, cd_typo=cd_typo) or []
        except Exception:  # noqa: BLE001 - la recherche ne doit pas casser la saisie
            results = []
        self._hab_model.clear()
        for item in results:
            # `search_name` contient déjà « code - nom » (ex. « 41.2 - Chênaies-charmaies »).
            name = item.get("search_name") or item.get("lb_code") or str(item.get("cd_hab"))
            typo = item.get("lb_nom_typo") or self._typo_names.get(item.get("cd_typo"), "")
            label = ("%s %s" % (typo, name)).strip()  # ex. « CORINE_biotopes 41.2 - Chênaies-charmaies »
            row = QStandardItem(label)
            row.setData(item, Qt.ItemDataRole.UserRole)
            self._hab_model.appendRow(row)
        if self._hab_model.rowCount():
            self.edit_nom_cite.completer().complete()

    def _on_habitat_chosen(self, index):
        data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        cd_hab = data.get("cd_hab")
        if cd_hab is not None:
            self.spin_cdhab.setValue(int(cd_hab))
        # Le completer va écrire le libellé affiché ; on force le nom cité au nom HABREF.
        name = data.get("search_name") or ""
        QTimer.singleShot(0, lambda: self.edit_nom_cite.setText(name))

    def _on_recouvrement_changed(self, value):
        """Un recouvrement > 0 pré-sélectionne la classe d'abondance correspondante."""
        cd = cover_class(value)
        if cd is None:
            return
        id_nom = self._abundance_cover_map.get(cd)
        if id_nom is not None:
            select_combo_data(self.combo_abundance, id_nom)

    # ------------------------------------------------------------- API
    def validate(self):
        if self.spin_cdhab.value() <= 0:
            return False, (
                "Le code habitat (cd_hab) est obligatoire : choisissez un habitat "
                "dans la liste, ou saisissez le code."
            )
        if not self.edit_nom_cite.text().strip():
            return False, "Le nom cité est obligatoire."
        if self._has_technique and self.combo_technique.currentData() is None:
            return False, "La technique de collecte est obligatoire."
        return True, ""

    def get_data(self):
        recouvrement = self.spin_recouvrement.value() or None
        technical_precision = encode_eval(
            self.text_precision.toPlainText(),
            enjeu=self.combo_enjeu.currentData(),
            etat_conservation=self.combo_etat.currentData(),
            recouvrement=recouvrement,
        )
        return {
            "cd_hab": self.spin_cdhab.value() or None,
            "nom_cite": self.edit_nom_cite.text().strip(),
            "determiner": self.combo_determiner.currentText().strip() or None,
            # Recouvrement écrit aussi dans le champ natif OccHab (pas seulement encodé).
            "recovery_percentage": recouvrement,
            "id_nomenclature_determination_type": self.combo_determination.currentData(),
            "id_nomenclature_collection_technique": self.combo_technique.currentData(),
            "id_nomenclature_abundance": self.combo_abundance.currentData(),
            "id_nomenclature_sensitivity": (
                self.combo_sensitivity.currentData() if self.combo_sensitivity else None
            ),
            "id_nomenclature_community_interest": self.combo_community.currentData(),
            "technical_precision": technical_precision or None,
        }

    def set_data(self, habitat):
        self.edit_nom_cite.setText(habitat.get("nom_cite") or "")
        if habitat.get("cd_hab"):
            self.spin_cdhab.setValue(int(habitat["cd_hab"]))
        self.combo_determiner.setCurrentText(habitat.get("determiner") or "")
        select_combo_data(
            self.combo_determination, habitat.get("id_nomenclature_determination_type")
        )
        select_combo_data(
            self.combo_technique, habitat.get("id_nomenclature_collection_technique")
        )
        select_combo_data(self.combo_abundance, habitat.get("id_nomenclature_abundance"))
        if self.combo_sensitivity:
            select_combo_data(
                self.combo_sensitivity, habitat.get("id_nomenclature_sensitivity")
            )
        select_combo_data(
            self.combo_community, habitat.get("id_nomenclature_community_interest")
        )
        precision = habitat.get("technical_precision") or ""
        self.text_precision.setPlainText(strip_eval(precision))
        codes = decode_eval(precision)
        select_combo_data(self.combo_enjeu, codes.get("enjeu"))
        select_combo_data(self.combo_etat, codes.get("etat_conservation"))
        # Recouvrement : bloc encodé prioritaire, sinon champ natif recovery_percentage.
        rec = codes.get("recouvrement") or habitat.get("recovery_percentage")
        if rec:
            # afficher le recouvrement sans réécraser l'abondance déjà enregistrée
            try:
                self.spin_recouvrement.blockSignals(True)
                self.spin_recouvrement.setValue(float(rec))
            finally:
                self.spin_recouvrement.blockSignals(False)
