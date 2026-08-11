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
    QTimer,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QBrush, QColor, QKeySequence
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSpinBox,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..api.payload import mesures_incoherentes
from ..database.sqlite_local import BROUILLON, VALIDE
from ..processing import champs as ch
from ..processing import correspondances as corresp
from ..processing.correspondances import Catalogue
from ..processing.grille import Grille
from ..processing.referentiels import TYPOLOGIES_CORRESPONDANCE, label_for
from ..processing.tableur import tsv
from .dialog_size import ajuster_a_l_ecran, borner_largeur_combos
from .habref_widget import HabrefLineEdit, HabrefSearchEdit
from .no_wheel import FiltreMolette, proteger_du_defilement

#: Catalogue vide, passé explicitement aux champs qui n'écrivent que le nom cité
#: et le cd_hab (cf. `_creer_editeur`). Le nommer vaut mieux qu'un `Catalogue([])`
#: anonyme répété : c'est une décision, pas un détail d'appel.
SANS_CATALOGUE = Catalogue([])

# Jeux de colonnes : 25 colonnes ne tiennent pas à l'écran, et un botaniste qui
# saisit du N2000 n'a pas besoin de l'exposition ni de la profondeur.
JEUX_COLONNES = {
    "Essentiel": (ch.G_IDENTITE, ch.G_STATION, ch.G_HABITAT, ch.G_METIER),
    "Natura 2000": (ch.G_IDENTITE, ch.G_STATION, ch.G_N2000, ch.G_HABITAT),
    "Tout": None,  # tous les groupes
}
_TEINTE_MODIFIE = QBrush(QColor(230, 145, 0, 70))     # même orangé que « à synchroniser »
# Fonds de cellule. Deux informations se superposent : la colonne est-elle
# partagée par toute la station, et à quel polygone appartient la ligne. La
# seconde compte davantage — trois lignes d'affilée peuvent décrire une seule
# mosaïque — d'où un aplat qui court sur toute la LARGEUR de la ligne, un
# polygone sur deux. Il remplace l'alternance ligne à ligne de Qt, qui coupait
# les mosaïques en tranches et faisait exactement croire le contraire.
_ARDOISE = (120, 144, 156)
_TEINTE_STATION = (QBrush(QColor(*_ARDOISE, 30)), QBrush(QColor(*_ARDOISE, 52)))
_TEINTE_LIGNE = (None, QBrush(QColor(*_ARDOISE, 22)))
_SEPARATEUR_LISTE = " ; "

# Édition en lot : le libellé annonce l'action *et* son ampleur, pour qu'on sache
# combien de lignes partent avant d'ouvrir la fenêtre.
LIBELLE_MODIFIER = "Modifier les lignes sélectionnées…"
LIBELLE_MODIFIER_1 = "Modifier la ligne sélectionnée…"
LIBELLE_MODIFIER_N = "Modifier les %d lignes sélectionnées…"

#: Suffixes de niveau portés par certains libellés du registre pour les
#: distinguer entre eux (« Enjeu (station) » / « Enjeu (habitat) »). Sous un
#: titre de section qui dit déjà le niveau, ils font double emploi.
_SUFFIXES_NIVEAU = (" (station)", " (habitat)")


def _libelle_court(champ):
    """Libellé du champ sans son suffixe de niveau."""
    for suffixe in _SUFFIXES_NIVEAU:
        if champ.libelle.endswith(suffixe):
            return champ.libelle[: -len(suffixe)]
    return champ.libelle


