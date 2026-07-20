# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Construction du payload OccHab pour l'API GeoNature (module pur, testable).

Format validé de bout en bout contre une vraie instance GeoNature
(demo.geonature.fr) : GeoJSON Feature (geometry + properties), dates au format
'%Y-%m-%d', observers = [{'id_role': …}], habitats imbriqués, id_station/id_habitat
préservés pour les mises à jour. Création, mise à jour, suppression et
récupération (aller-retour) confirmées.

Réserve mineure : une instance OccHab très ancienne ou fortement personnalisée
pourrait diverger — le cas échéant, comparer avec un GET /occhab/stations/<id>/.
"""


def build_station_payload(station, habitats, observers, geom_geojson):
    """Construire le GeoJSON Feature attendu par POST /occhab/stations/.

    Le schéma station est un GeoAlchemyAutoSchema (feature_geometry='geom_4326') :
    la géométrie va dans 'geometry', tous les autres champs dans 'properties'.

    Args:
        station: dict de la station locale (t_stations).
        habitats: liste de dicts (t_habitats) rattachés.
        observers: liste de dicts (cor_station_observer) — transmis comme liste
            'observers' [{id_role}] (schéma Nested UserSchema) EN PLUS de
            'observers_txt'. Format validé contre demo.geonature.fr.
        geom_geojson: géométrie GeoJSON (dict) en EPSG:4326.

    Returns:
        dict Feature prêt à être sérialisé en JSON.
    """
    properties = {
        "id_station": station.get("id_station"),  # présent en mise à jour
        "id_dataset": station.get("id_dataset"),
        "station_name": station.get("station_name"),
        "date_min": _date_value(station.get("date_min")),
        "date_max": _date_value(station.get("date_max")),
        "observers_txt": station.get("observers_txt"),
        "altitude_min": station.get("altitude_min"),
        "altitude_max": station.get("altitude_max"),
        "area": station.get("area"),
        "id_nomenclature_exposure": station.get("id_nomenclature_exposure"),
        "id_nomenclature_area_surface_calculation": station.get(
            "id_nomenclature_area_surface_calculation"
        ),
        "id_nomenclature_geographic_object": station.get(
            "id_nomenclature_geographic_object"
        ),
        "comment": station.get("comment"),
        "depth_min": station.get("depth_min"),
        "depth_max": station.get("depth_max"),
        "id_nomenclature_type_sol": station.get("id_nomenclature_type_sol"),
        "id_nomenclature_type_mosaique_habitat": station.get(
            "id_nomenclature_type_mosaique_habitat"
        ),
        "habitats": [_habitat_payload(h) for h in habitats],
        # Observateurs = liste d'utilisateurs (schéma Nested UserSchema many).
        "observers": [
            {"id_role": o["id_role"]} for o in observers if o.get("id_role")
        ],
    }
    # On n'envoie pas les clés à None ni la liste d'observateurs vide.
    properties = {k: v for k, v in properties.items() if v not in (None, [])}
    return {
        "type": "Feature",
        "geometry": geom_geojson,
        "properties": properties,
    }


def _date_value(value):
    """Le schéma OccHab attend fields.DateTime('%Y-%m-%d') → date seule 'YYYY-MM-DD'."""
    return value.split("T")[0] if value else None


def _habitat_payload(habitat):
    fields = {
        # id présents si l'habitat vient du serveur → mise à jour (pas re-création)
        "id_habitat": habitat.get("id_habitat"),
        "unique_id_sinp_hab": habitat.get("unique_id_sinp_hab"),
        "cd_hab": habitat.get("cd_hab"),
        "nom_cite": habitat.get("nom_cite"),
        "id_nomenclature_collection_technique": habitat.get(
            "id_nomenclature_collection_technique"
        ),
        "determiner": habitat.get("determiner"),
        "recovery_percentage": habitat.get("recovery_percentage"),
        "technical_precision": habitat.get("technical_precision"),
        "id_nomenclature_determination_type": habitat.get(
            "id_nomenclature_determination_type"
        ),
        "id_nomenclature_abundance": habitat.get("id_nomenclature_abundance"),
        "id_nomenclature_sensitivity": habitat.get("id_nomenclature_sensitivity"),
        "id_nomenclature_community_interest": habitat.get(
            "id_nomenclature_community_interest"
        ),
    }
    return {k: v for k, v in fields.items() if v is not None}


def extract_id_station(response):
    """Extraire l'id_station renvoyé par l'API (formats JSON ou GeoJSON)."""
    if not isinstance(response, dict):
        return None
    if response.get("id_station"):
        return response["id_station"]
    if response.get("id"):  # feature_id='id_station' → Feature.id
        return response["id"]
    props = response.get("properties")
    if isinstance(props, dict) and props.get("id_station"):
        return props["id_station"]
    features = response.get("features")
    if isinstance(features, list) and features:
        return extract_id_station(features[0])
    return None


# ---------------------------------------------------------------------------
# Serveur → local : récupérer une station serveur pour l'éditer localement.
# ---------------------------------------------------------------------------
def _wkt_point(coord):
    return "%s %s" % (coord[0], coord[1])


def _wkt_ring(coords):
    return ", ".join(_wkt_point(c) for c in coords)


def _wkt_poly(rings):
    return ", ".join("(%s)" % _wkt_ring(r) for r in rings)


def geojson_to_wkt(geometry):
    """Convertir une géométrie GeoJSON (dict) en WKT. None si non gérée/vide."""
    if not isinstance(geometry, dict):
        return None
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if coords is None:
        return None
    try:
        if gtype == "Point":
            return "POINT (%s)" % _wkt_point(coords)
        if gtype == "LineString":
            return "LINESTRING (%s)" % _wkt_ring(coords)
        if gtype == "Polygon":
            return "POLYGON (%s)" % _wkt_poly(coords)
        if gtype == "MultiPoint":
            return "MULTIPOINT (%s)" % ", ".join("(%s)" % _wkt_point(c) for c in coords)
        if gtype == "MultiLineString":
            return "MULTILINESTRING (%s)" % ", ".join(
                "(%s)" % _wkt_ring(c) for c in coords
            )
        if gtype == "MultiPolygon":
            return "MULTIPOLYGON (%s)" % ", ".join("(%s)" % _wkt_poly(c) for c in coords)
    except (TypeError, IndexError):
        return None
    return None


def _geojson_geom_type(geometry):
    gtype = geometry.get("type", "") if isinstance(geometry, dict) else ""
    if "Point" in gtype:
        return "point"
    if "LineString" in gtype:
        return "line"
    if "Polygon" in gtype:
        return "polygon"
    return None


# Colonnes station reprises telles quelles depuis les properties serveur.
_STATION_PROP_KEYS = (
    "id_station", "unique_id_sinp_station", "id_dataset", "station_name",
    "observers_txt", "altitude_min", "altitude_max", "depth_min", "depth_max",
    "area", "comment", "id_nomenclature_exposure",
    "id_nomenclature_area_surface_calculation", "id_nomenclature_geographic_object",
    "id_nomenclature_type_sol", "id_nomenclature_type_mosaique_habitat",
)
_HABITAT_PROP_KEYS = (
    "id_habitat", "unique_id_sinp_hab", "cd_hab", "nom_cite", "determiner",
    "recovery_percentage", "technical_precision",
    "id_nomenclature_determination_type", "id_nomenclature_collection_technique",
    "id_nomenclature_abundance", "id_nomenclature_sensitivity",
    "id_nomenclature_community_interest",
)


def parse_server_station(feature):
    """Décomposer un GeoJSON Feature (détail station serveur) en dicts locaux.

    Retourne (station, habitats, observers), prêts pour create_station /
    add_habitat / add_observer.
    """
    if not isinstance(feature, dict):
        return {}, [], []
    props = feature.get("properties") or {}

    station = {k: props.get(k) for k in _STATION_PROP_KEYS if props.get(k) is not None}
    if not station.get("id_station") and feature.get("id"):
        station["id_station"] = feature["id"]
    for key in ("date_min", "date_max"):
        value = _date_value(props.get(key))
        if value:
            station[key] = value
    geometry = feature.get("geometry")
    wkt = geojson_to_wkt(geometry)
    if wkt:
        station["geom"] = wkt
        station["geom_type"] = _geojson_geom_type(geometry)

    habitats = []
    for hab in props.get("habitats") or []:
        habitats.append({k: hab.get(k) for k in _HABITAT_PROP_KEYS if hab.get(k) is not None})

    observers = []
    for obs in props.get("observers") or []:
        if not isinstance(obs, dict):
            continue
        name = obs.get("nom_complet") or (
            "%s %s" % (obs.get("prenom_role") or "", obs.get("nom_role") or "")
        ).strip()
        observers.append({"id_role": obs.get("id_role"), "observer_name": name or None})

    return station, habitats, observers
