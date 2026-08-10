# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalogue des végétations de l'Ariège : déterminations et correspondances.

Les botanistes de l'ANA déterminent à l'**alliance**, dans leur propre catalogue
(`0_Typologie.xlsx`, tenu par eux et faisant autorité). HABREF, lui, ne connaît
pas toutes ces alliances : le catalogue diverge délibérément du Prodrome sur une
quarantaine d'entrées. Ce module porte le pont entre les deux, préparé hors ligne
par `scripts/import_typologie.py` et livré en CSV dans `resources/typologie/`.

Il répond à deux questions, et à deux seulement :

1. **Que poser dans l'habitat** quand le botaniste choisit telle alliance —
   quel `cd_hab`, quel nom cité, et faut-il signaler que le code n'est qu'une
   ancre ?
2. **Quelles correspondances** ce choix apporte (CORINE, EUNIS, Natura 2000),
   pour les inscrire dans la donnée plutôt que de les laisser recalculer.

**Deux natures de `cd_hab`, à ne jamais confondre.** Pour 182 alliances, HABREF a
l'entrée : le `cd_hab` EST la détermination. Pour les 43 autres, il n'a rien —
on pose alors le code CORINE (à défaut EUNIS) de la ligne comme **ancre**, et le
nom d'alliance part en nom cité. C'est l'usage prévu d'OccHab, où le code rattache
la donnée à un référentiel national et le nom porte la détermination réelle ; mais
une ancre n'est pas une détermination, et `est_ancree` existe pour que l'interface
et l'export puissent le dire.

**Ce que ce module ne fait pas** : il ne décide rien. Il ne remplace pas la
recherche HABREF (qui reste la voie normale), ne réécrit jamais le catalogue, et
ne résout rien à la lecture — ce que le botaniste retient est recopié dans
l'habitat au moment de la saisie. Sans quoi corriger une entrée du catalogue
réécrirait après coup des stations déjà validées et livrées.

