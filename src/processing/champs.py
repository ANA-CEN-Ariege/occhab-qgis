# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Registre des champs saisissables (module pur, testable).

Un champ était jusqu'ici défini à quatre endroits qui divergeaient déjà : le
formulaire station, le formulaire habitat, l'export et la vue SQL. Ajouter une
grille éditable en aurait fait cinq. Ce module le décrit **une seule fois**, et
fournit les deux accesseurs qui savent où la valeur est réellement rangée.

En sortent, sans duplication : les colonnes et éditeurs de la table attributaire,
la liste des champs de « modifier les lignes sélectionnées », les colonnes
d'export, et à terme les widgets des formulaires.

Trois stockages coexistent, hérités des contraintes d'OccHab :

- `COLONNE` — une vraie colonne (locale et côté GeoNature) ;
- `EVAL` — une clé du bloc ANA-EVAL, faute de champ natif et de champs
  additionnels côté OccHab (cf. `eval_fields`) ;
- `DOUBLE` — le recouvrement, écrit **à la fois** dans la colonne native
  `recovery_percentage` et dans le bloc (le bloc fait foi à la relecture) ;
- `TEXTE_LIBRE` — la part humaine du champ qui porte le bloc : lire et écrire
  ce texte ne doit jamais détruire le bloc qui le suit.

