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
    from .eval_fields import bloc_brut, decode_eval, encode_eval
except ImportError:  # pragma: no cover - repli hors paquet
    import referentiels as ref
    from eval_fields import bloc_brut, decode_eval, encode_eval

#: (clé HABREF, libellé, préfixe des colonnes du CSV). Les trois viennent de
#: `referentiels` : la liste des typologies et leurs noms courts y sont définis
#: une fois, et tout ce qui en dérive — colonnes du catalogue, colonnes d'export,
#: validation du bloc ANA-EVAL — s'y raccorde sans table parallèle.
TYPOLOGIES = tuple(ref.TYPOLOGIES_CORRESPONDANCE)


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


#: Suffixes qui font d'un dernier mot une ÉPITHÈTE et non un genre : le squelette
#: s'arrête aux genres, pour que la forme abrégée rejoigne la complète.
_SUFFIXES_SYNTAXON = ("etea", "etalia", "ion", "enion", "etum", "enalia")


def squelette(nom):
    """Genres d'un syntaxon, pour rapprocher ses formes abrégée et complète.

    HABREF porte « Eleocharito-Sagittarion » là où le catalogue écrit
    « Eleocharito palustris-Sagittarion sagittifoliae » : même végétation, deux
    écritures. Réduites à leurs genres, les deux donnent
    « eleocharito-sagittarion » et se retrouvent.

    **Seuls les noms COMPOSÉS sont réduits.** Retirer l'épithète d'un nom
    simple détruirait le seul mot qui discrimine : le catalogue porte cinq
    `Salicion` et quatre `Caricion`, et les confondre ferait écrire les
    correspondances de l'un sur l'autre. L'abréviation qu'on cherche à rattraper
    ne se produit d'ailleurs que sur les noms à deux genres.

    Un nom qui ne se termine pas par un suffixe de syntaxon n'est pas réduit non
    plus : « Cultures et jardins maraîchers » n'est pas une nomenclature latine,
    et en garder le premier mot de chaque membre n'aurait aucun sens.
    """
    # `normaliser` remplace les tirets par des espaces — c'est ce qu'il faut pour
    # CHERCHER, pas pour découper : ici le tiret sépare les deux genres du nom
    # composé, et il doit survivre. On unifie donc ses variantes au lieu de les
    # effacer.
    sans_accent = unicodedata.normalize("NFD", nom or "")
    sans_accent = "".join(c for c in sans_accent
                          if unicodedata.category(c) != "Mn")
    normalise = re.sub(r"\s+", " ", re.sub(r"[‐-―]", "-", sans_accent)).strip().lower()
    membres = [m for m in normalise.split("-") if m.strip()]
    if len(membres) < 2 or not membres[-1].split():
        return normalise
    if not membres[-1].split()[0].endswith(_SUFFIXES_SYNTAXON):
        return normalise
    return "-".join(membre.split()[0] for membre in membres)


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
        # Index des seules DÉTERMINATIONS. Les ancres n'y entrent pas : une ancre
        # est un code CORINE emprunté, partagé avec bien d'autres habitats, et
        # deux alliances peuvent emprunter le même. Retrouver « une » alliance
        # depuis une ancre ferait attribuer à l'habitat un syntaxon que personne
        # n'a déterminé, avec ses correspondances.
        self._par_determination = {}
        for alliance in self.alliances:
            if alliance.cd_hab is not None:
                self._par_determination.setdefault(alliance.cd_hab, alliance)
        # Index par squelette de nom : c'est le seul moyen de retrouver une
        # alliance choisie sous sa forme HABREF abrégée (cf. `squelette`).
        #
        # Un squelette que PLUSIEURS alliances se partagent est écarté : « Rubo
        # caesii-Populion nigrae » et « Rubo ulmifolii-Populion albae » se
        # réduisent tous deux à « rubo-populion », et rendre l'une pour l'autre
        # écrirait des correspondances fausses sans que rien ne le signale.
        # Mieux vaut ne rien proposer — le botaniste garde la recherche libre.
        # Index par nom EXACT, consulté avant le squelette : une alliance dont
        # le squelette est ambigu reste retrouvable sous son nom complet. Sans
        # lui, écarter « rubo-populion » perdrait aussi « Rubo caesii-Populion
        # nigrae », pourtant sans la moindre ambiguïté.
        self._par_nom = {}
        for alliance in self.alliances:
            self._par_nom.setdefault(normaliser(alliance.nom), alliance)
        candidats = {}
        for alliance in self.alliances:
            candidats.setdefault(squelette(alliance.nom), []).append(alliance)
        self._par_squelette = {
            sq: liste[0] for sq, liste in candidats.items()
            # Les VARIANTES d'une même alliance (mêmes nom à la graphie près)
            # ne sont pas une ambiguïté : c'est le même syntaxon.
            if len({normaliser(a.nom) for a in liste}) == 1
        }
        # Index cd_hab → {code, nom} de TOUTES les correspondances du catalogue.
        # Depuis la 0.11.0 la donnée ne porte plus que le `cd_hab` : c'est ici que
        # l'export retrouve code et libellé, hors ligne et sans interroger HABREF
        # code par code — ce qui l'avait fait s'effondrer.
        self._fiches_corresp = {}
        for alliance in self.alliances:
            for entree in alliance._corresp.values():
                fiche = self._fiches_corresp.setdefault(entree["cd_hab"], {})
                for cle in ("code", "nom"):
                    if entree.get(cle) and not fiche.get(cle):
                        fiche[cle] = entree[cle]

    def __len__(self):
        return len(self.alliances)

    def par_determination(self, cd_hab):
        """Alliance dont le `cd_hab` EST la détermination (jamais une ancre)."""
        return self._par_determination.get(_entier(cd_hab))

    def fiche_correspondance(self, cd_hab):
        """{'code': …, 'nom': …} d'un cd_hab de correspondance, ou None.

        Ne connaît que les correspondances DU CATALOGUE. Une correspondance
        arbitrée hors catalogue (recherche HABREF « Autre… ») n'y est pas :
        l'appelant doit prévoir un repli sur HABREF.
        """
        return self._fiches_corresp.get(_entier(cd_hab))

    def par_nom_approche(self, nom):
        """Alliance portant ce nom, quelle qu'en soit l'écriture.

        Le rapprochement se fait sur les GENRES (cf. `squelette`), sans quoi une
        alliance choisie sous sa forme HABREF abrégée reste introuvable dans le
        catalogue — et ses correspondances avec elle.

        Le nom exact d'abord, le squelette ensuite — et seulement s'il ne
        désigne qu'une alliance (cf. `Catalogue.__init__`). Deux syntaxons de
        même squelette ne se départagent pas, et en choisir un écrirait ses
        correspondances sur l'autre. On ne propose alors rien : la recherche
        libre reste ouverte, et le botaniste tranche.
        """
        if not nom:
            return None
        exacte = self._par_nom.get(normaliser(nom))
        if exacte is not None:
            return exacte
        return self._par_squelette.get(squelette(nom))

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
    retenues = {cle for cle, _libelle, _court in ref.TYPOLOGIES_CORRESPONDANCE}
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


