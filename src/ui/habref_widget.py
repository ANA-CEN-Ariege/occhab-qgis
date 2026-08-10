# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Champ « nom cité » avec autocomplétion HABREF et filtre par typologie.

Extrait du formulaire habitat pour être partagé avec l'édition en masse et les
**cellules de la table attributaire** : le même choix d'habitat doit se faire de
la même façon aux trois endroits, et remplir **cd_hab ET nom cité** ensemble —
les dissocier laisserait un code qui ne correspond plus au nom.

Deux niveaux, pour tenir dans une cellule comme dans un formulaire :

- `HabrefLineEdit` — la **ligne de saisie** seule, avec sa liste de propositions.
  C'est tout ce qu'une cellule de tableau peut accueillir ;
- `HabrefSearchEdit` — la même ligne, précédée du menu **Typologie** et suivie
  d'une ligne d'état, pour les formulaires.

Trois défauts de la version précédente sont corrigés ici :

1. **La recherche échouait en silence.** Une erreur d'API était avalée
   (`except: results = []`) : l'utilisateur voyait « l'autocomplétion ne marche
   pas », sans le moindre indice. Le motif de l'échec est désormais affiché.
2. **Hors connexion, la ligne « Typologie » disparaissait** et taper ne faisait
   rien. Le champ reste visible mais désactivé, avec la raison.
3. `QStandardItemModel.clear()` remet le modèle à zéro (colonnes comprises) et
   met le QCompleter qui l'observe dans un état incertain. On vide désormais les
   lignes sans réinitialiser le modèle.