Ce module ne dépend que de la bibliothèque standard.
"""
from collections import namedtuple

try:  # importable dans le paquet (plugin) comme en isolation (tests)
    from . import referentiels as ref
    from .eval_fields import decode_eval, encode_eval, merge_eval, strip_eval
except ImportError:  # pragma: no cover - repli hors paquet
    import referentiels as ref
    from eval_fields import decode_eval, encode_eval, merge_eval, strip_eval

# --- Niveaux ------------------------------------------------------------------
STATION = "station"
HABITAT = "habitat"

# --- Stockages ----------------------------------------------------------------
COLONNE = "colonne"
EVAL = "eval"
#: Une correspondance de la clé `corresp` du bloc, typologie par typologie. Elle
#: ne tient pas dans `EVAL` : la valeur n'est pas un scalaire mais un dict porté
#: par le `cd_hab`, et l'écrire demande de relire les autres typologies pour ne
#: pas les effacer — `merge_eval` remplace la clé `corresp` entière.
CORRESP = "corresp"
DOUBLE = "double"
TEXTE_LIBRE = "texte_libre"

# Champ porteur du bloc ANA-EVAL (et du texte libre) selon le niveau.
PORTEUR = {STATION: "comment", HABITAT: "technical_precision"}

# --- Types de saisie ----------------------------------------------------------
TEXTE = "texte"
TEXTE_LONG = "texte_long"
ENTIER = "entier"
POURCENTAGE = "pourcentage"
DATE = "date"
CODE = "code"                # référentiel fermé local (referentiels.py)
NOMENCLATURE = "nomenclature"  # nomenclature GeoNature, chargée à la connexion
BOOLEEN = "booleen"
LISTE_TEXTE = "liste_texte"
JDD = "jdd"
OBSERVATEURS = "observateurs"

# --- Groupes d'affichage (jeux de colonnes de la table) -----------------------
G_IDENTITE = "identite"
G_STATION = "station"
G_METIER = "metier"
G_N2000 = "n2000"
G_HABITAT = "habitat"
G_MESURES = "mesures"

# `lecture_seule` : jamais modifiable, nulle part (valeur calculée ou technique).
# `cellule` : modifiable dans une cellule de la table. Distinct de `masse` — les
#   observateurs sont une liste multi-valuée, intenable dans une cellule mais
#   parfaitement modifiable en lot. Confondre les deux les rendait intouchables.
Champ = namedtuple(
    "Champ",
    "cle niveau libelle type stockage groupe referentiel nomenclature masse "
    "cellule lecture_seule largeur",
)


def _champ(cle, niveau, libelle, type_, stockage, groupe, referentiel=None,
           nomenclature=None, masse=True, cellule=True, lecture_seule=False,
           largeur=120):
    return Champ(cle, niveau, libelle, type_, stockage, groupe, referentiel,
                 nomenclature, masse, cellule, lecture_seule, largeur)


#: Identifiant de la station sur GeoNature. Il vaut mieux qu'un numéro d'ordre
#: inventé au chargement : c'est LE même que dans la base, dans les exports et
#: dans l'interface web, donc celui qu'on cite dans un courriel ou qu'on colle
#: dans une requête. Vide tant que la station n'est pas synchronisée — le fond
#: alterné, lui, continue de montrer quelles lignes décrivent la même mosaïque.
ID_STATION = "id_station"
#: Libellé HABREF du `cd_hab`, posé au chargement de la table depuis le cache du
#: plugin (cf. `dock_widget._libelles_habref`). Ce n'est pas une donnée saisie :
#: `lecture_seule` et `cellule=False` le tiennent hors de tout enregistrement.
HABREF = "habref"

#: Correspondances arbitrées, une par typologie, DÉRIVÉES du référentiel :
#: ajouter une typologie les fait apparaître d'un coup dans les colonnes du
#: tableau ET dans « modifier les lignes sélectionnées ». Elles étaient réservées
#: au formulaire, un habitat à la fois — intenable sur une mosaïque où trente
#: polygones voisins portent le même habitat.
#:
#: Déclarées ICI, à la suite du couple cd_hab / nom cité : une correspondance dit
#: ce qu'est l'habitat dans une autre typologie, elle appartient donc à son
#: identité. Reléguées en fin de liste, elles se retrouvaient tout en bas de la
#: fenêtre d'édition en masse, après les champs d'évaluation.
CHAMPS_CORRESPONDANCE = [
    _champ(cle, HABITAT, "%s (corresp.)" % libelle, TEXTE, CORRESP, G_HABITAT,
           largeur=120)
    for cle, libelle, _court in ref.TYPOLOGIES_CORRESPONDANCE
]

CHAMPS = [
    # ---------------------------------------------------------- identité
    _champ(ID_STATION, STATION, "id_station", ENTIER, COLONNE, G_IDENTITE,
           masse=False, cellule=False, lecture_seule=True, largeur=90),
    _champ("validation_status", STATION, "Statut", CODE, COLONNE, G_IDENTITE,
           referentiel=ref.STATUTS_VALIDATION, largeur=90),
    _champ("sync_status", STATION, "Synchro", TEXTE, COLONNE, G_IDENTITE,
           masse=False, lecture_seule=True, largeur=90),

    # ---------------------------------------------------------- station
    _champ("station_name", STATION, "Nom de la station", TEXTE, COLONNE, G_STATION,
           largeur=160),
    _champ("id_dataset", STATION, "Jeu de données", JDD, COLONNE, G_STATION,
           largeur=150),
    _champ("date_min", STATION, "Date début", DATE, COLONNE, G_STATION, largeur=95),
    _champ("date_max", STATION, "Date fin", DATE, COLONNE, G_STATION, largeur=95),
    # Liste multi-valuée : intenable dans une cellule, mais modifiable en masse —
    # une équipe se pose justement sur toute une campagne d'un seul geste.
    _champ("observers", STATION, "Observateurs", OBSERVATEURS, COLONNE, G_STATION,
           cellule=False, largeur=170),
    _champ("comment", STATION, "Commentaire station", TEXTE_LONG, TEXTE_LIBRE,
           G_STATION, masse=False, largeur=200),

    # ------------------------------------------------- champs métier ANA
    _champ("enjeu", STATION, "Enjeu (station)", CODE, EVAL, G_METIER,
           referentiel=ref.NIVEAUX_ENJEU, largeur=110),
    _champ("etat_conservation", STATION, "État (station)", CODE, EVAL, G_METIER,
           referentiel=ref.ETATS_CONSERVATION, largeur=110),
    _champ("zone_humide", STATION, "Zone humide", CODE, EVAL, G_METIER,
           referentiel=ref.ZONES_HUMIDES, largeur=100),

    # ------------------------------------------------ Natura 2000 (station)
    _champ("unite_vegetale", STATION, "Unité végétale", CODE, EVAL, G_N2000,
           referentiel=ref.UNITES_VEGETALES, largeur=170),
    _champ("nature_observation", STATION, "Nature de l'observation", CODE, EVAL,
           G_N2000, referentiel=ref.NATURES_OBSERVATION, largeur=200),
    _champ("echelle", STATION, "Échelle de numérisation", ENTIER, EVAL, G_N2000,
           largeur=140),

    # ------------------------------------------------------- mesures station
    _champ("area", STATION, "Surface (m²)", ENTIER, COLONNE, G_MESURES,
           masse=False, lecture_seule=True, largeur=100),
    _champ("altitude_min", STATION, "Altitude min", ENTIER, COLONNE, G_MESURES,
           masse=False, largeur=95),
    _champ("altitude_max", STATION, "Altitude max", ENTIER, COLONNE, G_MESURES,
           masse=False, largeur=95),
    _champ("depth_min", STATION, "Profondeur min", ENTIER, COLONNE, G_MESURES,
           masse=False, largeur=110),
    _champ("depth_max", STATION, "Profondeur max", ENTIER, COLONNE, G_MESURES,
           masse=False, largeur=110),
    _champ("id_nomenclature_exposure", STATION, "Exposition", NOMENCLATURE, COLONNE,
           G_MESURES, nomenclature="exposure", largeur=120),
    _champ("id_nomenclature_area_surface_calculation", STATION,
           "Méthode de surface", NOMENCLATURE, COLONNE, G_MESURES,
           nomenclature="surface_method", largeur=150),
    _champ("id_nomenclature_geographic_object", STATION, "Nature objet géo.",
           NOMENCLATURE, COLONNE, G_MESURES, nomenclature="geo_object", largeur=140),
    _champ("id_nomenclature_type_sol", STATION, "Type de sol", NOMENCLATURE, COLONNE,
           G_MESURES, nomenclature="type_sol", largeur=130),
    _champ("id_nomenclature_type_mosaique_habitat", STATION, "Mosaïque (OccHab)",
           NOMENCLATURE, COLONNE, G_MESURES, nomenclature="mosaique", largeur=150),

    # ---------------------------------------------------------- habitat
    # Modifiables en masse : un même habitat se répète souvent sur des dizaines
    # de polygones, et une correction de détermination doit pouvoir se propager.
    # Les deux vont ensemble — l'interface les remplit d'un seul choix HABREF,
    # car un code sans son nom (ou l'inverse) serait une donnée incohérente.
    _champ("cd_hab", HABITAT, "cd_hab", ENTIER, COLONNE, G_HABITAT, largeur=80),
    _champ("nom_cite", HABITAT, "Nom cité", TEXTE, COLONNE, G_HABITAT, largeur=200),
    # Le nom cité est celui que le botaniste a ÉCRIT ; celui-ci est celui que
    # HABREF donne au cd_hab retenu. Les deux diffèrent souvent — abréviation,
    # variante, faute de frappe — et c'est justement ce qu'on veut voir : la
    # colonne montre à quoi le code renvoie vraiment.
    _champ(HABREF, HABITAT, "Habitat (HABREF)", TEXTE, COLONNE, G_HABITAT,
           masse=False, cellule=False, lecture_seule=True, largeur=220),
    *CHAMPS_CORRESPONDANCE,
    _champ("recouvrement", HABITAT, "Recouvrement %", POURCENTAGE, DOUBLE, G_HABITAT,
           largeur=110),
    _champ("determiner", HABITAT, "Déterminateur", TEXTE, COLONNE, G_HABITAT,
           largeur=140),
    _champ("id_nomenclature_collection_technique", HABITAT, "Technique",
           NOMENCLATURE, COLONNE, G_HABITAT, nomenclature="technique", largeur=130),
    _champ("id_nomenclature_determination_type", HABITAT, "Détermination",
           NOMENCLATURE, COLONNE, G_HABITAT, nomenclature="determination",
           largeur=130),
    _champ("id_nomenclature_abundance", HABITAT, "Abondance", NOMENCLATURE, COLONNE,
           G_HABITAT, nomenclature="abundance", largeur=120),
    _champ("id_nomenclature_sensitivity", HABITAT, "Sensibilité", NOMENCLATURE,
           COLONNE, G_HABITAT, nomenclature="sensitivity", largeur=120),
    _champ("id_nomenclature_community_interest", HABITAT, "Intérêt communautaire",
           NOMENCLATURE, COLONNE, G_HABITAT, nomenclature="community_interest",
           largeur=170),

    # --------------------------------------------- champs métier (habitat)
    _champ("enjeu", HABITAT, "Enjeu (habitat)", CODE, EVAL, G_METIER,
           referentiel=ref.NIVEAUX_ENJEU, largeur=110),
    _champ("etat_conservation", HABITAT, "État de conservation", CODE, EVAL, G_N2000,
           referentiel=ref.ETATS_CONSERVATION, largeur=150),

    # ------------------------------------------------ Natura 2000 (habitat)
    _champ("typicite", HABITAT, "Typicité", CODE, EVAL, G_N2000,
           referentiel=ref.TYPICITES, largeur=110),
    _champ("dynamique", HABITAT, "Dynamique", CODE, EVAL, G_N2000,
           referentiel=ref.DYNAMIQUES, largeur=150),
    _champ("restauration", HABITAT, "Restauration", CODE, EVAL, G_N2000,
           referentiel=ref.RESTAURATIONS, largeur=150),
    _champ("critere", HABITAT, "Critère d'évaluation", TEXTE_LONG, EVAL, G_N2000,
           largeur=180),
    _champ("pee", HABITAT, "PEE (3 taxons max)", LISTE_TEXTE, EVAL, G_N2000,
           largeur=180),
    _champ("remarque", HABITAT, "Remarque", TEXTE_LONG, EVAL, G_N2000, largeur=180),
    _champ("technical_precision", HABITAT, "Précision technique", TEXTE_LONG,
           TEXTE_LIBRE, G_HABITAT, masse=False, largeur=180),
]


# --- Sélection ----------------------------------------------------------------
def du_niveau(niveau):
    """Champs d'un niveau (`STATION` ou `HABITAT`), dans l'ordre de déclaration."""
    return [champ for champ in CHAMPS if champ.niveau == niveau]


def par_cle(niveau, cle):
    """Champ d'un niveau par sa clé, ou None.

    Le niveau est obligatoire : `enjeu` et `etat_conservation` existent aux DEUX
    niveaux, avec le même nom mais un porteur différent.
    """
    for champ in CHAMPS:
        if champ.niveau == niveau and champ.cle == cle:
            return champ
    return None


def modifiables_en_masse(niveau=None):
    """Champs que « modifier les lignes sélectionnées » a le droit de toucher.

    En sont exclus les champs calculés ou mesurés au cas par cas (surface,
    altitudes, profondeurs), l'état de synchronisation, et les textes libres
    propres à un objet (commentaire, précision technique) — écraser d'un coup le
    commentaire de 40 stations n'a pas de sens. La détermination (nom cité +
    cd_hab), elle, est bien modifiable en lot : les deux champs sont poussés
    ensemble par la recherche HABREF de la fenêtre.
    """
    return [
        champ for champ in CHAMPS
        if champ.masse and not champ.lecture_seule
        and (niveau is None or champ.niveau == niveau)
    ]


def groupes(champs=None):
    """Groupes présents, dans l'ordre de première apparition."""
    ordre = []
    for champ in champs if champs is not None else CHAMPS:
        if champ.groupe not in ordre:
            ordre.append(champ.groupe)
    return ordre