Module **pur** : bibliothèque standard seulement, testable hors QGIS.
"""
import csv
import os
import re
import unicodedata

#: Dictionnaire livré avec le plugin. Produit par `scripts/import_typologie.py`,
#: jamais édité à la main : le tableur des botanistes reste la source.
CHEMIN_DEFAUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "resources", "typologie", "dictionnaire_typologie.csv",
)

try:  # importable dans le paquet (plugin) comme en isolation (tests)
    from . import referentiels as ref
except ImportError:  # pragma: no cover - repli hors paquet
    import referentiels as ref

#: (clé HABREF, libellé, préfixe des colonnes du CSV). Les trois viennent de
#: `referentiels` : la liste des typologies et leurs noms courts y sont définis
#: une fois, et tout ce qui en dérive — colonnes du catalogue, colonnes d'export,
#: validation du bloc ANA-EVAL — s'y raccorde sans table parallèle.
TYPOLOGIES = tuple(
    (cle, libelle, ref.NOM_COURT_TYPOLOGIE[cle])
    for cle, libelle in ref.TYPOLOGIES_CORRESPONDANCE
)


def normaliser(texte):
    """Forme comparable d'un nom : sans accent, sans casse, tirets unifiés.

    Le tableur écrit `Achilleo ptarmicae – Cirsion palustris` (tiret long) là où
    HABREF met un trait d'union. Chercher « cirsion palustris » doit trouver les
    deux, sans quoi le botaniste conclut que son alliance est absente.
    """
    texte = unicodedata.normalize("NFD", texte or "")
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = re.sub(r"[‐-―\-]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip().lower()


def _entier(valeur):
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


class Alliance:
    """Une ligne du catalogue : une alliance et ce qu'elle apporte."""

    __slots__ = (
        "ligne", "nom", "classe", "auteurs", "cd_hab", "typologie", "code_habref",
        "ancre_cd_hab", "ancre_typologie", "ancre_code", "_corresp",
        "condition_n2000", "_recherche", "variantes",
    )

    def __init__(self, ligne):
        self.ligne = _entier(ligne.get("ligne_xlsx"))
        self.nom = (ligne.get("alliance") or "").strip()
        self.classe = (ligne.get("classe") or "").strip()
        self.auteurs = (ligne.get("auteurs") or "").strip()
        self.cd_hab = _entier(ligne.get("cd_hab"))
        self.typologie = (ligne.get("typologie") or "").strip()
        self.code_habref = (ligne.get("code_habref") or "").strip()
        self.ancre_cd_hab = _entier(ligne.get("ancre_cd_hab"))
        self.ancre_typologie = (ligne.get("ancre_typologie") or "").strip()
        self.ancre_code = (ligne.get("ancre_code") or "").strip()
        self.condition_n2000 = (ligne.get("condition_n2000") or "").strip()
        self._corresp = {}
        for cle_habref, _libelle, prefixe in TYPOLOGIES:
            cd_hab = _entier(ligne.get("%s_cd_hab" % prefixe))
            if cd_hab is not None:
                self._corresp[cle_habref] = {
                    "cd_hab": cd_hab,
                    "code": (ligne.get("%s_code" % prefixe) or "").strip(),
                    "nom": (ligne.get("%s_nom" % prefixe) or "").strip(),
                }
        #: Lignes du catalogue portant CE nom d'alliance, celle-ci comprise. Le
        #: catalogue la renseigne ; seule, une ligne ne sait pas qu'elle a des
        #: sœurs. Voir `Catalogue.__init__`.
        self.variantes = [self]
        # Le nom ET la classe sont indexés : on cherche aussi bien « Nitellion »
        # que « Charetea », le botaniste ne se rappelant pas toujours l'alliance
        # exacte mais toujours le grand type de végétation.
        self._recherche = normaliser("%s %s" % (self.nom, self.classe))

    def __repr__(self):  # pragma: no cover - confort de débogage
        return "<Alliance %s (%s)>" % (self.nom, self.cd_hab or self.ancre_cd_hab)

    @property
    def est_ancree(self):
        """Le `cd_hab` n'est-il qu'une ancre, faute d'entrée HABREF ?"""
        return self.cd_hab is None and self.ancre_cd_hab is not None

    @property
    def est_saisissable(self):
        """Y a-t-il un `cd_hab` à poser ? (`cd_hab` est obligatoire côté OccHab)"""
        return self.cd_hab is not None or self.ancre_cd_hab is not None

    @property
    def cd_hab_a_poser(self):
        """`cd_hab` de l'habitat : la détermination, ou l'ancre à défaut."""
        return self.cd_hab if self.cd_hab is not None else self.ancre_cd_hab

    def correspondances(self):
        """{typologie HABREF: {'cd_hab': …, 'code': …}} — copie défensive.

        Copie, parce que l'appelant l'enrichit d'une clé `src` avant de
        l'enregistrer : lui rendre la structure interne ferait qu'un habitat
        saisi modifierait le catalogue en mémoire, et donc les suivants.
        """
        return {
            typologie: dict(valeurs) for typologie, valeurs in self._corresp.items()
        }

    def candidats(self, typologie):
        """Correspondances possibles dans une typologie, toutes variantes confondues.

        C'est ce qui remplace la saisie d'un code : le botaniste a déterminé une
        alliance, il ne connaît pas forcément son code CORINE ou EUNIS. On lui
        propose donc **les correspondances que le catalogue connaît pour cette
        alliance-là**, libellé compris, plutôt qu'un champ de recherche vide.

        Dédoublonné sur le `cd_hab`, dans l'ordre des lignes du catalogue : deux
        variantes renvoient parfois au même code CORINE en ne différant que par
        leur EUNIS.
        """
        vus, candidats = set(), []
        for variante in self.variantes:
            entree = variante._corresp.get(typologie)
            if entree and entree["cd_hab"] not in vus:
                vus.add(entree["cd_hab"])
                candidats.append(dict(entree))
        return candidats

    def libelle_correspondances(self):
        """« CORINE 41.112 · EUNIS G1.62 », ou la mention d'un choix à faire.

        Le catalogue porte parfois **plusieurs lignes pour une même alliance**,
        qui ne diffèrent que par leurs correspondances (`Luzulo luzuloidis –
        Fagion sylvaticae` en a quatre). Elles ne sont plus proposées une par
        une : l'alliance apparaît une fois, et le choix se fait ensuite, dans les
        lignes de correspondance où les libellés sont lisibles.
        """
        if len(self.variantes) > 1:
            # Pas de nombre ici : le catalogue peut porter quatre lignes dont
            # deux partagent leur code CORINE, et les listes de correspondance
            # en proposeraient alors trois. Annoncer « 4 » puis en montrer 3
            # ferait chercher une option qui n'existe pas.
            return "correspondances à choisir"
        return " · ".join(
            "%s %s" % (libelle, self._corresp[cle].get("code") or "?")
            for cle, libelle, _prefixe in TYPOLOGIES if cle in self._corresp
        )

    def libelle(self):
        """Ce qui s'affiche dans une liste de propositions."""
        if self.est_ancree:
            detail = "ancre %s %s" % (self.ancre_typologie.replace("_", " "),
                                      self.ancre_code)
        else:
            detail = "%s %s" % (self.typologie, self.code_habref or "sans code")
        correspondances = self.libelle_correspondances()
        return "%s — %s%s" % (
            self.nom, detail.strip(),
            " → %s" % correspondances if correspondances else "",
        )