"""
from qgis.PyQt.QtCore import QModelIndex, QPoint, QRect, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QCompleter,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from ..processing import correspondances as corresp
from .dialog_size import ecran_de

MIN_RECHERCHE = 3  # en deçà, la recherche serveur ne discrimine rien
#: Marque des propositions venant du catalogue ANA. Elles précèdent celles de
#: HABREF : ce sont les déterminations que les botanistes emploient réellement,
#: et une partie d'entre elles n'existe nulle part ailleurs.
PREFIXE_CATALOGUE = "★ Catalogue ANA"
_DELAI_MS = 300  # laisser finir de taper avant d'interroger le serveur
#: Largeur maximale du menu de propositions. Un libellé HABREF préfixé de sa
#: typologie (« Habitats_naturels_et_semi-naturels_de_La_Réunion_(2017) 1.4.1.4 -
#: Pelouse post-pionnière… ») réclame plus de 1000 px : le laisser décider, c'est
#: un menu qui sort de l'écran par la droite.
LARGEUR_POPUP_MAX = 620
_MARGE_POPUP = 40  # cadre + ascenseur vertical du menu


class HabrefLineEdit(QLineEdit):
    """Ligne de saisie du nom cité, assistée par HABREF (utilisable en cellule).

    Émet `habitat_choisi(cd_hab, nom)` quand une proposition est retenue, et
    `etat_change(texte, detail)` pour qui veut afficher la raison d'une recherche
    infructueuse (le formulaire le fait ; une cellule de tableau, non).

    `nom_choisi` / `cd_choisi` retiennent la dernière proposition retenue :
    l'appelant peut ainsi écrire le nom **et** le code sans relire le texte du
    champ, que le complèteur peut encore être en train de réécrire.
    """

    habitat_choisi = pyqtSignal(int, str)
    #: Émis EN PLUS de `habitat_choisi` quand la proposition retenue vient du
    #: catalogue ANA : elle apporte une détermination et ses correspondances, que
    #: `habitat_choisi` (cd_hab + nom) ne sait pas transporter. Les appelants qui
    #: n'ont besoin que du code — une cellule de tableau — l'ignorent.
    alliance_choisie = pyqtSignal(object)
    etat_change = pyqtSignal(str, str)

    def __init__(self, habref_search=None, typo_names=None, cd_typo=None,
                 catalogue=None, parent=None):
        super().__init__(parent)
        self._habref_search = habref_search
        self._typo_names = dict(typo_names or {})
        self._cd_typo = cd_typo
        # Le catalogue est local : il répond même hors connexion, et c'est le
        # seul endroit où se trouvent les 43 alliances absentes de HABREF.
        self._catalogue = catalogue if catalogue is not None else corresp.catalogue()
        self._pending = ""
        self.nom_choisi = None
        self.cd_choisi = None
        #: Proposition HABREF retenue, telle que l'API l'a rendue. Le signal ne
        #: transporte que le code et le nom ; `lb_code` n'y tient pas, et c'est
        #: lui qu'une correspondance doit afficher (« G1.62 », pas un cd_hab).
        self.item_choisi = None
        self.alliance_choisie_valeur = None
        if habref_search is None and not len(self._catalogue):
            self.setPlaceholderText("Nom de l'habitat (saisie libre)")
            self._etat(
                "Recherche HABREF indisponible hors connexion — saisissez le nom "
                "et le code à la main."
            )
            return
        if habref_search is None:
            # Hors connexion, le catalogue ANA reste interrogeable : il est sur
            # le disque. C'est même là qu'il rend le plus de services — sur le
            # terrain, sans réseau.
            self.setPlaceholderText("Tapez le nom de l'alliance (catalogue ANA)…")
        else:
            self.setPlaceholderText("Tapez le nom (ou code) de l'habitat…")
        self._modele = QStandardItemModel(0, 1, self)
        completer = QCompleter(self._modele, self)
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.activated[QModelIndex].connect(self._on_choisi)
        self.setCompleter(completer)
        self.textEdited.connect(self._on_edite)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DELAI_MS)
        self._timer.timeout.connect(self._rechercher)

    @property
    def catalogue(self):
        """Catalogue ANA effectivement interrogé (jamais None, parfois vide)."""
        return self._catalogue

    def definir_typologie(self, cd_typo):
        """Restreindre la recherche à une typologie (None = toutes)."""
        self._cd_typo = cd_typo

    def _etat(self, texte, detail=None):
        self.etat_change.emit(texte or "", detail or "")

    def _on_edite(self, texte):
        # On relance la recherche sans toucher au cd_hab déjà retenu : corriger
        # une faute de frappe ne doit pas effacer le code choisi.
        self._pending = (texte or "").strip()
        if len(self._pending) >= MIN_RECHERCHE:
            self._timer.start()
        else:
            self._etat("Tapez au moins %d caractères." % MIN_RECHERCHE)

    def _rechercher(self):
        query = self._pending
        if len(query) < MIN_RECHERCHE:
            return

        # Le catalogue d'abord : il est local (donc instantané et disponible hors
        # connexion) et porte les déterminations que les botanistes emploient
        # réellement. Une recherche HABREF en échec ne doit pas l'emporter avec
        # elle — d'où sa constitution AVANT l'appel réseau.
        alliances = [
            alliance for alliance in self._catalogue.chercher(query)
            if alliance.est_saisissable
        ]

        echec = None
        resultats = []
        if self._habref_search is not None:
            try:
                resultats = self._habref_search(query, cd_typo=self._cd_typo) or []
            except Exception as exc:  # noqa: BLE001 - la saisie doit rester possible
                echec = str(exc)

        # Vider les LIGNES sans réinitialiser le modèle : `clear()` remettrait
        # aussi les colonnes à zéro et déstabiliserait le QCompleter.
        if self._modele.rowCount():
            self._modele.removeRows(0, self._modele.rowCount())
        for alliance in alliances:
            self._modele.appendRow(self._ligne_alliance(alliance))
        for item in resultats:
            self._modele.appendRow(self._ligne(item))

        if self._modele.rowCount():
            self._etat(
                "Recherche HABREF en échec — propositions du catalogue seulement."
                if echec else "",
                echec,
            )
            self._afficher_propositions()
        elif echec:
            self._etat("Recherche HABREF en échec — saisie manuelle possible.", echec)
        else:
            self._etat("Aucun habitat trouvé pour « %s »." % query)

    # ------------------------------------------------- menu de propositions
    def _afficher_propositions(self):
        """Dérouler le menu SOUS le champ, à une largeur maîtrisée.

        `complete()` sans argument laisse Qt décider : le menu se plaçait de
        travers et débordait de l'écran, les propositions HABREF étant bien plus
        longues que le champ. En lui passant un rectangle, on fixe nous-mêmes le
        point d'ancrage (le bas du champ) et la largeur.
        """
        completer = self.completer()
        popup = completer.popup()
        # Sans suivi de la souris, la ligne survolée ne se surligne pas : Qt
        # n'active pas `mouseTracking` sur le menu d'un QCompleter, à la
        # différence de celui d'une liste déroulante.
        popup.setMouseTracking(True)
        completer.complete(QRect(0, 0, self._largeur_popup(popup), self.height()))

    def _largeur_popup(self, popup):
        """Assez large pour lire une proposition, jamais au-delà de l'écran."""
        dispo = LARGEUR_POPUP_MAX
        ecran = ecran_de(self)
        if ecran is not None:
            depuis = self.mapToGlobal(QPoint(0, 0)).x()
            dispo = min(dispo, max(0, ecran.availableGeometry().right() - depuis))
        voulue = popup.sizeHintForColumn(0) + _MARGE_POPUP
        return max(self.width(), min(voulue, dispo))

    def _ligne(self, item):
        # `search_name` contient déjà « code - nom » (ex. « 41.2 - Chênaies »).
        nom = item.get("search_name") or item.get("lb_code") or str(item.get("cd_hab"))
        typo = item.get("lb_nom_typo") or self._typo_names.get(item.get("cd_typo"), "")
        texte = ("%s %s" % (typo, nom)).strip()
        ligne = QStandardItem(texte)
        # Le libellé complet reste lisible même quand le menu doit l'élider.
        ligne.setToolTip(texte)
        ligne.setData(item, Qt.ItemDataRole.UserRole)
        return ligne

    def _ligne_alliance(self, alliance):
        """Proposition venant du catalogue ANA, marquée comme telle."""
        texte = "%s · %s" % (PREFIXE_CATALOGUE, alliance.libelle())
        ligne = QStandardItem(texte)
        ligne.setToolTip(
            "%s\nClasse : %s%s" % (
                texte, alliance.classe or "—",
                "\nCode emprunté : ce nom d'alliance est absent de HABREF."
                if alliance.est_ancree else "",
            )
        )
        ligne.setData(alliance, Qt.ItemDataRole.UserRole)
        return ligne

    def _on_choisi(self, index):
        data = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, corresp.Alliance):
            self._retenir_alliance(data)
            return
        if not isinstance(data, dict):
            return
        nom = data.get("search_name") or ""
        self.nom_choisi = nom
        self.item_choisi = data
        # Ce choix-ci ne vient PAS du catalogue : oublier l'alliance retenue
        # précédemment, sinon l'appelant croirait qu'une alliance suit encore.
        self.alliance_choisie_valeur = None
        self._etat("")
        # Le complèteur va écrire le libellé affiché (préfixé de la typologie) :
        # on repasse derrière lui pour ne garder que le nom HABREF. En cellule,
        # l'éditeur peut avoir été refermé entre-temps par la validation — d'où
        # le garde-fou, sans lequel Qt lèverait sur un objet C++ détruit.
        def _poser():
            try:
                self.setText(nom)
            except RuntimeError:  # pragma: no cover - éditeur déjà refermé
                pass

        QTimer.singleShot(0, _poser)
        cd_hab = data.get("cd_hab")
        if cd_hab is not None:
            try:
                self.cd_choisi = int(cd_hab)
            except (TypeError, ValueError):
                return
            self.habitat_choisi.emit(self.cd_choisi, nom)

    def _retenir_alliance(self, alliance):
        """Retenir une proposition du catalogue : nom d'alliance et cd_hab à poser.

        Le nom cité devient le **nom d'alliance**, pas le libellé du code : c'est
        la détermination du botaniste. Quand le code n'est qu'une ancre, cette
        distinction est tout ce qui reste pour dire ce qui a réellement été
        déterminé.

        `habitat_choisi` est émis comme pour HABREF — une cellule de tableau n'a
        rien à savoir du catalogue — et `alliance_choisie` en plus, pour qui sait
        enregistrer la détermination et ses correspondances.
        """
        self.nom_choisi = alliance.nom
        self.alliance_choisie_valeur = alliance
        self.item_choisi = None
        self._etat("")

        def _poser():
            try:
                self.setText(alliance.nom)
            except RuntimeError:  # pragma: no cover - éditeur déjà refermé
                pass

        QTimer.singleShot(0, _poser)
        self.cd_choisi = alliance.cd_hab_a_poser
        self.habitat_choisi.emit(self.cd_choisi, alliance.nom)
        self.alliance_choisie.emit(alliance)


