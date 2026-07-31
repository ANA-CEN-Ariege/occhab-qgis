# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Formulaire de saisie d'un habitat (aligné sur le formulaire GeoNature).

`cd_hab` (code HABREF) et `nom_cite` (texte cité) sont **deux champs distincts,
tous deux obligatoires** côté OccHab. Le champ « Nom cité » propose une
autocomplétion HABREF : choisir une proposition remplit le `cd_hab` ET propose le
libellé comme nom cité. Le nom cité reste ensuite librement modifiable sans
effacer le cd_hab ; le cd_hab est aussi saisissable à la main.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QTextEdit,
    QToolButton,
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
from ..processing.referentiels import DYNAMIQUES, RESTAURATIONS, TYPICITES
from .habref_widget import HabrefSearchEdit

_SEPARATEUR_PEE = " ; "

# Repli hors-ligne : id None (pas un faux id) → comblé par le défaut à la synchro.
PLACEHOLDER_TECHNIQUES = [(None, "— à renseigner en ligne —")]


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
        self._user_names = user_names or []  # noms proposés pour le déterminateur
        self._default_determiner = default_determiner  # utilisateur connecté par défaut
        self._build()

    def _build(self):
        form = QFormLayout(self)

        # --- Nom cité (obligatoire) + autocomplétion HABREF ---
        # Composant partagé avec l'édition en masse : le choix d'un habitat doit
        # se faire de la même façon aux deux endroits (cf. `habref_widget`).
        self.habref = HabrefSearchEdit(
            habref_search=self._habref_search, typologies=self._typologies
        )
        self.habref.habitat_choisi.connect(self._on_habitat_chosen)
        self.edit_nom_cite = self.habref.edit  # compatibilité des appelants
        self.combo_typo = self.habref.combo_typo
        form.addRow(self.habref)

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

        # ============ Natura 2000 (replié par défaut) ============
        # Six champs de plus sur chaque habitat : hors cartographie N2000 ils
        # alourdiraient la saisie courante pour rien, d'où le repli.
        self.btn_n2000 = QToolButton()
        self.btn_n2000.setAutoRaise(True)
        self.btn_n2000.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_n2000.setStyleSheet("QToolButton { border: none; font-weight: 600; }")
        self.btn_n2000.clicked.connect(self._toggle_n2000)
        form.addRow(self.btn_n2000)

        self.n2000 = QWidget()
        n2000_form = QFormLayout(self.n2000)
        n2000_form.setContentsMargins(12, 0, 0, 0)

        self.combo_typicite = QComboBox()
        fill_eval_combo(self.combo_typicite, TYPICITES)
        n2000_form.addRow("Typicité", self.combo_typicite)

        self.combo_dynamique = QComboBox()
        fill_eval_combo(self.combo_dynamique, DYNAMIQUES)
        n2000_form.addRow("Dynamique", self.combo_dynamique)

        self.combo_restauration = QComboBox()
        fill_eval_combo(self.combo_restauration, RESTAURATIONS)
        n2000_form.addRow("Restauration", self.combo_restauration)

        self.text_critere = QTextEdit()
        self.text_critere.setPlaceholderText(
            "Critère ayant servi à évaluer l'état de conservation…"
        )
        self.text_critere.setMaximumHeight(55)
        n2000_form.addRow("Critère d'évaluation", self.text_critere)

        self.edit_pee = QLineEdit()
        self.edit_pee.setPlaceholderText("Taxon 1 ; Taxon 2 ; Taxon 3")
        self.edit_pee.setToolTip(
            "Plantes exotiques envahissantes : 3 taxons au plus, séparés par « ; »."
        )
        n2000_form.addRow("PEE", self.edit_pee)

        self.text_remarque = QTextEdit()
        self.text_remarque.setPlaceholderText("Remarque sur l'habitat…")
        self.text_remarque.setMaximumHeight(55)
        n2000_form.addRow("Remarque", self.text_remarque)

        form.addRow(self.n2000)
        self._set_n2000_visible(False)

    def _set_n2000_visible(self, visible):
        self.n2000.setVisible(visible)
        self.btn_n2000.setText(
            ("▾ " if visible else "▸ ")
            + "Natura 2000 (typicité, dynamique, restauration, PEE…)"
        )

    def _toggle_n2000(self):
        self._set_n2000_visible(not self.n2000.isVisible())

    # ------------------------------------------------ autocomplétion HABREF
    def _on_habitat_chosen(self, cd_hab, nom):
        """Une proposition HABREF retenue renseigne le code ET le nom cité."""
        self.spin_cdhab.setValue(int(cd_hab))

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
            typicite=self.combo_typicite.currentData(),
            dynamique=self.combo_dynamique.currentData(),
            restauration=self.combo_restauration.currentData(),
            critere=self.text_critere.toPlainText(),
            pee=[p.strip() for p in self.edit_pee.text().split(";") if p.strip()],
            remarque=self.text_remarque.toPlainText(),
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
        # `decode_eval` rend des valeurs déjà normalisées (codes hérités convertis).
        select_combo_data(self.combo_enjeu, codes.get("enjeu"))
        select_combo_data(self.combo_etat, codes.get("etat_conservation"))
        select_combo_data(self.combo_typicite, codes.get("typicite"))
        select_combo_data(self.combo_dynamique, codes.get("dynamique"))
        select_combo_data(self.combo_restauration, codes.get("restauration"))
        self.text_critere.setPlainText(codes.get("critere") or "")
        self.edit_pee.setText(_SEPARATEUR_PEE.join(codes.get("pee") or []))
        self.text_remarque.setPlainText(codes.get("remarque") or "")
        # Déplier la section si l'habitat porte déjà des champs N2000 : ne jamais
        # cacher une valeur saisie.
        if any(codes.get(cle) for cle in ("typicite", "dynamique", "restauration",
                                          "critere", "pee", "remarque")):
            self._set_n2000_visible(True)
        # Recouvrement : bloc encodé prioritaire, sinon champ natif recovery_percentage.
        rec = codes.get("recouvrement") or habitat.get("recovery_percentage")
        if rec:
            # afficher le recouvrement sans réécraser l'abondance déjà enregistrée
            try:
                self.spin_recouvrement.blockSignals(True)
                self.spin_recouvrement.setValue(float(rec))
            finally:
                self.spin_recouvrement.blockSignals(False)