class Contexte:
    """Libellés dont la grille a besoin pour afficher des identifiants.

    Rassemblés ici pour que le modèle n'ait pas à connaître le dock.
    """

    def __init__(self, nomenclatures=None, datasets=None, habref_labels=None,
                 habref_search=None, habref_detail=None,
                 typologies=None, observers=None, cd_typo=None):
        # {clé de champ: [(id_nomenclature, libellé)]}
        self.nomenclatures = nomenclatures or {}
        self.datasets = datasets or []  # [(id_dataset, nom)]
        self.habref_search = habref_search  # callable(texte, cd_typo) ou None
        # callable(cd_hab) -> fiche HABREF. Elle porte les correspondances que le
        # référentiel connaît : sans elle, l'édition en masse ne peut proposer que
        # ce que le catalogue de l'ANA sait, et un habitat déterminé hors
        # catalogue n'a qu'un champ de recherche vide.
        self.habref_detail = habref_detail
        # {cd_hab: libellé HABREF}. Rempli par le dock, qui le garde d'une
        # session à l'autre : interroger le référentiel pour chaque ligne à
        # chaque ouverture de la table serait insupportable.
        self.habref_labels = dict(habref_labels or {})
        self.typologies = typologies or []  # [(cd_typo, nom)]
        self.cd_typo = cd_typo  # typologie de la dernière saisie, présélectionnée
        self.observers = observers or []  # [(id_role, nom)]
        self._jdd = dict(self.datasets)
        self._nomenclature = {
            cle: dict(items) for cle, items in self.nomenclatures.items()
        }

    def poser_libelles_habref(self, stations):
        """Écrire le libellé HABREF sur chaque habitat, d'après le cache.

        Sur les dicts d'habitat eux-mêmes plutôt que par un cas particulier dans
        le modèle : la valeur circule alors comme toutes les autres — affichage,
        infobulle, copie vers un tableur, tri.
        """
        for station in stations or []:
            for habitat in station.get("habitats") or []:
                cd_hab = habitat.get("cd_hab")
                habitat[ch.HABREF] = self.habref_labels.get(cd_hab) or \
                    self.habref_labels.get(str(cd_hab)) or ""
        return stations

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
            if (champ.niveau, champ.cle) == (ch.HABITAT, "nom_cite"):
                # Hors connexion la cellule redevient du texte libre : le dire,
                # sinon on croit avoir changé d'habitat alors que le cd_hab de la
                # ligne pointe toujours sur l'ancienne détermination.
                portee += (
                    "\nDouble-clic : liste HABREF ; l'habitat choisi renseigne "
                    "aussi le cd_hab."
                    if self.contexte.habref_search is not None else
                    "\nHors connexion : saisie libre — pensez à corriger le "
                    "cd_hab vous-même."
                )
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
            if champ.cle == ch.ID_STATION:
                # Rendu en NOMBRE et non en texte : la table se trie alors par
                # ordre numérique, où « 9 » précède « 10 ».
                return self.grille.valeur(ligne, champ)
            return self.contexte.libelle(champ, self.grille.valeur(ligne, champ))
        if role == Qt.ItemDataRole.EditRole:
            return self.grille.valeur(ligne, champ)
        if role == Qt.ItemDataRole.BackgroundRole:
            if self.grille.modifie(ligne, champ):
                return _TEINTE_MODIFIE
            bande = self.grille.rang_station(ligne) % 2
            teintes = (_TEINTE_STATION if champ.niveau == ch.STATION
                       else _TEINTE_LIGNE)
            return teintes[bande]
        if role == Qt.ItemDataRole.ToolTipRole:
            if champ.cle == ch.ID_STATION:
                return self._infobulle_station(index.row())
            if champ.cle == ch.HABREF and not self.grille.valeur(ligne, champ):
                return self._infobulle_habref(ligne)
            if champ.niveau == ch.STATION and len(self.grille.lignes_de(ligne)) > 1:
                return ("Champ de la station : le modifier ici le modifie pour "
                        "ses %d habitats." % len(self.grille.lignes_de(ligne)))
            return self.contexte.libelle(champ, self.grille.valeur(ligne, champ)) or None
        return None

    def _infobulle_habref(self, ligne):
        """Dire pourquoi la case est vide : sans cela, on croit à une donnée perdue."""
        if ligne.habitat is None:
            return None
        if not ligne.habitat.get("cd_hab"):
            return "Aucun cd_hab : rien à demander au référentiel."
        return ("Libellé pas encore obtenu du référentiel — hors ligne au moment "
                "de l'ouverture, ou code absent de HABREF. Il sera redemandé à "
                "la prochaine ouverture de cette table ; le journal du plugin "
                "(Base locale… ▸ Ouvrir le dossier) en donne la raison exacte.")

    def _infobulle_station(self, row):
        """Situer la ligne dans sa mosaïque, ce qu'un identifiant seul ne dit pas.

        Sur la ligne (`row`) et non sur la `Ligne` : deux habitats aux mêmes
        valeurs sont des tuples ÉGAUX, donc introuvables l'un sans l'autre.
        """
        ligne = self.grille.lignes[row]
        soeurs = self.grille.lignes_de(ligne)
        identifiant = ligne.station.get(ch.ID_STATION)
        tete = ("Station %s" % identifiant if identifiant
                else "Station pas encore synchronisée : elle n'a pas encore "
                     "d'identifiant GeoNature")
        if ligne.habitat is None:
            return "%s — aucun habitat saisi" % tete
        if len(soeurs) == 1:
            return "%s — un seul habitat" % tete
        return ("%s — habitat %d sur %d ; les %d lignes décrivent la même "
                "mosaïque." % (tete, soeurs.index(row) + 1, len(soeurs), len(soeurs)))

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

    def definir_par_cle(self, row, niveau, cle, valeur):
        """Poser un champ d'une ligne par sa clé, colonne affichée ou non.

        Choisir un habitat dans la cellule « Nom cité » doit aussi écrire son
        `cd_hab` — or cette colonne peut très bien ne pas être affichée dans le
        jeu courant. Passer par la clé, et non par un numéro de colonne, est le
        seul moyen d'écrire les deux ensemble sans dépendre de l'affichage.
        """
        champ = ch.par_cle(niveau, cle)
        if champ is None or not (0 <= row < len(self.grille)):
            return False
        if not self.grille.definir(self.grille.lignes[row], champ, valeur):
            return False
        # La colonne peut être absente de l'affichage : rafraîchir la ligne
        # entière est plus simple et sans risque que de la chercher.
        self.dataChanged.emit(self.index(row, 0),
                              self.index(row, len(self.colonnes) - 1))
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
        # Un éditeur de cellule est créé à la volée : il doit être protégé dès
        # sa naissance, sinon la molette modifie la valeur qu'on vient d'ouvrir.
        self._filtre_molette = FiltreMolette(self)

    def _creer_editeur(self, parent, option, index):
        champ = self.colonnes[index.column()]
        # Nom cité : choisir un habitat dans la liste HABREF, comme au
        # formulaire. Retaper le nom à la main laissait le cd_hab de la ligne
        # sur l'ancienne détermination — une donnée incohérente, et invisible.
        if ((champ.niveau, champ.cle) == (ch.HABITAT, "nom_cite")
                and self.contexte.habref_search is not None):
            editor = HabrefLineEdit(
                habref_search=self.contexte.habref_search,
                typo_names=dict(self.contexte.typologies),
                cd_typo=self.contexte.cd_typo,
                # Pas de catalogue ANA ici : une cellule n'écrit que le nom cité
                # et le cd_hab. Une alliance ancrée y poserait un code CORINE
                # d'emprunt SANS la détermination qui dit que c'en est un —
                # exactement l'ambiguïté que cette détermination existe pour
                # lever. Le catalogue se choisit au formulaire, qui sait écrire
                # le bloc complet.
                catalogue=SANS_CATALOGUE,
                parent=parent,
            )
            # Valider dès qu'une proposition est retenue : sans cela il faudrait
            # encore appuyer sur Entrée dans une cellule qui semble déjà remplie.
            editor.habitat_choisi.connect(
                lambda _cd, _nom, e=editor: self._valider_habref(e)
            )
            return editor
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

    def createEditor(self, parent, option, index):  # noqa: F811 - enveloppe
        editor = self._creer_editeur(parent, option, index)
        editor.installEventFilter(self._filtre_molette)
        return editor

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

    def _valider_habref(self, editor):
        """Écrire la cellule et refermer l'éditeur dès l'habitat choisi.

        Différé d'un tour de boucle : on est ici DANS le signal du complèteur,
        dont le menu déroulant est encore ouvert sur ce même champ. Le refermer
        sur-le-champ reviendrait à détruire un widget en cours d'utilisation.
        """
        def _valider():
            try:
                self.commitData.emit(editor)
                self.closeEditor.emit(editor)
            except RuntimeError:  # pragma: no cover - éditeur déjà refermé
                pass

        QTimer.singleShot(0, _valider)

    def setModelData(self, editor, model, index):
        champ = self.colonnes[index.column()]
        if isinstance(editor, HabrefLineEdit):
            # `nom_choisi` plutôt que le texte du champ : le complèteur peut
            # encore être en train d'y réécrire le libellé préfixé de la
            # typologie, qui n'est pas le nom cité.
            nom = editor.nom_choisi or editor.text().strip() or None
            model.setData(index, nom, Qt.ItemDataRole.EditRole)
            if editor.cd_choisi is not None and editor.nom_choisi:
                self._ecrire_cd_hab(model, index, editor.cd_choisi)
            return
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

    @staticmethod
    def _ecrire_cd_hab(model, index, cd_hab):
        """Poser le cd_hab de la MÊME ligne, à travers le filtre s'il y en a un.

        Le modèle vu par la vue est le proxy de filtrage : ses numéros de ligne
        ne sont pas ceux de la grille. Écrire sans repasser par `mapToSource`
        aurait posé le code sur l'habitat d'une autre ligne dès qu'un filtre est
        actif — soit exactement quand on corrige une détermination en série.
        """
        source = model
        row = index.row()
        if hasattr(model, "mapToSource"):
            row = model.mapToSource(index).row()
            source = model.sourceModel()
        if hasattr(source, "definir_par_cle"):
            source.definir_par_cle(row, ch.HABITAT, "cd_hab", cd_hab)


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