class HabrefSearchEdit(QWidget):
    """Saisie du nom cité, assistée par HABREF, avec filtre de typologie.

    `habitat_choisi(cd_hab, nom)` est émis quand une proposition est retenue, et
    `alliance_choisie(alliance)` en plus quand elle vient du catalogue ANA.
    """

    habitat_choisi = pyqtSignal(int, str)
    alliance_choisie = pyqtSignal(object)

    def __init__(self, habref_search=None, typologies=None, libelle="Nom cité *",
                 cd_typo=None, catalogue=None, parent=None):
        super().__init__(parent)
        self._habref_search = habref_search
        self._typologies = typologies or []  # [(cd_typo, nom)]
        self._typo_names = dict(self._typologies)
        self._catalogue = catalogue
        self._build(libelle)
        self.definir_typologie(cd_typo)

    def definir_typologie(self, cd_typo):
        """Présélectionner une typologie (sans effet si elle n'est pas proposée)."""
        if cd_typo is None:
            return
        index = self.combo_typo.findData(cd_typo)
        if index >= 0:
            self.combo_typo.setCurrentIndex(index)

    def typologie(self):
        """cd_typo courant, ou None pour « Toutes les typologies »."""
        return self.combo_typo.currentData()

    def _build(self, libelle):
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)

        # Typologie : TOUJOURS affichée. Sa disparition hors connexion privait
        # l'utilisateur de toute explication sur l'absence d'autocomplétion.
        self.combo_typo = QComboBox()
        self.combo_typo.addItem("Toutes les typologies", None)
        for cd_typo, nom in self._typologies:
            self.combo_typo.addItem(nom, cd_typo)
        self.combo_typo.currentIndexChanged.connect(
            lambda _i: self.edit.definir_typologie(self.combo_typo.currentData())
        )
        form.addRow("Typologie", self.combo_typo)

        self.edit = HabrefLineEdit(
            habref_search=self._habref_search, typo_names=self._typo_names,
            catalogue=self._catalogue,
        )
        self.edit.etat_change.connect(self._etat)
        self.edit.habitat_choisi.connect(self.habitat_choisi)
        self.edit.alliance_choisie.connect(self.alliance_choisie)
        form.addRow(libelle, self.edit)

        self.label_etat = QLabel()
        self.label_etat.setWordWrap(True)
        self.label_etat.setStyleSheet("color: palette(mid); font-style: italic;")
        self.label_etat.setVisible(False)
        form.addRow("", self.label_etat)

        if self._habref_search is None:
            # La ligne de saisie a signalé son état hors connexion avant que le
            # label existe : on le repose ici, sans quoi le champ resterait muet
            # — le défaut même que ce composant a été écrit pour corriger. Le
            # filtre par typologie ne concerne que HABREF ; le catalogue, lui,
            # reste interrogeable, et il faut le dire plutôt que de laisser
            # croire que la saisie assistée est perdue.
            self.combo_typo.setEnabled(False)
            self._etat(
                "Recherche HABREF indisponible hors connexion — le catalogue ANA "
                "reste proposé."
                if len(self.edit.catalogue) else
                "Recherche HABREF indisponible hors connexion — saisissez le nom "
                "et le code à la main."
            )

    # ------------------------------------------------------------- état
    def _etat(self, texte, detail=None):
        self.label_etat.setText(texte or "")
        self.label_etat.setToolTip(detail or "")
        self.label_etat.setVisible(bool(texte))

    # ------------------------------------------------------------- API
    def text(self):
        return self.edit.text().strip()

    def setText(self, valeur):
        self.edit.setText(valeur or "")

    def setPlaceholderText(self, texte):
        self.edit.setPlaceholderText(texte)