# --- Accès aux valeurs --------------------------------------------------------
def _catalogue():
    """Le catalogue partagé. Import différé : `correspondances` lit un CSV au
    premier appel, et rien ne doit le charger pour un module qui ne s'en sert pas.
    """
    try:
        from . import correspondances
    except ImportError:  # pragma: no cover - repli hors paquet
        import correspondances
    return correspondances.catalogue()


def lire(objet, champ):
    """Valeur d'un champ dans un dict station ou habitat (None si absente)."""
    objet = objet or {}
    if champ.stockage == COLONNE:
        return objet.get(champ.cle)
    porteur = objet.get(PORTEUR[champ.niveau])
    if champ.stockage == TEXTE_LIBRE:
        return strip_eval(porteur) or None
    if champ.stockage == CORRESP:
        # Le CODE, pas le libellé : c'est lui qui identifie, et une colonne de
        # tableau n'a pas la place du nom complet. Depuis la 0.9.2 il n'est plus
        # stocké — le catalogue le rend — et à défaut on montre le `cd_hab` nu
        # plutôt que rien, pour que la correspondance reste visible.
        entree = (decode_eval(porteur).get("corresp") or {}).get(champ.cle) or {}
        cd_hab = entree.get("cd_hab")
        if not cd_hab:
            return None
        fiche = _catalogue().fiche_correspondance(cd_hab) or {}
        return fiche.get("code") or str(cd_hab)
    valeur = decode_eval(porteur).get(champ.cle)
    if champ.stockage == DOUBLE and valeur is None:
        # Repli sur la colonne native : une station venue du serveur peut porter
        # `recovery_percentage` sans bloc ANA-EVAL.
        return objet.get(_COLONNE_DOUBLE.get(champ.cle, champ.cle))
    return valeur


