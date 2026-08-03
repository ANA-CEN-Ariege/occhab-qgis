# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tampon d'édition d'un ensemble stations × habitats (module pur, testable).

C'est le cœur de la table attributaire, volontairement séparé de Qt : la
propagation d'un champ station à ses lignes sœurs, le suivi des modifications et
l'application en masse sont exactement ce qui peut corrompre des données en
silence, donc exactement ce qui doit être testable sans interface.

**Une ligne par habitat**, comme l'export : une station à trois habitats occupe
trois lignes, une station sans habitat en occupe une (colonnes habitat vides).

Chaque ligne **référence** le dict de sa station — elle n'en fait pas de copie.
Modifier un champ station depuis une ligne le modifie donc pour toutes ses
lignes sœurs, sans code de propagation : c'est la structure qui l'assure.

Les écritures sont accumulées **en mémoire**. `modifications()` rend ensuite les
stations à réécrire, pour un enregistrement en une passe.
"""
from collections import namedtuple

try:  # importable dans le paquet (plugin) comme en isolation (tests)
    from . import champs as ch
    from .referentiels import BROUILLON as _BROUILLON
    from .referentiels import VALIDE as _VALIDE
except ImportError:  # pragma: no cover - repli hors paquet
    import champs as ch
    from referentiels import BROUILLON as _BROUILLON
    from referentiels import VALIDE as _VALIDE

Ligne = namedtuple("Ligne", "station habitat")

# Recouvrement total attendu dans un polygone (cahier des charges N2000 : la
# somme des pourcentages des habitats d'une même géométrie vaut 100).
RECOUVREMENT_TOTAL = 100


class Grille:
    """Ensemble de lignes stations × habitats, éditable et suivi."""

    def __init__(self, stations):
        """`stations` : dicts tels que rendus par `OccHabDatabase.get_stations_full`."""
        self.stations = [dict(s) for s in stations or []]
        self.lignes = []
        for station in self.stations:
            habitats = [dict(h) for h in station.get("habitats") or []]
            station["habitats"] = habitats
            if habitats:
                for habitat in habitats:
                    self.lignes.append(Ligne(station, habitat))
            else:  # station sans habitat : une ligne quand même
                self.lignes.append(Ligne(station, None))
        self._modifies = set()  # {(niveau, id de l'objet, clé du champ)}

    # ------------------------------------------------------------- lecture
    def __len__(self):
        return len(self.lignes)

    def objet(self, ligne, champ):
        """Dict porteur du champ pour cette ligne (None si habitat absent)."""
        return ligne.station if champ.niveau == ch.STATION else ligne.habitat

    def valeur(self, ligne, champ):
        """Valeur d'un champ sur une ligne (None si la ligne n'a pas d'habitat)."""
        objet = self.objet(ligne, champ)
        return ch.lire(objet, champ) if objet is not None else None

    def modifie(self, ligne, champ):
        """Cette cellule a-t-elle été modifiée depuis le chargement ?"""
        objet = self.objet(ligne, champ)
        return objet is not None and self._cle(champ, objet) in self._modifies

    def editable(self, ligne, champ):
        """Cette cellule est-elle modifiable dans la table ?

        Non si le champ n'est pas saisissable en cellule (`cellule=False` : les
        observateurs, qui passent par l'application en masse), et non pour une
        colonne habitat sur la ligne d'une station qui n'en a pas.
        """
        if champ.lecture_seule or not champ.cellule:
            return False
        return self.objet(ligne, champ) is not None

    # ------------------------------------------------------------- écriture
    def definir(self, ligne, champ, valeur):
        """Poser une valeur. Renvoie True si elle a changé.

        Pour un champ station, la modification vaut pour toutes les lignes de la
        même station — l'appelant doit rafraîchir l'affichage de `lignes_de()`.
        """
        objet = self.objet(ligne, champ)
        if objet is None or not self.editable(ligne, champ):
            return False
        if ch.lire(objet, champ) == valeur:
            return False
        ch.ecrire(objet, champ, valeur)
        self._modifies.add(self._cle(champ, objet))
        return True

    def lignes_de(self, ligne):
        """Indices des lignes partageant la station de `ligne` (elle comprise)."""
        return [i for i, autre in enumerate(self.lignes)
                if autre.station is ligne.station]

    # --------------------------------------------------------- en masse
    def previsualiser(self, lignes, valeurs):
        """Ce que l'application en masse ferait, sans rien modifier.

        `valeurs` : {(niveau, clé): valeur}. Le chiffre qui compte n'est pas le
        nombre de lignes visées mais celui des valeurs **existantes et
        différentes** qui seraient écrasées : c'est la seule perte possible.
        """
        stations, habitats, ecrasements = set(), set(), 0
        for niveau, cle in valeurs:
            champ = ch.par_cle(niveau, cle)
            if champ is None:
                continue
            for objet in self._cibles(lignes, champ):
                marque = stations if niveau == ch.STATION else habitats
                marque.add(id(objet))
                ancienne = ch.lire(objet, champ)
                if ancienne not in (None, "", []) and ancienne != valeurs[(niveau, cle)]:
                    ecrasements += 1
        return {
            "stations": len(stations),
            "habitats": len(habitats),
            "ecrasements": ecrasements,
        }

    def appliquer(self, lignes, valeurs):
        """Appliquer `valeurs` aux lignes visées. Renvoie le nombre d'écritures.

        Un champ station n'est écrit **qu'une fois par station**, même si dix de
        ses lignes sont sélectionnées.
        """
        ecrites = 0
        for (niveau, cle), valeur in valeurs.items():
            champ = ch.par_cle(niveau, cle)
            if champ is None or champ.lecture_seule:
                continue
            for objet in self._cibles(lignes, champ):
                if ch.lire(objet, champ) == valeur:
                    continue
                ch.ecrire(objet, champ, valeur)
                self._modifies.add(self._cle(champ, objet))
                ecrites += 1
        return ecrites

    def _cibles(self, lignes, champ):
        """Objets distincts touchés par un champ sur un ensemble de lignes."""
        vus, cibles = set(), []
        for ligne in lignes:
            objet = self.objet(ligne, champ)
            if objet is None or id(objet) in vus:
                continue
            vus.add(id(objet))
            cibles.append(objet)
        return cibles

    # ------------------------------------------------------- enregistrement
    def modifications(self):
        """Stations à réécrire, avec leurs habitats. Vide si rien n'a changé.

        Une station est à réécrire dès qu'elle-même OU l'un de ses habitats a
        changé : les habitats sont remplacés en bloc à l'enregistrement.
        """
        touchees = []
        for station in self.stations:
            if self._station_modifiee(station):
                touchees.append(station)
        return touchees

    def colonnes_modifiees(self, station):
        """Clés du dict station réellement touchées depuis le chargement.

        Permet de ne réécrire QUE ce qui a changé. Réécrire la ligne entière
        depuis cette copie mémoire écrasait tout ce qu'une autre fenêtre avait
        enregistré entre-temps — jusqu'à `id_station`, ce qui détachait la
        station du serveur et la faisait recréer en double à la synchro suivante.
        """
        identifiant = station.get("id")
        colonnes = set()
        for niveau, objet_id, cle in self._modifies:
            if niveau != ch.STATION or objet_id != identifiant:
                continue
            champ = ch.par_cle(niveau, cle)
            if champ is not None:
                colonnes |= ch.colonnes_touchees(champ)
        return colonnes

    def habitats_modifies(self, station):
        """Un habitat de cette station a-t-il changé ? (les habitats sont remplacés en bloc)"""
        habitat_ids = {h.get("id") for h in station.get("habitats") or []}
        return any(
            niveau == ch.HABITAT and identifiant in habitat_ids
            for niveau, identifiant, _cle in self._modifies
        )

    def _station_modifiee(self, station):
        for niveau, identifiant, _cle in self._modifies:
            if niveau == ch.STATION and identifiant == station.get("id"):
                return True
        return self.habitats_modifies(station)

    STATUT = "validation_status"

    def statuts_retrogrades(self):
        """Stations validées dont le CONTENU vient de changer.

        Revenir sur une station validée la remet en brouillon : c'est ce que veut
        dire « j'y retouche ». Mais changer *le statut lui-même* n'est pas une
        retouche de contenu — sinon valider une station la remettrait aussitôt en
        brouillon, et rien ne pourrait jamais être validé.
        """
        retrogradees = []
        for station in self.stations:
            if station.get(self.STATUT) != _VALIDE:
                continue
            if self._modifie_explicitement(station, self.STATUT):
                continue
            if self._station_modifiee(station):
                retrogradees.append(station)
        return retrogradees

    def retrograder_statuts(self):
        """Repasser en brouillon les stations validées dont le contenu a changé.

        Marque la modification, sans quoi l'enregistrement ciblé — qui n'écrit que
        les colonnes signalées comme modifiées — passerait à côté.
        Renvoie les stations concernées.
        """
        champ = ch.par_cle(ch.STATION, self.STATUT)
        retrogradees = self.statuts_retrogrades()
        for station in retrogradees:
            ch.ecrire(station, champ, _BROUILLON)
            self._modifies.add(self._cle(champ, station))
        return retrogradees

    def _modifie_explicitement(self, station, cle):
        return (ch.STATION, station.get("id"), cle) in self._modifies

    def a_des_modifications(self):
        return bool(self._modifies)

    def oublier_modifications(self):
        """Repartir d'un état « propre » (après un enregistrement réussi)."""
        self._modifies = set()

    # ------------------------------------------------------- cohérence
    def recouvrements_incoherents(self, stations=None):
        """Stations dont la somme des recouvrements s'écarte de 100 %.

        Exigence du cahier des charges N2000 pour un polygone en mosaïque. Les
        stations dont aucun habitat n'a de recouvrement sont ignorées : ne pas
        avoir renseigné n'est pas une incohérence.

        `stations` restreint le contrôle à un sous-ensemble. Sans lui, toute la
        grille est passée en revue — et l'utilisateur se voyait réclamer un
        arbitrage sur des stations qu'il n'avait pas touchées, à chaque
        enregistrement.
        """
        champ = ch.par_cle(ch.HABITAT, "recouvrement")
        fautives = []
        for station in (self.stations if stations is None else stations):
            habitats = station.get("habitats") or []
            valeurs = [ch.lire(h, champ) for h in habitats]
            renseignees = [v for v in valeurs if isinstance(v, (int, float))]
            if not renseignees:
                continue
            total = sum(renseignees)
            if abs(total - RECOUVREMENT_TOTAL) > 0.01:
                fautives.append((station, total))
        return fautives

    @staticmethod
    def _cle(champ, objet):
        return (champ.niveau, objet.get("id"), champ.cle)
