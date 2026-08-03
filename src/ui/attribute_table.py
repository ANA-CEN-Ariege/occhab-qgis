# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Table attributaire : voir et modifier stations et habitats en nombre.

Une ligne par habitat. Adaptateur **mince** au-dessus de `processing.grille`,
qui porte toute la logique risquée (propagation d'un champ station à ses lignes
sœurs, suivi des modifications, application en masse) et qui est testée sans Qt.

Les modifications sont accumulées dans le tampon puis écrites en une passe par
« Enregistrer » : on peut ainsi tout relire avant d'écrire, contrôler la
cohérence des recouvrements, et `Ctrl+Z` reste utile.
"""
import shutil
from datetime import datetime

from qgis.PyQt.QtCore import (
    QAbstractTableModel,
    QDate,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..database.sqlite_local import BROUILLON, VALIDE
from ..processing import champs as ch
from ..processing.grille import Grille
from ..processing.referentiels import label_for
from .dialog_size import ajuster_a_l_ecran
from .habref_widget import HabrefSearchEdit

# Jeux de colonnes : 25 colonnes ne tiennent pas à l'écran, et un botaniste qui
# saisit du N2000 n'a pas besoin de l'exposition ni de la profondeur.
JEUX_COLONNES = {
    "Essentiel": (ch.G_IDENTITE, ch.G_STATION, ch.G_HABITAT, ch.G_METIER),
    "Natura 2000": (ch.G_IDENTITE, ch.G_STATION, ch.G_N2000, ch.G_HABITAT),
    "Tout": None,  # tous les groupes
}
_TEINTE_STATION = QBrush(QColor(120, 144, 156, 30))   # colonnes partagées
_TEINTE_MODIFIE = QBrush(QColor(230, 145, 0, 70))     # même orangé que « à synchroniser »
_SEPARATEUR_LISTE = " ; "

# Édition en lot : le libellé annonce l'action *et* son ampleur, pour qu'on sache
# combien de lignes partent avant d'ouvrir la fenêtre.
LIBELLE_MODIFIER = "Modifier les lignes sélectionnées…"
LIBELLE_MODIFIER_1 = "Modifier la ligne sélectionnée…"
LIBELLE_MODIFIER_N = "Modifier les %d lignes sélectionnées…"


class Contexte:
    """Libellés dont la grille a besoin pour afficher des identifiants.

    Rassemblés ici pour que le modèle n'ait pas à connaître le dock.
    """

    def __init__(self, nomenclatures=None, datasets=None, habref_search=None,
                 typologies=None, observers=None):
        # {clé de champ: [(id_nomenclature, libellé)]}
        self.nomenclatures = nomenclatures or {}
        self.datasets = datasets or []  # [(id_dataset, nom)]
        self.habref_search = habref_search  # callable(texte, cd_typo) ou None
        self.typologies = typologies or []  # [(cd_typo, nom)]
        self.observers = observers or []  # [(id_role, nom)]
        self._jdd = dict(self.datasets)
        self._nomenclature = {
            cle: dict(items) for cle, items in self.nomenclatures.items()
        }

    def items(self, champ):
        """Couples (valeur, libellé) proposables pour un champ à liste."""
        if champ.type == ch.JDD:
            return list(self.datasets)
        if champ.type == ch.NOMENCLATURE:
            return list(self.nomenclatures.get(champ.nomenclature) or [])
        if champ.type == ch.CODE:
            return list(champ.referentiel or [])
        return []

    def libelle(self, champ, valeur):
        """Texte affiché pour une valeur brute."""
        if valeur is None or valeur == "":
            return ""
        if champ.type == ch.CODE:
            return label_for(champ.referentiel or [], valeur, str(valeur))
        if champ.type == ch.JDD:
            return self._jdd.get(valeur, str(valeur))
        if champ.type == ch.NOMENCLATURE:
            table = self._nomenclature.get(champ.nomenclature) or {}
            return table.get(valeur, str(valeur))
        if champ.type == ch.BOOLEEN:
            return "Oui" if valeur else ""
        if champ.type == ch.LISTE_TEXTE:
            return _SEPARATEUR_LISTE.join(valeur) if isinstance(valeur, list) else str(valeur)
        if champ.type == ch.OBSERVATEURS:
            return ", ".join(
                o.get("observer_name") or "" for o in valeur or [] if o.get("observer_name")
            )
        return str(valeur)


class GrilleModel(QAbstractTableModel):
    """Adaptateur Qt du tampon `Grille`."""

    def __init__(self, grille, colonnes, contexte, parent=None):
        super().__init__(parent)
        self.grille = grille
        self.colonnes = colonnes
        self.contexte = contexte

    # ---------------------------------------------------------- dimensions
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.grille)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.colonnes)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return section + 1 if role == Qt.ItemDataRole.DisplayRole else None
        champ = self.colonnes[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return champ.libelle
        if role == Qt.ItemDataRole.ToolTipRole:
            portee = "Champ de la station — partagé par ses habitats" \
                if champ.niveau == ch.STATION else "Champ de l'habitat"
            return "%s\n%s" % (champ.libelle, portee)
        return None

    # ---------------------------------------------------------- lecture
    def ligne(self, row):
        return self.grille.lignes[row]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        ligne = self.grille.lignes[index.row()]
        champ = self.colonnes[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            return self.contexte.libelle(champ, self.grille.valeur(ligne, champ))
        if role == Qt.ItemDataRole.EditRole:
            return self.grille.valeur(ligne, champ)
        if role == Qt.ItemDataRole.BackgroundRole:
            if self.grille.modifie(ligne, champ):
                return _TEINTE_MODIFIE
            if champ.niveau == ch.STATION:
                return _TEINTE_STATION
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            if champ.niveau == ch.STATION and len(self.grille.lignes_de(ligne)) > 1:
                return ("Champ de la station : le modifier ici le modifie pour "
                        "ses %d habitats." % len(self.grille.lignes_de(ligne)))
            return self.contexte.libelle(champ, self.grille.valeur(ligne, champ)) or None
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        ligne = self.grille.lignes[index.row()]
        champ = self.colonnes[index.column()]
        if self.grille.editable(ligne, champ):
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    # ---------------------------------------------------------- écriture
    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        ligne = self.grille.lignes[index.row()]
        champ = self.colonnes[index.column()]
        if not self.grille.definir(ligne, champ, value):
            return False
        # Un champ station vient de changer pour TOUTES les lignes de la station :
        # rafraîchir les lignes sœurs, sinon la table afficherait des valeurs
        # divergentes pour un même polygone.
        if champ.niveau == ch.STATION:
            rows = self.grille.lignes_de(ligne)
            self.dataChanged.emit(
                self.index(min(rows), index.column()),
                self.index(max(rows), index.column()),
            )
        else:
            self.dataChanged.emit(index, index)
        return True

    def rafraichir_tout(self):
        """Signaler que l'ensemble des cellules a pu changer (après une application en masse)."""
        if len(self.grille) and self.colonnes:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.grille) - 1, len(self.colonnes) - 1),
            )


