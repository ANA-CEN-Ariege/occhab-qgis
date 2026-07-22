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
    from .eval_fields import decode_eval
except ImportError:  # pragma: no cover - repli hors paquet
    from eval_fields import decode_eval

# Ordre des colonnes de sortie (le driver Shapefile tronquera les noms à 10 car.).
STATION_FIELDS = [
    "id_station", "nom_station", "jdd", "date_min", "date_max", "observateurs",
    "numerisateur", "altitude_min", "altitude_max", "profondeur_min",
    "profondeur_max", "surface_m2", "exposition", "methode_surface",
    "nature_objet", "type_sol", "type_mosaique", "st_enjeu", "st_etat_cons",
]
HABITAT_FIELDS = [
    "id_habitat", "cd_hab", "nom_cite", "determinateur", "recouvrement",
    "technique", "determination", "abondance", "sensibilite", "interet_com",
    "hab_enjeu", "hab_etat_cons",
]
FIELDS = STATION_FIELDS + HABITAT_FIELDS
NUMERIC_FIELDS = {
    "id_station", "altitude_min", "altitude_max", "profondeur_min",
    "profondeur_max", "surface_m2", "id_habitat", "cd_hab", "recouvrement",
}


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def flatten_cartography(stations, nomenclature_label=None, jdd_name=None,
                        role_label=None):
    """Renvoyer une liste de lignes (dicts) — une par habitat.

    Args:
        stations: liste de tuples ``(station, habitats, observers)`` tels que
            renvoyés par ``parse_server_station``.
        nomenclature_label: callable ``id_nomenclature -> libellé`` (ou None).
        jdd_name: libellé du jeu de données.
        role_label: callable ``id_role -> nom`` (numérisateur).

    Chaque dict contient toutes les clés de ``FIELDS`` (habitat à None si la
    station n'a pas d'habitat) plus ``_geom`` (WKT) et ``_geom_type``.
    """
    label = nomenclature_label or (lambda _i: None)
    role = role_label or (lambda _i: None)
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
        }
        for habitat in (habitats or [None]):
            row = dict.fromkeys(FIELDS)
            row.update(station_row)
            if habitat is not None:
                hab_eval = decode_eval(habitat.get("technical_precision") or "")
                recouvrement = habitat.get("recovery_percentage")
                if recouvrement is None:
                    recouvrement = _to_float(hab_eval.get("recouvrement"))
                row.update({
                    "id_habitat": habitat.get("id_habitat"),
                    "cd_hab": habitat.get("cd_hab"),
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
                })
            row["_geom"] = station.get("geom")
            row["_geom_type"] = station.get("geom_type")
            rows.append(row)
    return rows
