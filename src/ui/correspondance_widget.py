# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Correspondances d'UN habitat, à choisir et à corriger.

Le catalogue ANA propose des correspondances, et la vue d'export sait en
recalculer depuis HABREF — mais ni l'un ni l'autre n'a toujours raison. Une
alliance se traduit différemment selon la situation, et le catalogue lui-même
porte parfois plusieurs lignes pour une même alliance (`Luzulo luzuloidis –
Fagion sylvaticae` en a quatre, qui ne diffèrent que par leurs codes). C'est au
botaniste de trancher, station par station : ce composant est l'endroit où il le
fait.

**On choisit, on ne tape pas un code.** Un botaniste qui a déterminé une alliance
ne connaît pas forcément son code CORINE ou EUNIS — lui présenter un champ de
recherche vide revient à lui demander la réponse qu'il vient chercher. Chaque
ligne est donc une **liste de choix**, garnie des correspondances que le
catalogue connaît pour cette alliance-là, **libellés compris** : « 41.112 —
Hêtraies montagnardes à Luzule » se choisit, « 41.112 » se devine. La recherche
HABREF reste accessible en dernier recours (« Autre… »).

**Rien n'est choisi à la place du botaniste.** Quand le catalogue propose
plusieurs correspondances pour une typologie, aucune n'est présélectionnée et la
ligne affiche « n propositions — à choisir ». En retenir une d'office
reviendrait à trancher en silence une question que le catalogue laisse
explicitement ouverte.

**Ce qui distingue une valeur reprise d'une valeur arbitrée.** Chaque ligne
retient d'où vient son code : `catalogue` tant qu'il est repris tel quel,
`manuel` dès que quelqu'un l'a choisi ici. La distinction n'est pas cosmétique —
c'est elle qui permet, en fin de campagne, de lister ce qui a été vérifié et ce
qui ne l'a pas été. Elle est donc affichée en clair sur chaque ligne, et pas
seulement stockée.