class GrilleProxy(QSortFilterProxyModel):
    """Filtres statut / synchro / texte au-dessus du modèle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._statut = None
        self._sync = None
        self._texte = ""

    def set_filtres(self, statut=None, sync=None, texte=""):
        self._statut = statut
        self._sync = sync
        self._texte = (texte or "").strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        ligne = model.ligne(row)
        station = ligne.station
        if self._statut and station.get("validation_status") != self._statut:
            return False
        if self._sync and station.get("sync_status") != self._sync:
            return False
        if self._texte:
            morceaux = [
                station.get("station_name") or "",
                (ligne.habitat or {}).get("nom_cite") or "",
                str((ligne.habitat or {}).get("cd_hab") or ""),
            ]
            if self._texte not in " ".join(morceaux).lower():
                return False
        return True


class ChampDelegate(QStyledItemDelegate):
    """Éditeur adapté au type déclaré dans le registre de champs."""

    def __init__(self, colonnes, contexte, parent=None):
        super().__init__(parent)
        self.colonnes = colonnes
        self.contexte = contexte

    def createEditor(self, parent, option, index):
        champ = self.colonnes[index.column()]
        if champ.type in (ch.CODE, ch.NOMENCLATURE, ch.JDD):
            editor = QComboBox(parent)
            editor.addItem("— non renseigné —", None)
            for valeur, libelle in self.contexte.items(champ):
                editor.addItem(libelle, valeur)
            return editor
        if champ.type == ch.BOOLEEN:
            editor = QComboBox(parent)
            editor.addItem("", False)
            editor.addItem("Oui", True)
            return editor
        if champ.type == ch.DATE:
            editor = QDateEdit(parent)
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("yyyy-MM-dd")
            return editor
        if champ.type == ch.POURCENTAGE:
            editor = QDoubleSpinBox(parent)
            editor.setRange(0, 100)
            editor.setDecimals(1)
            editor.setSuffix(" %")
            editor.setSpecialValueText("—")  # 0 = non renseigné
            return editor
        if champ.type == ch.ENTIER:
            editor = QSpinBox(parent)
            editor.setRange(0, 1_000_000)
            editor.setSpecialValueText("—")
            return editor
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        champ = self.colonnes[index.column()]
        valeur = index.data(Qt.ItemDataRole.EditRole)
        if isinstance(editor, QComboBox):
            position = editor.findData(valeur if champ.type != ch.BOOLEEN else bool(valeur))
            editor.setCurrentIndex(position if position >= 0 else 0)
        elif isinstance(editor, QDateEdit):
            date = QDate.fromString((valeur or "")[:10], "yyyy-MM-dd")
            editor.setDate(date if date.isValid() else QDate.currentDate())
        elif isinstance(editor, QDoubleSpinBox):
            editor.setValue(float(valeur) if valeur else 0)
        elif isinstance(editor, QSpinBox):
            editor.setValue(int(valeur) if valeur else 0)
        else:
            editor.setText(self.contexte.libelle(champ, valeur))

    def setModelData(self, editor, model, index):
        champ = self.colonnes[index.column()]
        if isinstance(editor, QComboBox):
            valeur = editor.currentData()
        elif isinstance(editor, QDateEdit):
            valeur = editor.date().toString("yyyy-MM-dd")
        elif isinstance(editor, (QDoubleSpinBox, QSpinBox)):
            valeur = editor.value() or None
        else:
            texte = editor.text().strip()
            if champ.type == ch.LISTE_TEXTE:
                valeur = [p.strip() for p in texte.split(";") if p.strip()] or None
            else:
                valeur = texte or None
        model.setData(index, valeur, Qt.ItemDataRole.EditRole)


class _ObservateursEdit(QListWidget):
    """Cases à cocher pour composer une équipe d'observateurs.

    Rendu identique à ce que la base attend : `[{id_role, observer_name}]`.
    Une liste vide EFFACE les observateurs des stations visées — c'est cohérent
    avec les autres champs, où ne rien choisir signifie « vider ».
    """

    def __init__(self, observateurs, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setMaximumHeight(140)
        for id_role, nom in observateurs:
            item = QListWidgetItem(nom)
            item.setData(Qt.ItemDataRole.UserRole, id_role)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.addItem(item)
        if not observateurs:
            self.addItem(QListWidgetItem("— aucun observateur chargé (hors connexion) —"))
            self.setEnabled(False)

    def valeur(self):
        retenus = []
        for i in range(self.count()):
            item = self.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                retenus.append({
                    "id_role": item.data(Qt.ItemDataRole.UserRole),
                    "observer_name": item.text(),
                })
        return retenus


class AppliquerDialog(QDialog):
    """Choisir les champs à modifier sur les lignes sélectionnées.

    Chaque champ a une case « modifier » décochée : sans elle, ouvrir la fenêtre
    et valider écraserait tout avec des valeurs vides.
    """

    def __init__(self, contexte, nb_lignes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier les lignes sélectionnées")
        self.contexte = contexte
        self._editeurs = {}  # (niveau, cle) -> (case, widget, champ)

        layout = QVBoxLayout(self)
        # La colonne de cases à cocher n'a pas d'en-tête : c'est ici qu'on dit
        # à quoi elle sert.
        cible = (
            "La ligne sélectionnée recevra"
            if nb_lignes == 1
            else "Les %d lignes sélectionnées recevront" % nb_lignes
        )
        entete = QLabel(
            "%s la même valeur pour chaque champ coché ci-dessous. Les champs "
            "non cochés sont laissés tels quels." % cible
        )
        entete.setWordWrap(True)
        layout.addWidget(entete)

        # Une vingtaine de champs : sans ascenseur, la fenêtre dépasse l'écran et
        # les boutons deviennent inatteignables.
        interieur = QWidget()
        form = QFormLayout(interieur)
        for champ in ch.modifiables_en_masse():
            case = QCheckBox()
            widget = self._widget(champ)
            widget.setEnabled(False)
            case.toggled.connect(widget.setEnabled)
            rang = QWidget()
            box = QHBoxLayout(rang)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(case)
            box.addWidget(widget, 1)
            portee = "station" if champ.niveau == ch.STATION else "habitat"
            form.addRow("%s (%s)" % (champ.libelle, portee), rang)
            self._editeurs[(champ.niveau, champ.cle)] = (case, widget, champ)
        self._lier_habref()
        ascenseur = QScrollArea()
        ascenseur.setWidgetResizable(True)
        ascenseur.setWidget(interieur)
        layout.addWidget(ascenseur, 1)

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        layout.addWidget(boutons)

    def showEvent(self, event):
        super().showEvent(event)
        ajuster_a_l_ecran(self, 520, 620)

    def _widget(self, champ):
        if champ.type == ch.OBSERVATEURS:
            return _ObservateursEdit(self.contexte.observers)
        if (champ.niveau, champ.cle) == (ch.HABITAT, "nom_cite"):
            # Choisir un habitat, pas taper un nom : le code suit automatiquement.
            return HabrefSearchEdit(
                habref_search=self.contexte.habref_search,
                typologies=self.contexte.typologies,
                libelle="Nom cité",
            )
        if champ.type in (ch.CODE, ch.NOMENCLATURE, ch.JDD):
            widget = QComboBox()
            widget.addItem("— vider —", None)
            for valeur, libelle in self.contexte.items(champ):
                widget.addItem(libelle, valeur)
            return widget
        if champ.type == ch.BOOLEEN:
            widget = QComboBox()
            widget.addItem("Non", False)
            widget.addItem("Oui", True)
            return widget
        if champ.type == ch.DATE:
            widget = QDateEdit(QDate.currentDate())
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
            return widget
        if champ.type == ch.POURCENTAGE:
            widget = QDoubleSpinBox()
            widget.setRange(0, 100)
            widget.setDecimals(1)
            widget.setSuffix(" %")
            return widget
        if champ.type == ch.ENTIER:
            widget = QSpinBox()
            widget.setRange(0, 1_000_000)
            return widget
        return QLineEdit()

    def _lier_habref(self):
        """Un habitat choisi renseigne le nom ET le code, et coche les deux cases.

        Sans cela, l'utilisateur pousserait un nom sur 40 habitats en laissant
        leur cd_hab pointer sur l'ancienne détermination.
        """
        nom = self._editeurs.get((ch.HABITAT, "nom_cite"))
        code = self._editeurs.get((ch.HABITAT, "cd_hab"))
        if not nom or not code or not isinstance(nom[1], HabrefSearchEdit):
            return

        def _sur_choix(cd_hab, libelle):
            nom[0].setChecked(True)
            code[0].setChecked(True)
            code[1].setValue(int(cd_hab))

        nom[1].habitat_choisi.connect(_sur_choix)

    def valeurs(self):
        """{(niveau, clé): valeur} pour les seuls champs cochés."""
        choix = {}
        for cle, (case, widget, champ) in self._editeurs.items():
            if not case.isChecked():
                continue
            if isinstance(widget, _ObservateursEdit):
                valeur = widget.valeur()
            elif isinstance(widget, QComboBox):
                valeur = widget.currentData()
            elif isinstance(widget, QDateEdit):
                valeur = widget.date().toString("yyyy-MM-dd")
            elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                valeur = widget.value() or None
            else:
                texte = widget.text().strip()
                valeur = ([p.strip() for p in texte.split(";") if p.strip()] or None
                          if champ.type == ch.LISTE_TEXTE else texte or None)
            choix[cle] = valeur
        return choix


class AttributeTableDialog(QDialog):
    """Fenêtre principale : filtres, table, application en masse, enregistrement."""

    #: Émis après un enregistrement : la fenêtre étant non modale, le reste de
    #: l'interface afficherait sinon l'état d'avant le lot.
    donnees_enregistrees = pyqtSignal()

    def __init__(self, db, stations, contexte, layers=None, logger=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OccHab — Stations et habitats")
        self.db = db
        self.logger = logger
        self.contexte = contexte
        self.layers = layers  # StationLayerManager : sélection carte ↔ table
        self.grille = Grille(stations)
        self.jeu_courant = "Essentiel"
        self._build()
        self._appliquer_jeu_colonnes()
        if self.layers is not None:
            self.layers.add_selection_listener(self._on_map_selection_changed)

    # -------------------------------------------------- sélection ↔ carte
    def _on_table_selection_changed(self):
        """Table → carte."""
        self._maj_boutons_selection()  # avant le garde-fou : vrai même sans carte
        if self.layers is None:
            return
        ids = {ligne.station.get("id") for ligne in self._lignes_selectionnees()}
        try:
            self.layers.select_stations(ids)
        except Exception as exc:  # noqa: BLE001 - la carte ne doit pas casser la table
            if self.logger:
                self.logger.debug("Sélection carte non appliquée : %s", exc)

    def _on_map_selection_changed(self):
        """Carte → table : sélectionner toutes les lignes des stations retenues.

        Une station en mosaïque occupe plusieurs lignes : les sélectionner toutes
        est le seul comportement cohérent avec « une ligne par habitat ».
        """
        if self.layers is None:
            return
        ids = set(self.layers.selected_station_ids())
        modele = self.table.selectionModel()
        if modele is None:
            return
        selection = QItemSelection()
        derniere = len(self.colonnes) - 1
        for row in range(self.proxy.rowCount()):
            source = self.proxy.mapToSource(self.proxy.index(row, 0)).row()
            if self.grille.lignes[source].station.get("id") in ids:
                selection.select(self.proxy.index(row, 0), self.proxy.index(row, derniere))
        modele.blockSignals(True)  # sinon la table repousserait vers la carte
        try:
            modele.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        finally:
            modele.blockSignals(False)
        # Signaux bloqués : `_on_table_selection_changed` ne partira pas.
        self._maj_boutons_selection()

    # ------------------------------------------------------------- UI
    def _build(self):
        layout = QVBoxLayout(self)

        barre = QHBoxLayout()
        self.combo_jeu = QComboBox()
        self.combo_jeu.addItems(list(JEUX_COLONNES))
        self.combo_jeu.currentTextChanged.connect(self._on_jeu_change)
        barre.addWidget(QLabel("Colonnes"))
        barre.addWidget(self.combo_jeu)

        self.combo_statut = QComboBox()
        self.combo_statut.addItem("Tous les statuts", None)
        self.combo_statut.addItem("Brouillons", BROUILLON)
        self.combo_statut.addItem("Validées", VALIDE)
        self.combo_statut.currentIndexChanged.connect(self._on_filtre_change)
        barre.addWidget(self.combo_statut)

        self.combo_sync = QComboBox()
        self.combo_sync.addItem("Toute synchro", None)
        self.combo_sync.addItem("À synchroniser", "pending")
        self.combo_sync.addItem("Synchronisées", "synced")
        self.combo_sync.addItem("En conflit", "conflict")
        self.combo_sync.currentIndexChanged.connect(self._on_filtre_change)
        barre.addWidget(self.combo_sync)

        self.edit_recherche = QLineEdit()
        self.edit_recherche.setPlaceholderText("Filtrer (nom de station, habitat, cd_hab)…")
        self.edit_recherche.textChanged.connect(self._on_filtre_change)
        barre.addWidget(self.edit_recherche, 1)
        layout.addLayout(barre)

        self.table = QTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        layout.addWidget(self.table, 1)

        self.label_etat = QLabel("")
        self.label_etat.setWordWrap(True)
        layout.addWidget(self.label_etat)

        pied = QHBoxLayout()
        self.btn_appliquer = QPushButton(LIBELLE_MODIFIER)
        self.btn_appliquer.setToolTip(
            "Remplir un ou plusieurs champs d'un coup sur toutes les lignes "
            "sélectionnées (rien n'est écrit en base avant « Enregistrer »)."
        )
        self.btn_appliquer.setEnabled(False)
        # Le libellé porte le nombre de lignes : sans largeur plancher, le bouton
        # change de taille à chaque sélection et toute la barre saute.
        self.btn_appliquer.setMinimumWidth(
            self.btn_appliquer.fontMetrics().horizontalAdvance(
                LIBELLE_MODIFIER_N % 999
            )
            + 24
        )
        self.btn_appliquer.clicked.connect(self.appliquer_a_la_selection)
        self.btn_valider = QPushButton("Marquer comme validées")
        self.btn_valider.setToolTip(
            "Passer les stations sélectionnées de « Brouillon » à « Validé »."
        )
        self.btn_valider.setEnabled(False)
        self.btn_valider.clicked.connect(self.valider_selection)
        pied.addWidget(self.btn_appliquer)
        pied.addWidget(self.btn_valider)
        pied.addStretch(1)
        self.btn_enregistrer = QPushButton("Enregistrer")
        self.btn_enregistrer.clicked.connect(self.enregistrer)
        btn_fermer = QPushButton("Fermer")
        btn_fermer.clicked.connect(self.close)
        pied.addWidget(self.btn_enregistrer)
        pied.addWidget(btn_fermer)
        layout.addLayout(pied)

    def showEvent(self, event):
        super().showEvent(event)
        # Recalculé à chaque ouverture : l'écran a pu changer entre-temps.
        ajuster_a_l_ecran(self, 1150, 620)

    def _appliquer_jeu_colonnes(self):
        groupes = JEUX_COLONNES.get(self.jeu_courant)
        colonnes = [c for c in ch.CHAMPS if groupes is None or c.groupe in groupes]
        self.colonnes = colonnes
        self.model = GrilleModel(self.grille, colonnes, self.contexte, self)
        self.proxy = GrilleProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table.setModel(self.proxy)
        self.table.setItemDelegate(ChampDelegate(colonnes, self.contexte, self))
        for index, champ in enumerate(colonnes):
            self.table.setColumnWidth(index, champ.largeur)
        # Le modèle et son modèle de sélection sont neufs après chaque
        # `setModel` : tout rebrancher ici.
        self.table.selectionModel().selectionChanged.connect(
            self._on_table_selection_changed
        )
        # Sans cela, modifier une cellule ne réveillait pas « Enregistrer » :
        # seule l'application en masse mettait l'état à jour.
        self.model.dataChanged.connect(lambda *_: self._maj_etat())
        self._on_filtre_change()

    def _on_jeu_change(self, nom):
        self.jeu_courant = nom
        self._appliquer_jeu_colonnes()

    def _on_filtre_change(self):
        self.proxy.set_filtres(
            statut=self.combo_statut.currentData(),
            sync=self.combo_sync.currentData(),
            texte=self.edit_recherche.text(),
        )
        self._maj_etat()

    def _maj_etat(self):
        visibles = self.proxy.rowCount()
        modifiees = len(self.grille.modifications())
        texte = "%d ligne(s) affichée(s) sur %d" % (visibles, len(self.grille))
        if modifiees:
            texte += "  ·  %d station(s) modifiée(s), non enregistrée(s)" % modifiees
        self.label_etat.setText(texte)
        self.btn_enregistrer.setEnabled(bool(modifiees))
        # Couvre le changement de filtre et le changement de jeu de colonnes,
        # qui recrée le modèle de sélection donc repart d'une sélection vide.
        self._maj_boutons_selection()

    def _maj_boutons_selection(self):
        """Les actions de lot n'ont de sens qu'avec des lignes sélectionnées."""
        nb = len(self._lignes_selectionnees())
        if nb == 0:
            self.btn_appliquer.setText(LIBELLE_MODIFIER)
        elif nb == 1:
            self.btn_appliquer.setText(LIBELLE_MODIFIER_1)
        else:
            self.btn_appliquer.setText(LIBELLE_MODIFIER_N % nb)
        self.btn_appliquer.setEnabled(bool(nb))
        self.btn_valider.setEnabled(bool(nb))

    # ------------------------------------------------------------- sélection
    def _lignes_selectionnees(self):
        modele = self.table.selectionModel()
        if modele is None:  # appelé avant le premier setModel
            return []
        # `selectedRows()` rend UN index par ligne, `selectedIndexes()` un par
        # cellule : avec le jeu « Tout » c'était 35 fois plus de mappings proxy,
        # à chaque changement de sélection et à chaque cellule éditée.
        lignes, vus = [], set()
        for index in modele.selectedRows():
            source = self.proxy.mapToSource(index).row()
            if source not in vus:
                vus.add(source)
                lignes.append(self.grille.lignes[source])
        return lignes

    # ------------------------------------------------------------- rechargement
    def a_des_modifications(self):
        return self.grille.a_des_modifications()

    def recharger(self, stations):
        """Reprendre l'état de la base après une écriture faite ailleurs.

        Refusé s'il reste des modifications non enregistrées : elles seraient
        perdues sans que l'utilisateur l'ait demandé. L'appelant l'a déjà
        vérifié ; ce garde-fou évite qu'un futur appel s'en dispense.
        """
        if self.grille.a_des_modifications():
            return False
        self.grille = Grille(stations)
        self._appliquer_jeu_colonnes()  # reconstruit modèle, proxy et connexions
        return True

    def appliquer_a_la_selection(self):
        lignes = self._lignes_selectionnees()
        if not lignes:
            QMessageBox.information(self, "OccHab", "Sélectionnez d'abord des lignes.")
            return
        dialogue = AppliquerDialog(self.contexte, len(lignes), self)
        if not dialogue.exec():
            return
        valeurs = dialogue.valeurs()
        if not valeurs:
            QMessageBox.information(self, "OccHab", "Aucun champ coché : rien à appliquer.")
            return
        apercu = self.grille.previsualiser(lignes, valeurs)
        if not self._confirmer(valeurs, apercu):
            return
        self.grille.appliquer(lignes, valeurs)
        self.model.rafraichir_tout()
        self._maj_etat()

    def _confirmer(self, valeurs, apercu):
        """Récapitulatif avant application. Le chiffre qui compte : les écrasements."""
        details = []
        for (niveau, cle), valeur in sorted(valeurs.items()):
            champ = ch.par_cle(niveau, cle)
            libelle = self.contexte.libelle(champ, valeur) or "— vidé —"
            details.append("• %s → %s" % (champ.libelle, libelle))
        message = [
            "%d station(s) et %d habitat(s) seront modifiés :"
            % (apercu["stations"], apercu["habitats"]),
            "",
            "\n".join(details),
        ]
        if apercu["ecrasements"]:
            message += [
                "",
                "⚠ %d valeur(s) déjà renseignée(s) seront remplacées."
                % apercu["ecrasements"],
            ]
        message += ["", "Rien n'est écrit en base avant « Enregistrer »."]
        return QMessageBox.question(
            self, "Modifier les lignes sélectionnées", "\n".join(message)
        ) == QMessageBox.StandardButton.Yes

    def valider_selection(self):
        lignes = self._lignes_selectionnees()
        if not lignes:
            QMessageBox.information(self, "OccHab", "Sélectionnez d'abord des lignes.")
            return
        champ = ch.par_cle(ch.STATION, "validation_status")
        self.grille.appliquer(lignes, {(ch.STATION, champ.cle): VALIDE})
        self.model.rafraichir_tout()
        self._maj_etat()

    # ------------------------------------------------------------- écriture
    def enregistrer(self):
        modifiees = self.grille.modifications()
        if not modifiees:
            QMessageBox.information(self, "OccHab", "Aucune modification à enregistrer.")
            return
        if not self._verifier_recouvrements():
            return

        # Une station validée sur laquelle on est revenu redevient un brouillon.
        self.grille.retrograder_statuts()

        sauvegarde = self._sauvegarder_base()
        ecrites = echecs = disparues = 0
        for station in modifiees:
            try:
                if self._ecrire_station(station):
                    ecrites += 1
                else:
                    disparues += 1
            except Exception as exc:  # noqa: BLE001 - une station en échec ne doit pas tout arrêter
                echecs += 1
                if self.logger:
                    self.logger.error("Station %s non enregistrée : %s",
                                      station.get("id"), exc)
        if not echecs and not disparues:
            self.grille.oublier_modifications()
        self.model.rafraichir_tout()
        self._maj_etat()
        # La liste du dock et la carte affichent encore l'état d'avant : la table
        # est non modale, elle peut rester ouverte des heures après un lot.
        self.donnees_enregistrees.emit()

        message = "%d station(s) enregistrée(s)." % ecrites
        if disparues:
            message += ("\n%d station(s) ont été supprimées depuis l'ouverture de "
                        "la table : leurs modifications sont abandonnées." % disparues)
        if echecs:
            message += " %d échec(s) — voir le journal." % echecs
        if sauvegarde:
            message += "\nSauvegarde préalable : %s" % sauvegarde
        QMessageBox.information(self, "OccHab", message)

    def _ecrire_station(self, station):
        """Écrire les SEULS champs modifiés. False si la station n'existe plus.

        Réécrire la ligne entière depuis la copie mémoire de la table écrasait
        tout ce qu'une autre fenêtre avait enregistré entre-temps : une édition
        faite dans le formulaire, et surtout l'`id_station` posé par une synchro,
        dont la perte faisait recréer un doublon sur GeoNature au prochain envoi.
        """
        if not self.db.station_exists(station["id"]):
            if self.logger:
                self.logger.warning("Station %s supprimée entre-temps : ignorée",
                                    station.get("id"))
            return False
        etait_en_conflit = station.get("sync_status") == "conflict"
        champs = {
            cle: station.get(cle) for cle in self.grille.colonnes_modifiees(station)
        }
        if "observers" in champs:
            # Ni une colonne ni un champ envoyé tel quel : la liste vit dans une
            # table à part, et sa version texte alimente la liste du dock,
            # l'export et le payload GeoNature.
            champs.pop("observers")
            observateurs = station.get("observers") or []
            champs["observers_txt"] = ", ".join(
                o.get("observer_name") or "" for o in observateurs
            ) or None
            self.db.replace_observers(station["id"], observateurs)
        champs["sync_status"] = "pending"  # toute édition remet en attente d'envoi
        self.db.update_station(station["id"], **champs)
        if self.grille.habitats_modifies(station):
            self.db.replace_habitats(station["id"], station.get("habitats") or [])
        if etait_en_conflit:
            # Conflit résolu côté local : oublier l'empreinte pour que la
            # prochaine synchro impose cette version (cf. édition unitaire).
            self.db.set_server_snapshot(station["id"], None)
        return True

    def _verifier_recouvrements(self):
        """Avertir si un polygone ne totalise pas 100 % (exigence N2000).

        Avertissement, pas blocage : une cartographie en cours de saisie est
        légitimement incomplète.
        """
        fautives = self.grille.recouvrements_incoherents()
        if not fautives:
            return True
        apercu = "\n".join(
            "• %s : %g %%" % (s.get("station_name") or "station %s" % s.get("id"), total)
            for s, total in fautives[:10]
        )
        reste = "\n… et %d autre(s)." % (len(fautives) - 10) if len(fautives) > 10 else ""
        return QMessageBox.question(
            self, "Recouvrements",
            "%d station(s) ne totalisent pas 100 %% de recouvrement :\n\n%s%s\n\n"
            "Enregistrer quand même ?" % (len(fautives), apercu, reste),
        ) == QMessageBox.StandardButton.Yes

    def _sauvegarder_base(self):
        """Copier la base avant une écriture en masse. Renvoie le chemin, ou None.

        C'est la seule annulation réelle d'une modification portant sur des
        dizaines de stations ; elle coûte une copie de fichier.
        """
        try:
            cible = self.db.db_path.with_name(
                "%s.avant-lot-%s.db" % (self.db.db_path.stem,
                                        datetime.now().strftime("%Y%m%d-%H%M%S"))
            )
            shutil.copy2(str(self.db.db_path), str(cible))
            return str(cible)
        except OSError as exc:
            if self.logger:
                self.logger.warning("Sauvegarde préalable impossible : %s", exc)
            return None

    # ------------------------------------------------------------- fermeture
    def closeEvent(self, event):
        if self.grille.a_des_modifications():
            reponse = QMessageBox.question(
                self, "Modifications non enregistrées",
                "%d station(s) modifiée(s) ne sont pas enregistrées. Fermer quand "
                "même ?" % len(self.grille.modifications()),
            )
            if reponse != QMessageBox.StandardButton.Yes:
                event.ignore()
                return  # fermeture annulée : on RESTE abonné à la carte
        if self.layers is not None:
            # Une fenêtre fermée ne doit plus réagir aux sélections carte, sinon
            # on manipulerait des widgets détruits.
            self.layers.remove_selection_listener(self._on_map_selection_changed)
        event.accept()