class Catalogue:
    """Les alliances du catalogue, interrogeables par nom, code ou cd_hab."""

    def __init__(self, alliances):
        self.alliances = list(alliances)
        # Regrouper les lignes qui décrivent la MÊME alliance : le catalogue en
        # met plusieurs quand une alliance se traduit de plusieurs façons. Elles
        # ne doivent pas se présenter comme des propositions distinctes — leurs
        # noms sont identiques — mais comme un seul choix d'alliance, dont les
        # correspondances restent à arbitrer.
        groupes = {}
        for alliance in self.alliances:
            groupes.setdefault(normaliser(alliance.nom), []).append(alliance)
        for groupe in groupes.values():
            for alliance in groupe:
                alliance.variantes = groupe
        self._groupes = groupes
        self._par_cd_hab = {}
        for alliance in self.alliances:
            # Une même ancre sert parfois deux alliances (deux syntaxons que
            # CORINE ne distingue pas) : on garde la PREMIÈRE et on ne prétend
            # pas trancher. Retrouver une alliance depuis un cd_hab d'ancre est
            # une commodité d'affichage, jamais une détermination.
            if alliance.cd_hab is not None:
                self._par_cd_hab.setdefault(alliance.cd_hab, alliance)
        for alliance in self.alliances:
            if alliance.est_ancree:
                self._par_cd_hab.setdefault(alliance.ancre_cd_hab, alliance)

    def __len__(self):
        return len(self.alliances)

    def par_cd_hab(self, cd_hab):
        """Alliance portant ce `cd_hab` (détermination d'abord, ancre ensuite).

        Commodité d'AFFICHAGE : l'index contient aussi les ancres, et une ancre
        est un code CORINE partagé avec d'autres habitats. Ne jamais s'en servir
        pour attribuer des correspondances — voir `par_determination`.
        """
        return self._par_cd_hab.get(_entier(cd_hab))

    def par_determination(self, cd_hab):
        """Alliance dont le `cd_hab` EST la détermination (jamais une ancre).

        Une ancre est un code CORINE emprunté : déterminer directement ce code
        dans HABREF ne veut pas dire qu'on a déterminé l'alliance qui l'emprunte.
        Lui attribuer les correspondances de cette alliance ferait affirmer à
        l'habitat un syntaxon que personne n'a déterminé.
        """
        cd_hab = _entier(cd_hab)
        alliance = self._par_cd_hab.get(cd_hab)
        return alliance if alliance is not None and alliance.cd_hab == cd_hab else None

    def chercher(self, texte, limite=20):
        """Alliances dont le nom ou la classe contient `texte`.

        Les correspondances en **début de nom** sortent en premier : taper
        « quercion » doit donner `Quercion pubescenti-petraeae` avant
        `Hyperico montani-Quercion petraeae`, où le mot n'arrive qu'en second.
        """
        cible = normaliser(texte)
        if not cible:
            return []
        # Une proposition par alliance, pas par ligne du catalogue : quatre
        # entrées au même nom n'aident personne à choisir.
        debut, ailleurs, vus = [], [], set()
        for alliance in self.alliances:
            clef = normaliser(alliance.nom)
            if clef in vus:
                continue
            position = alliance._recherche.find(cible)
            if position < 0:
                continue
            vus.add(clef)
            (debut if position == 0 else ailleurs).append(alliance)
        return (debut + ailleurs)[:limite]

    def ancrees(self):
        """Alliances sans entrée HABREF (posées sur une ancre)."""
        return [alliance for alliance in self.alliances if alliance.est_ancree]


