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
    QLabel,
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
from ..processing.correspondances import candidats_habref, catalogue
from ..processing.referentiels import (
    DYNAMIQUES,
    RESTAURATIONS,
    TYPICITES,
    TYPOLOGIES_CORRESPONDANCE,
)
from .correspondance_widget import CorrespondancesEdit
from .habref_widget import HabrefSearchEdit
from .dialog_size import borner_largeur_combos
from .no_wheel import proteger_du_defilement

_SEPARATEUR_PEE = " ; "

# Repli hors-ligne : id None (pas un faux id) → comblé par le défaut à la synchro.
PLACEHOLDER_TECHNIQUES = [(None, "— à renseigner en ligne —")]


class HabitatForm(QWidget):
    """Champs de l'habitat + niveau d'enjeu / état de conservation (extension ANA)."""

    def __init__(self, nomenclatures=None, habref_search=None, habref_detail=None,
                 typologies=None,
                 user_names=None, default_determiner=None, defaults=None,
                 abundance_cover_map=None, cd_typo=None, last_habitat=None,
                 parent=None):
        super().__init__(parent)
        # Habitat de la saisie précédente, sans son identité ni son recouvrement
        # (cf. `processing.duplicate.habitat_reprise`) : pré-remplit un NOUVEL
        # habitat. En édition, les valeurs de l'habitat l'emportent (`set_data`).
        self._last_habitat = last_habitat or None
        # Typologie de la dernière saisie : sur une campagne, on reste dans la
        # même (CORINE, EUNIS…). La retrouver à chaque habitat était fastidieux.
        self._cd_typo = cd_typo
        self.nomenclatures = nomenclatures or {}
        # Technique obligatoire seulement si les nomenclatures ont pu être chargées
        # (connecté). Hors-ligne on autorise None → comblé par le défaut à la synchro.
        self._has_technique = bool(self.nomenclatures.get("technique"))
        self._defaults = defaults or {}  # id_nomenclature par défaut (instance)
        self._abundance_cover_map = abundance_cover_map or {}  # {classe(1-5): id_nomenclature}
        self._habref_search = habref_search
        # Fiche HABREF complète d'un cd_hab : elle porte les correspondances que
        # HABREF connaît, avec leurs libellés. Sans elle, une détermination hors
        # catalogue n'aurait aucune proposition de code CORINE ou EUNIS.
        self._habref_detail = habref_detail
        self._fiches = {}  # cd_hab -> candidats, pour ne pas réinterroger
        self._typologies = typologies or []  # [(cd_typo, nom)]
        self._user_names = user_names or []  # noms proposés pour le déterminateur
        self._default_determiner = default_determiner  # utilisateur connecté par défaut
        # Détermination hors HABREF : relue dans `set_data`, réécrite par
        # `get_data`. `encode_eval` remplace le bloc ENTIER — sans ce report,
        # rouvrir puis enregistrer un habitat effacerait ce que le formulaire
        # n'affiche pas. Les correspondances, elles, ont leur propre composant :
        # c'est lui qui fait foi, et non une copie tenue à côté.
        self._determination = None
        self._build()

    def _build(self):
        form = QFormLayout(self)

        # Ce qui est repris de la saisie précédente doit se voir : un type de
        # détermination ou un état de conservation hérité en silence serait une
        # erreur de donnée invisible (cf. la même mention côté station).
        self.label_repris = QLabel(
            "↺ Champs repris de la saisie précédente (hors nom cité, code, "
            "recouvrement et abondance) — vérifiez-les."
        )
        self.label_repris.setWordWrap(True)
        self.label_repris.setStyleSheet("color: palette(mid); font-style: italic;")
        self.label_repris.setVisible(False)
        form.addRow(self.label_repris)

        # --- Nom cité (obligatoire) + autocomplétion HABREF ---
        # Composant partagé avec l'édition en masse : le choix d'un habitat doit
        # se faire de la même façon aux deux endroits (cf. `habref_widget`).
        self.habref = HabrefSearchEdit(
            habref_search=self._habref_search, typologies=self._typologies,
            cd_typo=self._cd_typo,
        )
        self.habref.habitat_choisi.connect(self._on_habitat_chosen)
        self.habref.alliance_choisie.connect(self._on_alliance_choisie)
        self.edit_nom_cite = self.habref.edit  # compatibilité des appelants
        self.combo_typo = self.habref.combo_typo
        form.addRow(self.habref)

        # Ce que le catalogue apporte doit se lire, pas se deviner : un code
        # emprunté et des correspondances reprises sont des affirmations sur
        # l'habitat, pas des commodités de saisie.
        self.label_catalogue = QLabel()
        self.label_catalogue.setWordWrap(True)
        self.label_catalogue.setStyleSheet("color: palette(mid); font-style: italic;")
        self.label_catalogue.setVisible(False)
        form.addRow("", self.label_catalogue)

        # --- Correspondances de CET habitat, modifiables ---
        # Repliées par défaut : la plupart des saisies reprennent ce que propose
        # le catalogue sans avoir à y toucher. La section s'ouvre d'elle-même dès
        # qu'une correspondance est renseignée — on ne cache jamais une valeur.
        self.btn_corresp = QToolButton()
        self.btn_corresp.setAutoRaise(True)
        self.btn_corresp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_corresp.setStyleSheet("QToolButton { border: none; font-weight: 600; }")
        self.btn_corresp.clicked.connect(self._toggle_corresp)
        form.addRow(self.btn_corresp)

        self.corresp_edit = CorrespondancesEdit(
            habref_search=self._habref_search, typologies=self._typologies,
        )
        self.corresp_edit.modifiee.connect(self._afficher_catalogue)
        form.addRow(self.corresp_edit)
        self._set_corresp_visible(False)

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
        self.spin_recouvrement.setToolTip(
            "Renseigner le recouvrement pré-sélectionne la classe d'abondance "
            "correspondante (repliée en bas du formulaire)."
        )
        form.addRow("Recouvrement", self.spin_recouvrement)

        # Extension ANA : encodés dans technical_precision (voir README §6).
        self.combo_enjeu = QComboBox()
        fill_eval_combo(self.combo_enjeu, NIVEAUX_ENJEU)
        form.addRow("Niveau d'enjeu", self.combo_enjeu)

        self.combo_etat = QComboBox()
        fill_eval_combo(self.combo_etat, ETATS_CONSERVATION)
        form.addRow("État de conservation", self.combo_etat)

        # Critère d'évaluation et PEE : ils justifient l'état de conservation
        # qu'on vient de choisir. Ils sont donc posés à sa suite, et non dans le
        # bloc Natura 2000 replié où on ne pensait pas à les remplir.
        self.text_critere = QTextEdit()
        self.text_critere.setPlaceholderText(
            "Critère ayant servi à évaluer l'état de conservation…"
        )
        self.text_critere.setMaximumHeight(55)
        form.addRow("Critère d'évaluation", self.text_critere)

        self.edit_pee = QLineEdit()
        self.edit_pee.setPlaceholderText("Taxon 1 ; Taxon 2 ; Taxon 3")
        self.edit_pee.setToolTip(
            "Plantes exotiques envahissantes : 3 taxons au plus, séparés par « ; »."
        )
        form.addRow("PEE", self.edit_pee)

        # ============ Natura 2000 (replié par défaut) ============
        # Quatre champs de plus sur chaque habitat : hors cartographie N2000 ils
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

        self.text_remarque = QTextEdit()
        self.text_remarque.setPlaceholderText("Remarque sur l'habitat…")
        self.text_remarque.setMaximumHeight(55)
        n2000_form.addRow("Remarque", self.text_remarque)

        form.addRow(self.n2000)
        self._set_n2000_visible(False)

        # ====== Abondance et sensibilité (repliées, en bas) ======
        # Deux menus qui n'appellent presque jamais d'intervention : l'abondance
        # se déduit du recouvrement saisi plus haut, la sensibilité a un défaut
        # d'instance (« Non sensible »). Les garder sous les yeux allongeait le
        # formulaire sans profit — mais ils restent à un clic, et la section
        # s'ouvre d'elle-même dès qu'une valeur s'écarte du défaut.
        self.btn_complements = QToolButton()
        self.btn_complements.setAutoRaise(True)
        self.btn_complements.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_complements.setStyleSheet(
            "QToolButton { border: none; font-weight: 600; }"
        )
        self.btn_complements.clicked.connect(self._toggle_complements)
        form.addRow(self.btn_complements)

        self.complements = QWidget()
        complements_form = QFormLayout(self.complements)
        complements_form.setContentsMargins(12, 0, 0, 0)

        self.combo_abundance = QComboBox()
        fill_eval_combo(self.combo_abundance, self.nomenclatures.get("abundance", []))
        select_combo_data(self.combo_abundance, self._defaults.get("abundance"))
        complements_form.addRow("Abondance", self.combo_abundance)

        # Sensibilité : absente de certaines instances → menu créé seulement si dispo.
        self.combo_sensitivity = None
        if self.nomenclatures.get("sensitivity"):
            self.combo_sensitivity = QComboBox()
            fill_eval_combo(self.combo_sensitivity, self.nomenclatures["sensitivity"])
            select_combo_data(self.combo_sensitivity, self._defaults.get("sensitivity"))
            complements_form.addRow("Sensibilité", self.combo_sensitivity)

        form.addRow(self.complements)
        self._set_complements_visible(False)

        if self._last_habitat:
            self._appliquer_reprise(self._last_habitat)
        # Cf. station_form : la molette ne doit pas modifier une valeur saisie.
        self._filtre_molette = proteger_du_defilement(self)
        # Les listes déroulantes ne doivent pas imposer leur largeur au dialogue.
        borner_largeur_combos(self)

    def _set_corresp_visible(self, visible):
        self.corresp_edit.setVisible(visible)
        self.btn_corresp.setText(
            ("▾ " if visible else "▸ ")
            + "Correspondances (CORINE, EUNIS, Natura 2000)"
        )

    def _toggle_corresp(self):
        self._set_corresp_visible(not self.corresp_edit.isVisible())

    def _set_n2000_visible(self, visible):
        self.n2000.setVisible(visible)
        self.btn_n2000.setText(
            ("▾ " if visible else "▸ ")
            + "Natura 2000 (typicité, dynamique, restauration, remarque)"
        )

    def _toggle_n2000(self):
        self._set_n2000_visible(not self.n2000.isVisible())

    def _set_complements_visible(self, visible):
        self.complements.setVisible(visible)
        self.btn_complements.setText(
            ("▾ " if visible else "▸ ") + "Abondance et sensibilité"
        )

    def _toggle_complements(self):
        self._set_complements_visible(not self.complements.isVisible())

    def _complements_hors_defaut(self, habitat):
        """Abondance ou sensibilité s'écartant du défaut d'instance ?

        Sert à décider du dépli : sans ce filtre, la section s'ouvrirait à chaque
        habitat relu — l'abondance et la sensibilité sont presque toujours
        renseignées, ne serait-ce que par leur défaut.
        """
        return any(
            habitat.get(colonne) is not None
            and habitat.get(colonne) != self._defaults.get(cle)
            for colonne, cle in (
                ("id_nomenclature_abundance", "abundance"),
                ("id_nomenclature_sensitivity", "sensitivity"),
            )
        )

    # ------------------------------------------- reprise de la saisie précédente
    def _appliquer_reprise(self, habitat):
        """Pré-remplir un NOUVEL habitat avec la saisie précédente, en le disant."""
        self.set_data(habitat)
        self.label_repris.setVisible(True)

    # ------------------------------------------------ autocomplétion HABREF
    def _on_habitat_chosen(self, cd_hab, nom):
        """Une proposition HABREF retenue renseigne le code ET le nom cité."""
        self.spin_cdhab.setValue(int(cd_hab))
        # Un choix HABREF direct n'est plus une détermination du catalogue : on
        # efface ce qu'un choix précédent aurait posé, sans quoi l'habitat
        # garderait une alliance et des correspondances qui ne le décrivent plus.
        self._determination = None
        self._proposer_pour(int(cd_hab))
        self._afficher_catalogue()

    def _proposer_pour(self, cd_hab):
        """Garnir les correspondances de CET habitat, quelle qu'en soit l'origine.

        Deux sources, dans cet ordre : le catalogue ANA s'il connaît ce `cd_hab`,
        sinon les correspondances que HABREF publie dans la fiche de l'habitat.
        Aucune n'est requise — sans l'une ni l'autre, les lignes restent en
        recherche libre. La section est TOUJOURS proposée : la bonne
        correspondance dépend de la station, donc elle doit rester ajustable même
        sur une détermination que personne n'a documentée.
        """
        item = self.edit_nom_cite.item_choisi or {}
        self.corresp_edit.definir_determination(
            item.get("lb_nom_typo"), item.get("lb_code")
        )

        if cd_hab not in self._fiches:
            self._fiches[cd_hab] = self._chercher_candidats(cd_hab)
        candidats, source = self._fiches[cd_hab]
        self.corresp_edit.proposer(candidats, source=source)
        self._set_corresp_visible(True)

    def _chercher_candidats(self, cd_hab):
        """({typologie: [candidats]}, origine) pour un cd_hab."""
        alliance = catalogue().par_cd_hab(cd_hab)
        if alliance is not None:
            return {
                cle: alliance.candidats(cle)
                for cle, _libelle in TYPOLOGIES_CORRESPONDANCE
            }, "catalogue"
        if self._habref_detail is None:
            return {}, "habref"
        try:
            fiche = self._habref_detail(cd_hab)
        except Exception:  # noqa: BLE001 - la saisie ne doit jamais être bloquée
            # Sans réseau on ne propose rien, et c'est tout : les lignes passent
            # en recherche libre, le botaniste garde la main.
            return {}, "habref"
        return candidats_habref(fiche, dict(self._typologies)), "habref"

    def _on_alliance_choisie(self, alliance):
        """Une alliance du catalogue ANA : détermination et correspondances.

        Appelé APRÈS `_on_habitat_chosen`, qui vient de poser le `cd_hab` et de
        remettre les deux clés à zéro — l'ordre est celui des connexions, et il
        compte.
        """
        self._determination = (
            {"nom": alliance.nom, "ancre": alliance.ancre_typologie}
            if alliance.est_ancree else None
        )
        # Le composant garnit ses listes depuis TOUTES les variantes de
        # l'alliance et ne retient d'office que les typologies sans ambiguïté.
        # Une alliance du catalogue n'est jamais elle-même une typologie cible :
        # ce que `_on_habitat_chosen` vient éventuellement de verrouiller sur un
        # choix HABREF antérieur n'a plus lieu d'être.
        self.corresp_edit.definir_determination(None, None)
        self.corresp_edit.proposer({
            cle: alliance.candidats(cle) for cle, _lib in TYPOLOGIES_CORRESPONDANCE
        })
        # Une correspondance reprise reste une affirmation sur l'habitat, et un
        # choix en suspens doit se voir : dans les deux cas la section s'ouvre.
        self._set_corresp_visible(True)
        self._afficher_catalogue(alliance)

    def _afficher_catalogue(self, alliance=None):
        """Dire ce que porte l'habitat — à la saisie comme à la relecture.

        Construit depuis l'état du formulaire et non depuis l'alliance : rouvrir
        un habitat déjà saisi doit afficher la même mise en garde que le jour de
        sa saisie, et corriger une correspondance doit mettre à jour la mention
        sur-le-champ. L'alliance, quand elle est là, ajoute ce que la donnée
        enregistrée ne porte pas — la condition Natura 2000.
        """
        lignes = []
        determination = self._determination or {}
        if determination.get("nom"):
            ancre = (determination.get("ancre") or "").replace("_", " ")
            lignes.append(
                "⚠ « %s » est absente de HABREF : le code%s est une ANCRE, pas la "
                "détermination — celle-ci est le nom cité."
                % (determination["nom"], " " + ancre if ancre else "")
            )
        resume = self.corresp_edit.resume()
        if resume:
            lignes.append("↺ Correspondances : %s — vérifiez-les." % resume)
        a_trancher = self.corresp_edit.a_trancher()
        if a_trancher:
            lignes.append(
                "⚠ Le catalogue propose plusieurs correspondances pour %s : "
                "choisissez-en une." % ", ".join(a_trancher)
            )
        if alliance is not None and alliance.condition_n2000:
            lignes.append(
                "⚠ Natura 2000 sous condition : %s" % alliance.condition_n2000
            )
        self.label_catalogue.setText("\n".join(lignes))
        self.label_catalogue.setVisible(bool(lignes))

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
            determination=self._determination,
            corresp=self.corresp_edit.get_data(),
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
        # Ne jamais cacher une valeur qui s'écarte du défaut (cf. N2000 plus bas).
        if self._complements_hors_defaut(habitat):
            self._set_complements_visible(True)
        precision = habitat.get("technical_precision") or ""
        self.text_precision.setPlainText(strip_eval(precision))
        codes = decode_eval(precision)
        self._determination = codes.get("determination")
        self.corresp_edit.set_data(codes.get("corresp"))
        self._set_corresp_visible(bool(codes.get("corresp")))
        self._afficher_catalogue()
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
                                          "remarque")):
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