def _libelle_corresp(entree):
    """« 41.112 — Hêtraies montagnardes à Luzule », ou le code seul."""
    code = entree.get("code") or "?"
    nom = entree.get("nom")
    return "%s — %s" % (code, nom) if nom else code


def _correspondance_choisie(edit):
    """{cd_hab, code, nom} de la proposition retenue, ou None si le champ est vide.

    None vaut RETRAIT : c'est le seul moyen d'enlever en masse une correspondance
    posée par erreur. Un champ où l'on a tapé sans rien retenir dans la liste ne
    vaut pas non plus une correspondance — un code sans `cd_hab` ne se raccorde à
    rien.
    """
    item = edit.item_choisi or {}
    if not edit.text().strip() or not item.get("cd_hab"):
        return None
    return {
        "cd_hab": int(item["cd_hab"]),
        "code": (item.get("lb_code") or "").strip(),
        "nom": corresp.nom_habref(item.get("search_name")),
    }


class AppliquerDialog(QDialog):
    """Choisir les champs à modifier sur les lignes sélectionnées.

    Chaque champ a une case « modifier » décochée : sans elle, ouvrir la fenêtre
    et valider écraserait tout avec des valeurs vides.

    Les champs restent **saisissables** et c'est la saisie qui coche la case.
    Les griser tant que la case n'était pas cochée se retournait contre le champ
    le plus utile de la fenêtre : « Nom cité » n'est pas une simple ligne de
    texte mais un bloc HABREF (typologie + recherche), qu'on ne lit pas comme un
    champ désactivé. On cliquait dedans, on tapait, rien ne se passait — et la
    saisie groupée du syntaxon paraissait ne pas fonctionner.
    """

    def __init__(self, contexte, nb_lignes, parent=None, cd_habs=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier les lignes sélectionnées")
        self.contexte = contexte
        # `cd_hab` des lignes visées. Quand elles décrivent TOUTES le même
        # habitat — le cas d'une mosaïque, où trente polygones voisins
        # portent la même liste — on peut proposer ses correspondances au
        # lieu d'un champ de recherche vide. Sélection hétérogène : on ne
        # propose rien, car une correspondance juste pour l'un serait
        # fausse pour l'autre.
        self._cd_habs = set(cd_habs or ())
        self._candidats = None  # résolus à la demande, une seule fois
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
        # Deux sections plutôt qu'un suffixe « (station) » / « (habitat) » sur
        # chaque ligne : le suffixe était répété une trentaine de fois, élargissait
        # d'autant la colonne des libellés, et se doublait pour les champs qui
        # portent déjà leur niveau dans leur nom (« Enjeu (habitat) (habitat) »).
        for niveau, titre in (
            (ch.STATION, "Champs de la station — appliqués à tous ses habitats"),
            (ch.HABITAT, "Champs de l'habitat — appliqués aux lignes visées"),
        ):
            form.addRow(self._entete_section(titre))
            for champ in ch.modifiables_en_masse(niveau):
                case = QCheckBox()
                case.setToolTip(
                    "Cochez pour appliquer ce champ ; saisir une valeur le coche "
                    "tout seul."
                )
                widget = self._widget(champ)
                self._cocher_a_la_saisie(case, widget)
                if isinstance(widget, HabrefLineEdit) and champ.stockage != ch.CORRESP:
                    # Filtre de recherche, pas une valeur à appliquer : sa ligne
                    # n'a donc pas de case à cocher. Réservé au NOM CITÉ, dont la
                    # typologie est libre : un champ de correspondance a déjà la
                    # sienne, et lui en proposer une autre n'aurait aucun sens.
                    form.addRow("Typologie", self._combo_typologie(widget))
                rang = QWidget()
                box = QHBoxLayout(rang)
                box.setContentsMargins(0, 0, 0, 0)
                box.addWidget(case)
                box.addWidget(widget, 1)
                form.addRow(_libelle_court(champ), rang)
                self._editeurs[(champ.niveau, champ.cle)] = (case, widget, champ)
        self._lier_habref()
        # Qt dimensionne une liste déroulante sur son entrée la PLUS LONGUE :
        # une seule nomenclature réclamait 611 px, le contenu 918 px, et la
        # fenêtre s'ouvrait avec un ascenseur HORIZONTAL sur des champs pourtant
        # courts. Le champ replié est borné, le menu déroulant reste lisible.
        # Plus court qu'au formulaire : chaque ligne porte ici, en plus, sa case
        # à cocher et un libellé qui nomme le champ pour les deux niveaux.
        borner_largeur_combos(interieur, caracteres=self.LARGEUR_COMBO)
        # Une trentaine de champs dans un ascenseur : c'est le cas type où la
        # molette modifie des valeurs pendant qu'on cherche un champ plus bas.
        self._filtre_molette = proteger_du_defilement(interieur)
        ascenseur = QScrollArea()
        ascenseur.setWidgetResizable(True)
        ascenseur.setFrameShape(QFrame.Shape.NoFrame)  # cf. `rendre_defilant`
        ascenseur.setWidget(interieur)
        layout.addWidget(ascenseur, 1)

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        layout.addWidget(boutons)

    #: Largeur des listes déroulantes, en caractères (cf. `dialog_size`). Choisie
    #: pour que le contenu tienne dans `TAILLE_VOULUE` sans ascenseur horizontal,
    #: ascenseur vertical déduit — c'est lui qui rogne les derniers pixels.
    LARGEUR_COMBO = 16
    #: Taille d'ouverture souhaitée, bornée ensuite à l'écran.
    TAILLE_VOULUE = (520, 620)

    def showEvent(self, event):
        super().showEvent(event)
        ajuster_a_l_ecran(self, *self.TAILLE_VOULUE)

    @staticmethod
    def _entete_section(titre):
        """Titre de section, en pleine largeur du formulaire."""
        label = QLabel(titre)
        label.setWordWrap(True)
        label.setStyleSheet("font-weight: 600; margin-top: 6px;")
        return label

    def _widget(self, champ):
        if champ.type == ch.OBSERVATEURS:
            return _ObservateursEdit(self.contexte.observers)
        if (champ.niveau, champ.cle) == (ch.HABITAT, "nom_cite"):
            # Choisir un habitat, pas taper un nom : le code suit automatiquement.
            # La ligne de saisie SEULE (pas le bloc complet du formulaire) : son
            # bloc porte sa propre colonne de libellés imbriquée, qui imposait à
            # elle seule la largeur minimale de toute la fenêtre.
            return HabrefLineEdit(
                habref_search=self.contexte.habref_search,
                typo_names=dict(self.contexte.typologies),
                cd_typo=self.contexte.cd_typo,
                catalogue=SANS_CATALOGUE,  # cf. `_creer_editeur`
            )
        if champ.stockage == ch.CORRESP:
            candidats = self._candidats_corresp(champ.cle)
            if candidats:
                # Comme au formulaire : on CHOISIT, on ne tape pas un code. Un
                # botaniste connaît son alliance, pas son code EUNIS.
                widget = QComboBox()
                widget.addItem("— retirer la correspondance —", None)
                for entree in candidats:
                    widget.addItem(_libelle_corresp(entree), entree)
                widget.setCurrentIndex(-1)
                return widget
            # Sélection hétérogène, ou aucune proposition connue : recherche
            # libre, bornée à la typologie du champ. Le cd_typo vient de la liste
            # du serveur, jamais d'un numéro codé en dur.
            cd_typo = {nom: cd for cd, nom in self.contexte.typologies}.get(champ.cle)
            edit = HabrefLineEdit(
                habref_search=self.contexte.habref_search, cd_typo=cd_typo,
                catalogue=SANS_CATALOGUE,
            )
            edit.setPlaceholderText("Tapez un nom ou un code… (vide = retirer)")
            return edit
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

    def _candidats_corresp(self, typologie):
        """Correspondances proposables pour la sélection, ou [] si on ne peut pas.

        Il faut que les lignes visées décrivent le MÊME habitat : proposer les
        correspondances de l'un pour les appliquer à l'autre écrirait une donnée
        fausse sur tout un lot.

        Deux sources, comme au formulaire : le catalogue de l'ANA s'il connaît cet
        habitat, sinon les correspondances que HABREF publie dans sa fiche. La
        seconde manquait ici, et un habitat déterminé hors catalogue —
        « Eleocharito-Sagittarion », par exemple — n'avait qu'un champ de
        recherche vide, alors que le référentiel avait la réponse.
        """
        if len(self._cd_habs) != 1:
            return []
        cd_hab = next(iter(self._cd_habs))
        if self._candidats is None:
            self._candidats = self._resoudre_candidats(cd_hab)
        return self._candidats.get(typologie) or []

    def _resoudre_candidats(self, cd_hab):
        """{typologie: [candidats]} pour cet habitat. Un seul appel réseau."""
        alliance = corresp.catalogue().par_determination(cd_hab)
        if alliance is not None:
            return {cle: alliance.candidats(cle)
                    for cle, _lib, _court in TYPOLOGIES_CORRESPONDANCE}
        if self.contexte.habref_detail is None:
            return {}
        try:
            fiche = self.contexte.habref_detail(cd_hab)
        except Exception:  # noqa: BLE001 - l'édition doit rester possible
            return {}
        return corresp.candidats_habref(fiche, dict(self.contexte.typologies))

    def _combo_typologie(self, edit):
        """Menu de typologie qui cible la recherche HABREF de `edit`."""
        combo = QComboBox()
        combo.addItem("Toutes les typologies", None)
        for cd_typo, nom in self.contexte.typologies:
            combo.addItem(nom, cd_typo)
        position = combo.findData(self.contexte.cd_typo)
        if position >= 0:  # typologie de la dernière saisie
            combo.setCurrentIndex(position)
        combo.currentIndexChanged.connect(
            lambda _i: edit.definir_typologie(combo.currentData())
        )
        combo.setEnabled(self.contexte.habref_search is not None)
        return combo

    @staticmethod
    def _cocher_a_la_saisie(case, widget):
        """Cocher « modifier » dès que l'utilisateur touche au champ.

        On ne relie que des signaux d'origine UTILISATEUR (`textEdited`,
        `activated`) là où c'est possible : `textChanged` ou `currentIndexChanged`
        se déclenchent aussi au remplissage du formulaire, ce qui cocherait tout
        à l'ouverture — et vider les 40 lignes sélectionnées à la validation.
        """
        cocher = lambda *_args: case.setChecked(True)  # noqa: E731
        if isinstance(widget, HabrefLineEdit):
            widget.textEdited.connect(cocher)
            widget.habitat_choisi.connect(cocher)
            return
        if isinstance(widget, _ObservateursEdit):
            widget.itemChanged.connect(cocher)
            return
        if isinstance(widget, QComboBox):
            widget.activated.connect(cocher)
            return
        if isinstance(widget, QDateEdit):
            widget.dateChanged.connect(cocher)
            return
        if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
            widget.valueChanged.connect(cocher)
            return
        if isinstance(widget, QLineEdit):
            widget.textEdited.connect(cocher)

    def _lier_habref(self):
        """Un habitat choisi renseigne le nom ET le code, et coche les deux cases.

        Sans cela, l'utilisateur pousserait un nom sur 40 habitats en laissant
        leur cd_hab pointer sur l'ancienne détermination.
        """
        nom = self._editeurs.get((ch.HABITAT, "nom_cite"))
        code = self._editeurs.get((ch.HABITAT, "cd_hab"))
        if not nom or not code or not isinstance(nom[1], HabrefLineEdit):
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
            if champ.stockage == ch.CORRESP and isinstance(widget, QComboBox):
                entree = widget.currentData()
                valeur = ({"cd_hab": entree["cd_hab"], "code": entree.get("code"),
                           "nom": entree.get("nom")} if entree else None)
            elif champ.stockage == ch.CORRESP:
                # Le triplet complet : le code identifie, le libellé nourrit la
                # légende des cartes, le cd_hab fait autorité. Champ laissé vide
                # = retirer la correspondance, ce que `champs.ecrire` sait faire.
                valeur = _correspondance_choisie(widget)
            elif isinstance(widget, _ObservateursEdit):
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

    #: Nombre de stations à partir duquel la base est copiée avant écriture.
    SEUIL_SAUVEGARDE = 5
    #: Nombre de copies préalables conservées (les plus anciennes sont purgées).
    SAUVEGARDES_CONSERVEES = 5

    def __init__(self, db, stations, contexte, layers=None, logger=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OccHab — Stations et habitats")
        self.db = db
        self.logger = logger
        self.contexte = contexte
        self.layers = layers  # StationLayerManager : sélection carte ↔ table
        self.grille = Grille(self.contexte.poser_libelles_habref(stations))
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

        # Sortir la table vers un tableur est le seul moyen de la RELIRE
        # confortablement : trier sur trois colonnes, surligner, imprimer. Le
        # bouton porte les trois portées plutôt qu'un raccourci à deviner.
        self.btn_copier = QToolButton()
        self.btn_copier.setText("Copier")
        self.btn_copier.setToolTip(
            "Copier dans le presse-papiers, prêt à coller dans un tableur."
        )
        self.btn_copier.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_copier)
        self.act_copier_selection = menu.addAction("Copier les lignes sélectionnées")
        self.act_copier_selection.setShortcut(QKeySequence.StandardKey.Copy)
        self.act_copier_selection.triggered.connect(self.copier_selection)
        self.act_copier_cellule = menu.addAction("Copier la cellule")
        self.act_copier_cellule.triggered.connect(self.copier_cellule)
        menu.addSeparator()
        act_tout = menu.addAction("Copier tout le tableau (avec en-têtes)")
        act_tout.triggered.connect(self.copier_tout)
        self.btn_copier.setMenu(menu)
        barre.addWidget(self.btn_copier)
        layout.addLayout(barre)

        self.table = QTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        # Pas d'alternance ligne à ligne : c'est la STATION qui est teintée une
        # sur deux (cf. `_TEINTE_LIGNE`), sans quoi les deux rythmes se
        # contrarient et une mosaïque de trois habitats paraît en compter six.
        self.table.setAlternatingRowColors(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu_contextuel)
        # Le raccourci vit sur la TABLE : posé sur le dialogue, il aurait volé
        # le Ctrl+C d'une cellule en cours d'édition, où il doit copier le texte
        # sélectionné et rien d'autre.
        copier = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        copier.setContext(Qt.ShortcutContext.WidgetShortcut)
        copier.activated.connect(self.copier_selection)
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
        self.act_copier_selection.setEnabled(bool(nb))
        self.act_copier_selection.setText(
            "Copier la ligne sélectionnée" if nb == 1
            else "Copier les %d lignes sélectionnées" % nb if nb
            else "Copier les lignes sélectionnées"
        )

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
    # ------------------------------------------------------------- copie
    def copier_selection(self):
        """Les lignes sélectionnées dans le presse-papiers, sans en-têtes.

        Sans en-têtes : c'est le geste attendu d'un Ctrl+C, et on colle le plus
        souvent sous un tableau qui en a déjà. « Copier tout » les ajoute.
        """
        rangs = self._rangs_selectionnes()
        if not rangs:
            self._prevenir("Sélectionnez au moins une ligne à copier.")
            return
        self._copier(tsv([self._valeurs(rang) for rang in rangs]),
                     "%d ligne(s) copiée(s). Collez dans votre tableur (Ctrl+V)."
                     % len(rangs))

    def copier_cellule(self):
        """La seule cellule courante, TELLE QUELLE.

        Sans échappement, contrairement aux copies de lignes : une cellule
        seule se recolle le plus souvent dans un champ de saisie — un nom cité
        à reprendre, un cd_hab à vérifier — où des guillemets de convention
        seraient à effacer à la main.
        """
        index = self.table.currentIndex()
        if not index.isValid():
            self._prevenir("Cliquez d'abord dans une cellule.")
            return
        self._copier(self._texte(index), "Cellule copiée.")

    def copier_tout(self):
        """Tout ce que la table AFFICHE, en-têtes comprises.

        Ce que la table affiche, donc filtré et trié comme à l'écran : copier
        les 400 lignes du jeu de données quand l'écran n'en montre que douze
        serait une surprise désagréable.
        """
        lignes = [self._entetes()]
        lignes += [self._valeurs(rang) for rang in range(self.proxy.rowCount())]
        if len(lignes) == 1:
            self._prevenir("Le tableau est vide (filtres en cours ?).")
            return
        self._copier(tsv(lignes),
                     "Tableau copié : %d ligne(s) et %d colonne(s). Collez dans "
                     "votre tableur (Ctrl+V)." % (len(lignes) - 1, len(lignes[0])))

    def _copier(self, texte, message):
        QApplication.clipboard().setText(texte)
        self.label_etat.setText(message)

    def _prevenir(self, message):
        self.label_etat.setText(message)

    def _colonnes_visibles(self):
        """Colonnes affichées, dans leur ordre à l'écran."""
        entete = self.table.horizontalHeader()
        return [
            entete.logicalIndex(position)
            for position in range(entete.count())
            if not entete.isSectionHidden(entete.logicalIndex(position))
        ]

    def _entetes(self):
        return [self.colonnes[colonne].libelle
                for colonne in self._colonnes_visibles()]

    def _valeurs(self, rang):
        """Textes affichés d'une ligne du proxy, colonnes dans l'ordre écran."""
        return [self._texte(self.proxy.index(rang, colonne))
                for colonne in self._colonnes_visibles()]

    @staticmethod
    def _texte(index):
        valeur = index.data(Qt.ItemDataRole.DisplayRole)
        return "" if valeur is None else str(valeur)

    def _rangs_selectionnes(self):
        """Rangs proxy des lignes sélectionnées, dans l'ordre de l'écran."""
        return sorted({i.row() for i in self.table.selectionModel().selectedIndexes()})

    def _menu_contextuel(self, position):
        index = self.table.indexAt(position)
        if index.isValid():
            self.table.setCurrentIndex(index)
        menu = QMenu(self.table)
        action_cellule = menu.addAction("Copier la cellule")
        action_cellule.setEnabled(index.isValid())
        action_cellule.triggered.connect(self.copier_cellule)
        nb = len(self._rangs_selectionnes())
        action_lignes = menu.addAction(
            "Copier la ligne sélectionnée" if nb == 1
            else "Copier les %d lignes sélectionnées" % nb
        )
        action_lignes.setEnabled(bool(nb))
        action_lignes.triggered.connect(self.copier_selection)
        menu.addSeparator()
        menu.addAction("Copier tout le tableau (avec en-têtes)").triggered.connect(
            self.copier_tout
        )
        menu.exec(self.table.viewport().mapToGlobal(position))

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
        self.grille = Grille(self.contexte.poser_libelles_habref(stations))
        self._appliquer_jeu_colonnes()  # reconstruit modèle, proxy et connexions
        return True

    def appliquer_a_la_selection(self):
        lignes = self._lignes_selectionnees()
        if not lignes:
            QMessageBox.information(self, "OccHab", "Sélectionnez d'abord des lignes.")
            return
        cd_habs = {(ligne.habitat or {}).get("cd_hab") for ligne in lignes}
        dialogue = AppliquerDialog(self.contexte, len(lignes), self,
                                   cd_habs={c for c in cd_habs if c})
        if not dialogue.exec():
            return
        valeurs = dialogue.valeurs()
        if not valeurs:
            QMessageBox.information(self, "OccHab", "Aucun champ coché : rien à appliquer.")
            return
        apercu = self.grille.previsualiser(lignes, valeurs)
        # Ne demander confirmation que si des valeurs déjà renseignées seraient
        # remplacées : c'est la seule perte possible. Sans écrasement, la
        # modification reste en mémoire, apparaît en orangé, et « Enregistrer »
        # est de toute façon nécessaire — confirmer n'apportait rien.
        if apercu["ecrasements"] and not self._confirmer(valeurs, apercu):
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
        if not self._verifier_mesures():
            return
        if not self._verifier_recouvrements():
            return

        # Une station validée sur laquelle on est revenu redevient un brouillon.
        self.grille.retrograder_statuts()

        sauvegarde = (self._sauvegarder_base()
                      if len(modifiees) >= self.SEUIL_SAUVEGARDE else None)
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
            # Le chemin complet part au journal : on n'en a besoin qu'au moment
            # de restaurer, et le dossier s'ouvre depuis « Base locale… ».
            message += ("\nUne copie de la base a été faite avant l'opération "
                        "(menu « Base locale… »).")
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

    def _verifier_mesures(self):
        """Bloquer un couple altitude/profondeur inversé avant l'enregistrement.

        Ces champs se saisissent cellule par cellule, donc hors du formulaire et
        de sa validation. Côté GeoNature les contraintes `t_stations_altitude_max`
        et `_depth_max` rejettent la station avec une erreur 500 illisible : la
        synchro échouerait sans que rien n'explique pourquoi.
        """
        fautives = []
        for station in self.grille.modifications():
            for probleme in mesures_incoherentes(station):
                fautives.append((station, probleme))
        if not fautives:
            return True
        apercu = "\n".join(
            "• %s : %s" % (s.get("station_name") or "station %s" % s.get("id"), p)
            for s, p in fautives[:10]
        )
        reste = "\n… et %d autre(s)." % (len(fautives) - 10) if len(fautives) > 10 else ""
        QMessageBox.warning(
            self, "Mesures incohérentes",
            "%d mesure(s) ont un minimum supérieur au maximum :\n\n%s%s\n\n"
            "GeoNature les refuserait à la synchronisation. Corrigez-les avant "
            "d'enregistrer." % (len(fautives), apercu, reste),
        )
        return False

    def _verifier_recouvrements(self):
        """Avertir si un polygone ne totalise pas 100 % (exigence N2000).

        Avertissement, pas blocage : une cartographie en cours de saisie est
        légitimement incomplète.

        Restreint aux stations dont un HABITAT a changé : le recouvrement est un
        champ d'habitat, modifier un champ de station ne peut pas en altérer la
        somme. Sans ce filtre, changer « Nature de l'observation » faisait
        ressortir des stations incomplètes de longue date, sans aucun rapport
        avec le lot en cours.
        """
        concernees = [station for station in self.grille.modifications()
                      if self.grille.habitats_modifies(station)]
        fautives = self.grille.recouvrements_incoherents(concernees)
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
        dizaines de stations ; elle coûte une copie de fichier. En dessous de
        `SEUIL_SAUVEGARDE` stations on s'en passe : refaire la main quelques
        corrections ne justifie pas une copie complète, et l'édition unitaire
        depuis le formulaire n'en fait aucune non plus.
        """
        try:
            cible = self.db.db_path.with_name(
                "%s.avant-lot-%s.db" % (self.db.db_path.stem,
                                        datetime.now().strftime("%Y%m%d-%H%M%S"))
            )
            shutil.copy2(str(self.db.db_path), str(cible))
            if self.logger:
                self.logger.info("Sauvegarde préalable : %s", cible)
            self._purger_sauvegardes()
            return str(cible)
        except OSError as exc:
            if self.logger:
                self.logger.warning("Sauvegarde préalable impossible : %s", exc)
            return None

    def _purger_sauvegardes(self):
        """Ne garder que les dernières copies préalables.

        Rien ne les supprimait : une copie de la base entière s'accumulait à
        chaque enregistrement, sans limite — alors que le journal de synchro et
        les stations anciennes ont, eux, leur rétention.
        """
        try:
            motif = "%s.avant-lot-*.db" % self.db.db_path.stem
            copies = sorted(self.db.db_path.parent.glob(motif))
            for ancienne in copies[:-self.SAUVEGARDES_CONSERVEES]:
                ancienne.unlink()
                if self.logger:
                    self.logger.info("Ancienne sauvegarde supprimée : %s", ancienne)
        except OSError as exc:
            if self.logger:
                self.logger.warning("Purge des sauvegardes impossible : %s", exc)

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
        # Indispensable : c'est `QDialog.closeEvent` qui appelle `reject()`, donc
        # qui émet `finished`. Un simple `event.accept()` masquait la fenêtre sans
        # prévenir personne : le dock gardait sa référence et le bouton
        # « Tableau » ne rouvrait plus rien.
        super().closeEvent(event)
