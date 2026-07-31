# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Champ « nom cité » avec autocomplétion HABREF et filtre par typologie.

Extrait du formulaire habitat pour être partagé avec l'édition en masse : le même
choix d'habitat doit se faire de la même façon aux deux endroits, et remplir
**cd_hab ET nom cité** ensemble — les dissocier laisserait un code qui ne
correspond plus au nom.

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
from qgis.PyQt.QtCore import QModelIndex, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QCompleter,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

MIN_RECHERCHE = 3  # en deçà, la recherche serveur ne discrimine rien
_DELAI_MS = 300  # laisser finir de taper avant d'interroger le serveur


class HabrefSearchEdit(QWidget):
    """Saisie du nom cité, assistée par HABREF.

    `habitat_choisi(cd_hab, nom)` est émis quand une proposition est retenue.
    """

    habitat_choisi = pyqtSignal(int, str)

    def __init__(self, habref_search=None, typologies=None, libelle="Nom cité *",
                 parent=None):
        super().__init__(parent)
        self._habref_search = habref_search
        self._typologies = typologies or []  # [(cd_typo, nom)]
        self._typo_names = dict(self._typologies)
        self._pending = ""
        self._build(libelle)

    def _build(self, libelle):
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)

        # Typologie : TOUJOURS affichée. Sa disparition hors connexion privait
        # l'utilisateur de toute explication sur l'absence d'autocomplétion.
        self.combo_typo = QComboBox()
        self.combo_typo.addItem("Toutes les typologies", None)
        for cd_typo, nom in self._typologies:
            self.combo_typo.addItem(nom, cd_typo)
        form.addRow("Typologie", self.combo_typo)

        self.edit = QLineEdit()
        form.addRow(libelle, self.edit)

        self.label_etat = QLabel()
        self.label_etat.setWordWrap(True)
        self.label_etat.setStyleSheet("color: palette(mid); font-style: italic;")
        self.label_etat.setVisible(False)
        form.addRow("", self.label_etat)

        if self._habref_search is None:
            self.combo_typo.setEnabled(False)
            self.edit.setPlaceholderText("Nom de l'habitat (saisie libre)")
            self._etat(
                "Recherche HABREF indisponible hors connexion — saisissez le nom "
                "et le code à la main."
            )
            return

        self.edit.setPlaceholderText("Tapez le nom (ou code) de l'habitat…")
        self._modele = QStandardItemModel(0, 1, self)
        completer = QCompleter(self._modele, self)
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.activated[QModelIndex].connect(self._on_choisi)
        self.edit.setCompleter(completer)
        self.edit.textEdited.connect(self._on_edite)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DELAI_MS)
        self._timer.timeout.connect(self._rechercher)

    # ------------------------------------------------------------- état
    def _etat(self, texte, detail=None):
        self.label_etat.setText(texte or "")
        self.label_etat.setToolTip(detail or "")
        self.label_etat.setVisible(bool(texte))

    # ------------------------------------------------------------- recherche
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
        if len(query) < MIN_RECHERCHE or self._habref_search is None:
            return
        cd_typo = self.combo_typo.currentData()
        try:
            resultats = self._habref_search(query, cd_typo=cd_typo) or []
        except Exception as exc:  # noqa: BLE001 - la saisie doit rester possible
            self._etat("Recherche HABREF en échec — saisie manuelle possible.", str(exc))
            return

        # Vider les LIGNES sans réinitialiser le modèle : `clear()` remettrait
        # aussi les colonnes à zéro et déstabiliserait le QCompleter.
        if self._modele.rowCount():
            self._modele.removeRows(0, self._modele.rowCount())
        for item in resultats:
            self._modele.appendRow(self._ligne(item))

        if self._modele.rowCount():
            self._etat("")
            self.edit.completer().complete()
        else:
            self._etat("Aucun habitat trouvé pour « %s »." % query)

    def _ligne(self, item):
        # `search_name` contient déjà « code - nom » (ex. « 41.2 - Chênaies »).
        nom = item.get("search_name") or item.get("lb_code") or str(item.get("cd_hab"))
        typo = item.get("lb_nom_typo") or self._typo_names.get(item.get("cd_typo"), "")
        ligne = QStandardItem(("%s %s" % (typo, nom)).strip())
        ligne.setData(item, Qt.ItemDataRole.UserRole)
        return ligne

    def _on_choisi(self, index):
        data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        nom = data.get("search_name") or ""
        # Le completer va écrire le libellé affiché (préfixé de la typologie) :
        # on repasse derrière lui pour ne garder que le nom HABREF.
        QTimer.singleShot(0, lambda: self.edit.setText(nom))
        self._etat("")
        cd_hab = data.get("cd_hab")
        if cd_hab is not None:
            try:
                self.habitat_choisi.emit(int(cd_hab), nom)
            except (TypeError, ValueError):
                pass

    # ------------------------------------------------------------- API
    def text(self):
        return self.edit.text().strip()

    def setText(self, valeur):
        self.edit.setText(valeur or "")

    def setPlaceholderText(self, texte):
        self.edit.setPlaceholderText(texte)