La recherche de secours cherche **dans sa typologie** : le champ EUNIS n'interroge
que l'EUNIS. Le `cd_typo` correspondant est résolu depuis la liste des typologies
fournie par le serveur, jamais codé en dur — les identifiants HABREF sont
nationaux, mais rien ne garantit qu'une instance les expose tous.
"""
from collections import namedtuple

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QStackedWidget,
    QToolButton,
    QWidget,
)

from ..processing import correspondances as corresp
from ..processing.referentiels import SOURCES_CORRESPONDANCE, TYPOLOGIES_CORRESPONDANCE
from .habref_widget import HabrefLineEdit

#: Catalogue vide : ces champs cherchent un CODE dans une typologie donnée, pas
#: une alliance. Y proposer le catalogue ANA n'aurait aucun sens.
_SANS_CATALOGUE = corresp.Catalogue([])

_MENTION = {
    "catalogue": "repris du catalogue",
    "habref": "proposé par HABREF",
    "manuel": "arbitré ici",
}
_AUCUNE = "— aucune —"
_AUTRE = "Autre… (chercher dans HABREF)"

_Ligne = namedtuple("_Ligne", "pile choix edit propre retour mention")


def _libelle_choix(entree):
    """« 41.112 — Hêtraies montagnardes à Luzule », ou le code seul."""
    code = entree.get("code") or "?"
    nom = entree.get("nom")
    return "%s — %s" % (code, nom) if nom else code


class CorrespondancesEdit(QWidget):
    """Une ligne par typologie : le code retenu, son origine, et de quoi le changer."""

    #: Émis à chaque modification, pour que le formulaire rafraîchisse ce qu'il
    #: affiche par ailleurs (la mention « correspondances… »).
    modifiee = pyqtSignal()

    def __init__(self, habref_search=None, typologies=None, parent=None):
        super().__init__(parent)
        self._habref_search = habref_search
        self._cd_typo = {nom: cd for cd, nom in (typologies or [])}
        self._candidats = {}  # typologie -> [{cd_hab, code, nom}] proposés
        self._valeurs = {}  # typologie -> {cd_hab, code, nom, src} retenu
        self._propre = None  # (typologie, code) de la détermination elle-même
        self._lignes = {}
        self._build()

    # -------------------------------------------------------------- montage
    def _build(self):
        grille = QGridLayout(self)
        grille.setContentsMargins(12, 0, 0, 0)
        grille.setColumnStretch(1, 1)

        for rang, (cle, libelle, _court) in enumerate(TYPOLOGIES_CORRESPONDANCE):
            grille.addWidget(QLabel(libelle), rang, 0)

            # Deux visages pour la même ligne : la liste de choix (le cas
            # courant) et, derrière « Autre… », la recherche HABREF. Une pile
            # plutôt que deux champs côte à côte, qui laisseraient croire qu'on
            # peut renseigner les deux.
            pile = QStackedWidget()
            choix = QComboBox()
            # `cle=cle` fige la typologie : sans lui, les quatre lignes
            # partageraient la dernière valeur de la boucle.
            choix.activated.connect(lambda _i, cle=cle: self._on_choix_liste(cle))
            pile.addWidget(choix)

            edit = HabrefLineEdit(
                habref_search=self._habref_search,
                cd_typo=self._cd_typo.get(cle),
                catalogue=_SANS_CATALOGUE,
            )
            edit.setPlaceholderText("Tapez un nom ou un code…")
            edit.habitat_choisi.connect(
                lambda cd, _nom, cle=cle: self._on_choix_habref(cle, cd)
            )
            pile.addWidget(edit)

            # Troisième visage : la typologie DE la détermination. Un habitat
            # déterminé en EUNIS est déjà sa propre correspondance EUNIS —
            # redemander le code reviendrait à poser une question dont la
            # réponse est le `cd_hab` lui-même.
            propre = QLabel()
            propre.setStyleSheet("color: palette(text);")
            pile.addWidget(propre)

            grille.addWidget(pile, rang, 1)

            retour = QToolButton()
            retour.setText("↩")
            retour.setToolTip("Revenir aux propositions du catalogue")
            retour.setAutoRaise(True)
            retour.setVisible(False)
            retour.clicked.connect(lambda _c=False, cle=cle: self._revenir(cle))
            grille.addWidget(retour, rang, 2)

            mention = QLabel()
            mention.setStyleSheet("color: palette(mid); font-style: italic;")
            grille.addWidget(mention, rang, 3)

            self._lignes[cle] = _Ligne(pile, choix, edit, propre, retour, mention)
            self._rafraichir(cle)

    # ------------------------------------------------------------- affichage
    def _rafraichir(self, cle):
        """Regarnir la liste et remettre la ligne dans l'état qu'elle décrit."""
        ligne = self._lignes[cle]

        # La typologie de la détermination : rien à demander, rien à choisir.
        if self._propre and self._propre[0] == cle:
            ligne.propre.setText(
                "%s — c'est la détermination elle-même" % (self._propre[1] or "ce code")
            )
            ligne.pile.setCurrentIndex(2)
            ligne.retour.setVisible(False)
            ligne.mention.setText("")
            return

        valeurs = self._valeurs.get(cle)
        candidats = self._candidats.get(cle, [])

        ligne.choix.blockSignals(True)
        try:
            ligne.choix.clear()
            ligne.choix.addItem(_AUCUNE, None)
            for entree in candidats:
                ligne.choix.addItem(_libelle_choix(entree), entree)
            if valeurs and not any(e["cd_hab"] == valeurs["cd_hab"] for e in candidats):
                # Correspondance arbitrée hors catalogue : elle doit figurer dans
                # la liste, sinon rouvrir l'habitat la ferait disparaître.
                ligne.choix.addItem(_libelle_choix(valeurs), valeurs)
            if self._habref_search is not None:
                ligne.choix.addItem(_AUTRE, _AUTRE)

            position = 0
            if valeurs:
                for index in range(ligne.choix.count()):
                    donnee = ligne.choix.itemData(index)
                    if isinstance(donnee, dict) and donnee["cd_hab"] == valeurs["cd_hab"]:
                        position = index
                        break
            ligne.choix.setCurrentIndex(position)
        finally:
            ligne.choix.blockSignals(False)

        # Sans proposition NI valeur, une liste réduite à « aucune / Autre… »
        # n'apporte rien : on met directement la recherche, qui accepte un nom
        # aussi bien qu'un code. C'est le cas courant d'une détermination HABREF
        # dont personne n'a encore établi la correspondance.
        recherche = (
            not candidats and not valeurs and self._habref_search is not None
        )
        ligne.pile.setCurrentIndex(1 if recherche else 0)
        ligne.retour.setVisible(False)
        ligne.mention.setText(self._mention(cle))

    def _mention(self, cle):
        valeurs = self._valeurs.get(cle)
        if valeurs:
            return _MENTION.get(valeurs.get("src"), "")
        candidats = self._candidats.get(cle, [])
        if len(candidats) > 1:
            # Le catalogue laisse la question ouverte : la poser, ne pas la
            # trancher à la place du botaniste.
            return "%d propositions — à choisir" % len(candidats)
        return ""

    # -------------------------------------------------------------- édition
    def _on_choix_liste(self, cle):
        """Une entrée retenue dans la liste : c'est un arbitrage, il est marqué."""
        ligne = self._lignes[cle]
        donnee = ligne.choix.currentData()
        if donnee == _AUTRE:
            ligne.pile.setCurrentIndex(1)
            ligne.retour.setVisible(True)
            ligne.edit.setFocus()
            return
        if donnee is None:
            self._valeurs.pop(cle, None)
        else:
            self._valeurs[cle] = dict(donnee, src="manuel")
        self._rafraichir(cle)
        self.modifiee.emit()

    def _on_choix_habref(self, cle, cd_hab):
        """Une correspondance trouvée dans HABREF : hors catalogue, donc arbitrée."""
        item = self._lignes[cle].edit.item_choisi or {}
        self._valeurs[cle] = {
            "cd_hab": int(cd_hab),
            "code": (item.get("lb_code") or "").strip(),
            "nom": corresp.nom_habref(item.get("search_name")),
            "src": "manuel",
        }
        self._rafraichir(cle)
        self.modifiee.emit()

    def _revenir(self, cle):
        """Refermer la recherche sans rien changer."""
        self._rafraichir(cle)

    # ------------------------------------------------------------------ API
    def definir_determination(self, typologie, code):
        """Signaler que la détermination appartient elle-même à une typologie cible.

        Un habitat déterminé en EUNIS **est** sa correspondance EUNIS : la ligne
        se remplit de son propre code et cesse de poser la question. Rien n'est
        enregistré pour autant — ce serait recopier le `cd_hab` dans la donnée,
        avec le risque que les deux divergent au premier changement.

        `typologie=None` remet toutes les lignes en jeu (détermination dans une
        typologie qui n'est pas une cible : PVF1, PVF2, Cahiers d'unités…).
        """
        cibles = {cle for cle, _libelle, _court in TYPOLOGIES_CORRESPONDANCE}
        self._propre = (typologie, code) if typologie in cibles else None
        if self._propre:
            self._valeurs.pop(self._propre[0], None)
        for cle in self._lignes:
            self._rafraichir(cle)

    def garnir(self, candidats):
        """Poser les propositions SANS toucher aux valeurs déjà retenues.

        Sert à la relecture d'un habitat enregistré : les mises en garde
        (« n propositions — à choisir ») doivent réapparaître, mais ce qui a été
        retenu ne se rejoue pas.
        """
        self._candidats = {
            cle: list((candidats or {}).get(cle) or [])
            for cle, _libelle, _court in TYPOLOGIES_CORRESPONDANCE
        }
        for cle in self._lignes:
            self._rafraichir(cle)

    def proposer(self, candidats, source="catalogue"):
        """Garnir les listes de propositions ({typologie: [{cd_hab, code, nom}]}).

        Une typologie n'ayant qu'un seul candidat est retenue d'office (`src`
        vaut alors `catalogue` : reprise, non vérifiée). Dès qu'il y en a
        plusieurs, aucune n'est choisie — c'est au botaniste de le faire.

        Le composant ignore d'où viennent ces propositions : catalogue ANA pour
        une alliance connue, correspondances HABREF pour toute autre
        détermination. C'est l'appelant qui sait, et il n'a pas à le lui dire.
        """
        propre = self._propre[0] if self._propre else None
        self._candidats = {
            cle: list((candidats or {}).get(cle) or [])
            for cle, _libelle, _court in TYPOLOGIES_CORRESPONDANCE
        }
        self._valeurs = {
            cle: dict(liste[0], src=source)
            for cle, liste in self._candidats.items()
            if len(liste) == 1 and cle != propre
        }
        for cle in self._lignes:
            self._rafraichir(cle)
        self.modifiee.emit()

    def set_data(self, correspondances):
        """Poser les correspondances enregistrées (relecture d'un habitat)."""
        self._valeurs = {
            cle: dict(valeurs)
            for cle, valeurs in (correspondances or {}).items()
            if isinstance(valeurs, dict) and valeurs.get("cd_hab")
        }
        for cle in self._lignes:
            self._rafraichir(cle)

    def get_data(self):
        """{typologie: {cd_hab, code, nom, src}} — None si rien n'est renseigné.

        Le libellé EST enregistré, contrairement à ce qu'une première version
        avait décidé. L'argument — HABREF fait foi et peut le corriger d'une
        version à l'autre — vaut pour la donnée, pas pour la carte : sans nom
        stocké, la légende d'un export affichait « C1.32 » tout court, et une
        carte d'habitats se lit par ses noms. Un libellé légèrement daté vaut
        mieux qu'un code nu. Le `cd_hab` reste ce qui fait autorité.
        """
        propre = {}
        for cle, valeurs in self._valeurs.items():
            entree = {"cd_hab": valeurs["cd_hab"]}
            if valeurs.get("code"):
                entree["code"] = valeurs["code"]
            if valeurs.get("nom"):
                entree["nom"] = valeurs["nom"]
            if valeurs.get("src") in SOURCES_CORRESPONDANCE:
                entree["src"] = valeurs["src"]
            propre[cle] = entree
        return propre or None

    def a_trancher(self):
        """Typologies où plusieurs codes sont proposés et où rien n'est retenu."""
        propre = self._propre[0] if self._propre else None
        return [
            libelle for cle, libelle, _court in TYPOLOGIES_CORRESPONDANCE
            if cle not in self._valeurs and cle != propre
            and len(self._candidats.get(cle, [])) > 1
        ]

    def resume(self):
        """« CORINE biotopes 41.112 (repris du catalogue), EUNIS G1.62 (arbitré ici) »."""
        return ", ".join(
            "%s %s%s" % (
                libelle, self._valeurs[cle].get("code") or "?",
                " (%s)" % _MENTION[self._valeurs[cle]["src"]]
                if self._valeurs[cle].get("src") in _MENTION else "",
            )
            for cle, libelle, _court in TYPOLOGIES_CORRESPONDANCE if cle in self._valeurs
        )