#: Un code HABREF : chiffres, lettres et points, sans espace (« 6.0.1.0.2 »,
#: « G1.62 »). Sert à distinguer « code - nom » d'un NOM qui contient lui-même
#: un tiret espacé — « Centaurio pulchelli - Blackstonion perfoliatae ».
_CODE_SEUL = re.compile(r"^[A-Za-z0-9][\w.]*$")


def nom_habref(search_name):
    """Libellé lisible d'une proposition HABREF (« G1.62 - Hêtraies… » → le nom).

    Deux nettoyages, et deux seulement :

    1. le **code de tête**, quand il y en a un. On ne coupe qu'à un vrai code :
       certains noms de syntaxons portent eux-mêmes un tiret espacé (« Centaurio
       pulchelli - Blackstonion perfoliatae »), et couper au premier « - »
       venu en amputerait la moitié ;
    2. le **nom répété**. `search_name` vaut « code - nom nom auteurs » : le nom
       y figure deux fois, une fois seul puis une fois suivi des auteurs.

    Idempotent : appliquée à un nom déjà propre, la fonction le rend inchangé.
    C'est ce qui permet de s'en servir aussi pour rattraper un libellé mal
    découpé par une version antérieure.
    """
    # Découper AVANT de rogner : un habitat sans code donne « - nom nom
    # auteurs », dont le séparateur commence par l'espace de tête.
    texte = search_name or ""
    tete, separateur, reste = texte.partition(" - ")
    tete = tete.strip()
    if separateur and (not tete or _CODE_SEUL.match(tete)):
        texte = reste
    texte = texte.strip()
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