def candidats_habref(fiche, noms_typologies=None):
    """{typologie: [{cd_hab, code, nom}]} depuis une fiche HABREF.

    HABREF publie, pour chaque habitat, les correspondances qu'il connaît —
    `/habref/habitat/<cd_hab>` les rend avec leurs libellés. C'est ce qui permet
    de proposer un CORINE ou un EUNIS à un botaniste qui a déterminé dans une
    autre typologie (une association PVF2, par exemple) et ne connaît pas le code
    d'arrivée : sans elles, il n'aurait qu'un champ de recherche vide.

    Seules les correspondances **directes** sont retenues. HABREF en publie
    aussi à deux sauts, mais sans libellé — les proposer reviendrait à afficher
    des codes nus, c'est-à-dire le problème qu'on cherche à éviter. Elles restent
    du ressort de la vue d'export, qui les résout côté serveur.

    `noms_typologies` : {cd_typo: nom}, tel que le serveur le publie. Sans lui,
    rien n'est rendu — mieux vaut ne rien proposer qu'associer un code à une
    typologie devinée.
    """
    noms = noms_typologies or {}
    retenues = {cle for cle, _libelle in ref.TYPOLOGIES_CORRESPONDANCE}
    candidats = {}
    for correspondance in (fiche or {}).get("correspondances") or []:
        habitat = correspondance.get("habref") or {}
        typologie = noms.get(correspondance.get("cd_typo_sortie"))
        cd_hab = habitat.get("cd_hab")
        if typologie not in retenues or not cd_hab:
            continue
        entrees = candidats.setdefault(typologie, [])
        if any(entree["cd_hab"] == cd_hab for entree in entrees):
            continue
        entrees.append({
            "cd_hab": cd_hab,
            "code": (habitat.get("lb_code") or "").strip(),
            "nom": (habitat.get("lb_hab_fr") or "").strip(),
        })
    return candidats


def nom_habref(search_name):
    """Libellé lisible d'une proposition HABREF (« G1.62 - Hêtraies… » → le nom).

    `search_name` vaut « code - nom nom auteurs » : le nom y figure deux fois,
    une fois seul puis une fois suivi des auteurs. On coupe au doublon.
    """
    texte = (search_name or "").split(" - ", 1)[-1].strip()
    mots = texte.split()
    for taille in range(len(mots) // 2, 0, -1):
        if mots[:taille] == mots[taille:2 * taille]:
            return " ".join(mots[:taille])
    return texte


_PARTAGE = None


def catalogue():
    """Le catalogue livré, chargé une fois pour toutes.

    C'est une ressource en lecture seule, sans état ni réglage : la faire
    descendre en paramètre depuis le panneau jusqu'au champ de saisie
    traverserait quatre couches sans rien y gagner. Les tests passent le leur en
    argument explicite là où c'est utile.
    """
    global _PARTAGE  # noqa: PLW0603 - cache de ressource, pas un état métier
    if _PARTAGE is None:
        _PARTAGE = charger()
    return _PARTAGE


def charger(chemin=None):
    """Catalogue lu depuis le CSV livré (ou un autre, pour les tests).

    Un catalogue absent ou illisible n'est **pas** une erreur fatale : le plugin
    doit rester utilisable sans lui — la recherche HABREF est la voie normale, ce
    catalogue n'en est que le complément ariégeois. On rend alors un catalogue
    vide, et l'appelant décide s'il le signale.
    """
    chemin = chemin or CHEMIN_DEFAUT
    try:
        with open(chemin, encoding="utf-8-sig", newline="") as fichier:
            lignes = list(csv.DictReader(fichier, delimiter=";"))
    except (OSError, csv.Error):
        return Catalogue([])
    return Catalogue(
        Alliance(ligne) for ligne in lignes
        if (ligne.get("alliance") or "").strip()
    )