def colonnes_touchees(champ):
    """Clés du dict que `ecrire()` modifie pour ce champ.

    Contrepartie indispensable de `ecrire()` : un champ EVAL n'écrit pas dans une
    colonne à son nom mais dans le porteur du bloc ANA-EVAL (`comment` pour une
    station, `technical_precision` pour un habitat), et un champ DOUBLE écrit aux
    deux endroits. Sans cette correspondance, un enregistrement qui ne veut
    réécrire que les champs modifiés en oublierait la moitié.
    """
    if champ.stockage == COLONNE:
        return {champ.cle}
    porteur = PORTEUR[champ.niveau]
    if champ.stockage == DOUBLE:
        return {porteur, _COLONNE_DOUBLE.get(champ.cle, champ.cle)}
    return {porteur}


def ecrire(objet, champ, valeur):
    """Poser la valeur d'un champ (mute `objet`), bloc ANA-EVAL préservé."""
    if champ.stockage == COLONNE:
        objet[champ.cle] = valeur
        return objet
    porteur = PORTEUR[champ.niveau]
    if champ.stockage == TEXTE_LIBRE:
        # Remplacer le texte humain SANS toucher au bloc qui le suit.
        objet[porteur] = encode_eval(valeur or "", **decode_eval(objet.get(porteur)))
        return objet
    if champ.stockage == CORRESP:
        # `valeur` est un dict portant au moins {cd_hab} — ou None pour retirer
        # la correspondance. On relit les autres typologies : `merge_eval`
        # remplace la clé `corresp` en bloc, les omettre les effacerait.
        corresp = dict((decode_eval(objet.get(porteur)) or {}).get("corresp") or {})
        if valeur:
            # Seul le `cd_hab` est retenu (`_clean_corresp` écarte le reste) :
            # le bloc doit tenir dans les 500 caractères du champ porteur.
            corresp[champ.cle] = {"cd_hab": valeur["cd_hab"], "src": "manuel"}
        else:
            corresp.pop(champ.cle, None)
        objet[porteur] = merge_eval(objet.get(porteur), corresp=corresp or None)
        return objet
    objet[porteur] = merge_eval(objet.get(porteur), **{champ.cle: valeur})
    if champ.stockage == DOUBLE:
        objet[_COLONNE_DOUBLE.get(champ.cle, champ.cle)] = valeur
    return objet


# Champs `DOUBLE` : correspondance clé du bloc → colonne native.
_COLONNE_DOUBLE = {"recouvrement": "recovery_percentage"}
