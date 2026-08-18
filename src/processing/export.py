# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Aplatir les stations × habitats d'un JDD en lignes de cartographie d'habitats.

Une ligne par **habitat** (la géométrie de la station est répétée pour chacun de
ses habitats ; une station sans habitat donne quand même une ligne). Les
identifiants de nomenclature et de rôle sont résolus en **libellés** via des
callables fournis par l'appelant. Les champs métier ANA (enjeu / état /
recouvrement) sont décodés du commentaire station et de `technical_precision`.

Module **pur** (aucune dépendance PyQGIS) : il reçoit des stations déjà
décomposées par `payload.parse_server_station` et renvoie des dicts d'attributs
(+ `_geom` WKT et `_geom_type`), prêts à écrire. Testable hors QGIS.
"""
try:  # importable dans le paquet (plugin) comme en isolation (tests)
    from . import referentiels as ref
    from .eval_fields import decode_eval
except ImportError:  # pragma: no cover - repli hors paquet
    import referentiels as ref
    from eval_fields import decode_eval

# Ordre des colonnes de sortie (le driver Shapefile tronquera les noms à 10 car.).
STATION_FIELDS = [
    "id_station", "nom_station", "jdd", "statut", "date_min", "date_max",
    "observateurs", "numerisateur", "altitude_min", "altitude_max",
    "profondeur_min", "profondeur_max", "surface_m2", "exposition",
    "methode_surface", "nature_objet", "type_sol", "type_mosaique",
    "st_enjeu", "st_etat_cons", "st_zone_humide",
    # Natura 2000 (annexe 2 : id_uv, id_nat_obs, echelle)
    "unite_vegetale", "nature_obs", "echelle",
]
HABITAT_FIELDS = [
    "id_habitat", "cd_hab", "code_habref", "habitat_officiel", "nom_cite",
    "determinateur", "recouvrement", "technique", "determination", "abondance",
    "sensibilite", "interet_com", "hab_enjeu", "hab_etat_cons",
    # Natura 2000 (annexe 2 : id_typi, id_dynam, id_restaur) + extensions ANA
    "typicite", "dynamique", "restauration", "critere", "pee", "remarque",
    # Détermination du catalogue ANA et correspondances INSCRITES dans la donnée.
    # `alliance` n'est renseignée que si `cd_hab` est une ANCRE — un code CORINE
    # ou EUNIS emprunté faute d'entrée HABREF. La lire vide ne veut donc pas dire
    # « pas d'alliance », mais « le cd_hab est lui-même la détermination ».
    # Le champ ne s'appelle pas « determination » : la colonne existe déjà plus
    # haut, pour le type de détermination.
    "alliance", "ancre_typo",
    "corine_cite", "eunis_cite", "n2000_cite", "cahiers_cite", "corresp_manu",
]
#: Colonnes de correspondance, DÉRIVÉES du référentiel des typologies : une
#: cinquième typologie ne se déclare qu'à un endroit. Ces codes-là priment sur
#: ceux que la vue recalcule — ils ont été retenus par un botaniste.
_COLONNES_CORRESP = [
    (cle, "%s_cite" % court)
    for cle, _libelle, court in ref.TYPOLOGIES_CORRESPONDANCE
]
FIELDS = STATION_FIELDS + HABITAT_FIELDS
NUMERIC_FIELDS = {
    "id_station", "altitude_min", "altitude_max", "profondeur_min",
    "profondeur_max", "surface_m2", "id_habitat", "cd_hab", "recouvrement",
}


def _code_stocke(porteur, typologie):
    """Code encore inscrit dans le bloc pour cette typologie, ou None."""
    if not porteur:
        return None
    try:  # importable dans le paquet (plugin) comme en isolation (tests)
        from . import correspondances
    except ImportError:  # pragma: no cover - repli hors paquet
        import correspondances
    return correspondances.code_stocke(porteur, typologie)


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _colonnes_catalogue(hab_eval, code_corresp=None, porteur=None):
    """Détermination hors HABREF et correspondances inscrites, à plat.

    `corresp_manu` liste les seules typologies **arbitrées à la main**. C'est la
    colonne qui compte à la relecture : tout le reste peut venir du catalogue
    repris tel quel, et n'atteste alors d'aucune vérification.
    """
    # Sans résolveur, le cd_hab tient lieu de code : la colonne est du texte, et
    # une correspondance non résolue reste plus parlante qu'une case vide.
    resoudre = code_corresp or (lambda cd: str(cd))
    determination = hab_eval.get("determination") or {}
    corresp = hab_eval.get("corresp") or {}
    colonnes = {
        "alliance": determination.get("nom"),
        "ancre_typo": determination.get("ancre"),
        "corresp_manu": " ; ".join(sorted(
            typologie for typologie, valeurs in corresp.items()
            if valeurs.get("src") == "manuel"
        )) or None,
    }
    for typologie, colonne in _COLONNES_CORRESP:
        cd_hab = (corresp.get(typologie) or {}).get("cd_hab")
        if not cd_hab:
            colonnes[colonne] = None
            continue
        # Le bloc ANTÉRIEUR à la 0.11.0 porte encore le code : le préférer au
        # `cd_hab` nu quand le résolveur ne sait pas répondre. Sans cela une
        # colonne de codes reçoit un nombre, qui se lit comme un code faux.
        colonnes[colonne] = resoudre(cd_hab) or _code_stocke(porteur, typologie) \
            or str(cd_hab)
    return colonnes


def flatten_cartography(stations, nomenclature_label=None, jdd_name=None,
                        role_label=None, habref_label=None, code_corresp=None):
    """Renvoyer une liste de lignes (dicts) — une par habitat.

    Args:
        stations: liste de tuples ``(station, habitats, observers)`` tels que
            renvoyés par ``parse_server_station``.
        nomenclature_label: callable ``id_nomenclature -> libellé`` (ou None).
        jdd_name: libellé du jeu de données.
        role_label: callable ``id_role -> nom`` (numérisateur).
        code_corresp: callable ``cd_hab -> code`` pour les correspondances, qui
            rend le ``cd_hab`` tel quel s'il ne le résout pas. Depuis la 0.11.0 la
            donnée ne porte plus que le ``cd_hab`` (le bloc dépassait les 500
            caractères du champ) : le code se retrouve à la lecture.

    Chaque dict contient toutes les clés de ``FIELDS`` (habitat à None si la
    station n'a pas d'habitat) plus ``_geom`` (WKT) et ``_geom_type``.
    """
    label = nomenclature_label or (lambda _i: None)
    role = role_label or (lambda _i: None)
    habref = habref_label or (lambda _c: None)
    rows = []
    for station, habitats, observers in stations:
        st_eval = decode_eval(station.get("comment") or "")
        observers_txt = station.get("observers_txt") or ", ".join(
            o.get("observer_name") or ""
            for o in (observers or []) if o.get("observer_name")
        )
        station_row = {
            "id_station": station.get("id_station"),
            "nom_station": station.get("station_name"),
            "jdd": jdd_name,
            "date_min": station.get("date_min"),
            "date_max": station.get("date_max"),
            "observateurs": observers_txt or None,
            "numerisateur": role(station.get("id_digitiser")),
            "altitude_min": station.get("altitude_min"),
            "altitude_max": station.get("altitude_max"),
            "profondeur_min": station.get("depth_min"),
            "profondeur_max": station.get("depth_max"),
            "surface_m2": station.get("area"),
            "exposition": label(station.get("id_nomenclature_exposure")),
            "methode_surface": label(
                station.get("id_nomenclature_area_surface_calculation")
            ),
            "nature_objet": label(station.get("id_nomenclature_geographic_object")),
            "type_sol": label(station.get("id_nomenclature_type_sol")),
            "type_mosaique": label(
                station.get("id_nomenclature_type_mosaique_habitat")
            ),
            "st_enjeu": st_eval.get("enjeu"),
            "st_etat_cons": st_eval.get("etat_conservation"),
            "st_zone_humide": st_eval.get("zone_humide"),
            "statut": station.get("validation_status"),
            "unite_vegetale": st_eval.get("unite_vegetale"),
            "nature_obs": st_eval.get("nature_observation"),
            "echelle": st_eval.get("echelle"),
        }
        for habitat in (habitats or [None]):
            row = dict.fromkeys(FIELDS)
            row.update(station_row)
            if habitat is not None:
                hab_eval = decode_eval(habitat.get("technical_precision") or "")
                recouvrement = habitat.get("recovery_percentage")
                if recouvrement is None:
                    recouvrement = _to_float(hab_eval.get("recouvrement"))
                official = habref(habitat.get("cd_hab")) or {}
                row.update({
                    "id_habitat": habitat.get("id_habitat"),
                    "cd_hab": habitat.get("cd_hab"),
                    "code_habref": official.get("code"),
                    "habitat_officiel": official.get("nom"),
                    "nom_cite": habitat.get("nom_cite"),
                    "determinateur": habitat.get("determiner"),
                    "recouvrement": recouvrement,
                    "technique": label(
                        habitat.get("id_nomenclature_collection_technique")
                    ),
                    "determination": label(
                        habitat.get("id_nomenclature_determination_type")
                    ),
                    "abondance": label(habitat.get("id_nomenclature_abundance")),
                    "sensibilite": label(habitat.get("id_nomenclature_sensitivity")),
                    "interet_com": label(
                        habitat.get("id_nomenclature_community_interest")
                    ),
                    "hab_enjeu": hab_eval.get("enjeu"),
                    "hab_etat_cons": hab_eval.get("etat_conservation"),
                    "typicite": hab_eval.get("typicite"),
                    "dynamique": hab_eval.get("dynamique"),
                    "restauration": hab_eval.get("restauration"),
                    "critere": hab_eval.get("critere"),
                    # Liste de taxons → une chaîne : un shapefile n'a pas de type liste.
                    "pee": " ; ".join(hab_eval.get("pee") or []) or None,
                    "remarque": hab_eval.get("remarque"),
                })
                row.update(_colonnes_catalogue(
                    hab_eval, code_corresp,
                    porteur=habitat.get("technical_precision")))
            row["_geom"] = station.get("geom")
            row["_geom_type"] = station.get("geom_type")
            rows.append(row)
    return rows