def correspondances_a_alleger(technical_precision):
    """Le bloc porte-t-il encore `code` ou `nom` dans ses correspondances ?

    Jusqu'à la 0.11.0, chaque correspondance enregistrait son code ET son libellé.
    À quatre typologies, le bloc dépassait les 500 caractères de
    `technical_precision` et GeoNature refusait l'enregistrement de la station
    entière. Seul le `cd_hab` est désormais écrit ; code et libellé se retrouvent
    à la lecture (catalogue, puis HABREF).

    Repérer ces blocs permet de les réécrire AVANT qu'une saisie ne bute dessus.

    La lecture se fait sur le bloc BRUT : `decode_eval` écarte le libellé — il ne
    fait plus partie du format — et ne peut donc pas servir à constater sa
    présence.

    Un code que le CATALOGUE NE SAIT PAS restituer ne compte pas : le bloc en est
    alors la seule copie, l'allègement le garde, et le signaler ferait proposer
    une réécriture qui n'aurait rien à retirer.
    """
    corresp = (bloc_brut(technical_precision) or {}).get("corresp") or {}
    if not isinstance(corresp, dict):
        return False
    for valeurs in corresp.values():
        if not isinstance(valeurs, dict):
            continue
        if valeurs.get("nom"):
            return True                      # le libellé part toujours
        if valeurs.get("code") and catalogue().fiche_correspondance(valeurs.get("cd_hab")):
            return True                      # code retrouvable : retirable
    return False


def alleger_correspondances(technical_precision):
    """Bloc réécrit sans les `code`/`nom` des correspondances, ou None.

    None signifie « rien à faire » : sans lui, chaque passage marquerait toutes
    les stations « à synchroniser » pour une réécriture identique.

    Le LIBELLÉ part toujours : c'est lui qui pesait, et le catalogue comme HABREF
    savent le rendre. Le CODE ne part que si le catalogue sait le restituer.

    Sans cette nuance, l'allègement effaçait la seule copie du code d'une
    correspondance arbitrée hors catalogue, et la colonne affichait ensuite le
    `cd_hab` nu — un nombre, dans une colonne de codes. Mesuré sur une base de
    terrain : garder ces codes-là coûte 12 entrées sur 514, le bloc le plus long
    reste à 365 caractères (limite : 500), et les 26 habitats que GeoNature
    refusait passent tous.
    """
    if not correspondances_a_alleger(technical_precision):
        return None
    champs = decode_eval(technical_precision)
    corresp = champs.get("corresp")
    if corresp:
        garde = {}
        for cle, valeurs in corresp.items():
            entree = dict(valeurs)
            entree.pop("code", None)
            if not catalogue().fiche_correspondance(entree.get("cd_hab")):
                code = code_stocke(technical_precision, cle)
                if code:
                    entree["code"] = code    # seule copie : elle reste
            garde[cle] = entree
        champs["corresp"] = garde
    return encode_eval(technical_precision, **champs)


def code_stocke(technical_precision, typologie):
    """Code que le bloc porte ENCORE pour cette typologie, ou None.

    Les blocs écrits avant la 0.11.0 recopient le code de chaque correspondance.
    `decode_eval` ne le rend plus — il ne fait plus partie du format — mais il
    est toujours dans la donnée, et c'est la meilleure source qui reste quand ni
    le catalogue ni HABREF ne savent nommer le `cd_hab`.

    Sans ce repli, un poste encore chargé de blocs anciens affiche le `cd_hab`
    nu dans une colonne de codes — « 17228 » là où la donnée disait « 53.2142 ».
    Un nombre à la place d'un code n'est pas une information dégradée : il se lit
    comme un code faux.
    """
    corresp = (bloc_brut(technical_precision) or {}).get("corresp") or {}
    entree = corresp.get(typologie) if isinstance(corresp, dict) else None
    if not isinstance(entree, dict):
        return None
    return (entree.get("code") or "").strip() or None


def nom_stocke(technical_precision, typologie):
    """Libellé que le bloc porte ENCORE pour cette typologie, ou None."""
    corresp = (bloc_brut(technical_precision) or {}).get("corresp") or {}
    entree = corresp.get(typologie) if isinstance(corresp, dict) else None
    if not isinstance(entree, dict):
        return None
    return (entree.get("nom") or "").strip() or None
