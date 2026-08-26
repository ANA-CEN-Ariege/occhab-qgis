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
import hashlib
import json

try:  # importable dans le paquet (plugin) comme en isolation (tests)
    from ..processing.eval_fields import decode_eval, merge_eval
    from ..processing.referentiels import BROUILLON
except ImportError:  # pragma: no cover - repli hors paquet
    from eval_fields import decode_eval, merge_eval
    from referentiels import BROUILLON


def coordonnees_wgs84(geojson):
    """Toutes les coordonnées d'un GeoJSON tiennent-elles dans le domaine WGS84 ?

    Longitude dans [-180, 180], latitude dans [-90, 90]. Module pur : la
    vérification côté QGIS vit dans `processing.geometry`, mais l'envoi doit
    pouvoir se protéger sans PyQGIS.
    """
    if not isinstance(geojson, dict):
        return True  # rien d'exploitable à vérifier

    def parcourir(valeur):
        if not isinstance(valeur, (list, tuple)) or not valeur:
            return True
        if isinstance(valeur[0], (list, tuple)):
            return all(parcourir(element) for element in valeur)
        if len(valeur) < 2 or not all(
            isinstance(nombre, (int, float)) for nombre in valeur[:2]
        ):
            return True  # pas une position : ne pas juger
        lon, lat = valeur[0], valeur[1]
        return -180 <= lon <= 180 and -90 <= lat <= 90

    return parcourir(geojson.get("coordinates"))


#: Champs qu'une MISE À JOUR envoie **même vides**, pour qu'un champ effacé dans
#: QGIS le soit aussi sur GeoNature.
#:
#: Le serveur charge le payload avec `unknown=EXCLUDE` et n'écrit que les clés
#: reçues : une clé absente laisse la colonne telle quelle. Retirer les valeurs
#: nulles rendait donc tout effacement impossible — le champ repassait à
#: « non renseigné » en local, GeoNature gardait l'ancienne valeur, et la
#: synchronisation se déclarait réussie. Cas rencontré sur « Habitat d'intérêt
#: communautaire », mais la règle valait pour chaque champ facultatif.
#:
#: N'y figurent que les colonnes que GeoNature accepte à NULL. En sont exclus :
#: les identifiants (`id_station`, `id_habitat`, `unique_id_sinp_hab`), qu'un
#: null détacherait de leur enregistrement serveur, et les colonnes NOT NULL
#: (`id_dataset`, `date_min`, `date_max`, `cd_hab`, `nom_cite`,
#: `id_nomenclature_collection_technique`), qu'un null ferait rejeter.
EFFACABLES_STATION = frozenset({
    "station_name", "observers_txt", "altitude_min", "altitude_max",
    "depth_min", "depth_max", "area", "comment",
    "id_nomenclature_exposure", "id_nomenclature_area_surface_calculation",
    "id_nomenclature_geographic_object", "id_nomenclature_type_sol",
    "id_nomenclature_type_mosaique_habitat", "observers",
})
EFFACABLES_HABITAT = frozenset({
    "determiner", "recovery_percentage", "technical_precision",
    "id_nomenclature_determination_type", "id_nomenclature_abundance",
    "id_nomenclature_sensitivity", "id_nomenclature_community_interest",
})


def _sans_vides(champs, effacables):
    """Retirer les valeurs vides, sauf celles qui effacent un champ côté serveur.

    `effacables` est vide à la création : rien n'y est à effacer, et omettre un
    champ laisse GeoNature appliquer ses valeurs par défaut (nature de l'objet
    géographique, type de sol…), ce qu'un null explicite empêcherait.
    """
    return {
        cle: valeur for cle, valeur in champs.items()
        if valeur not in (None, []) or cle in effacables
    }


#: Couples min/max contraints côté GeoNature (`t_stations_altitude_max`,
#: `t_stations_depth_max`) : un maximum inférieur au minimum y est rejeté.
COUPLES_MIN_MAX = (
    ("altitude_min", "altitude_max", "altitude"),
    ("depth_min", "depth_max", "profondeur"),
)


def mesures_incoherentes(station):
    """Libellés des couples min/max inversés d'une station (vide si tout va bien).

    Module pur. La contrainte existe côté serveur mais s'y manifeste par une
    erreur 500 illisible : autant la faire respecter avant l'envoi.
    """
    fautifs = []
    for cle_min, cle_max, libelle in COUPLES_MIN_MAX:
        mini, maxi = station.get(cle_min), station.get(cle_max)
        if mini is not None and maxi is not None and mini > maxi:
            fautifs.append("%s (min %s > max %s)" % (libelle, mini, maxi))
    return fautifs


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

    Raises:
        ValueError: géométrie hors du domaine WGS84. Dernier filet avant l'envoi :
            une station reprise d'une couche au SCR inconnu portait des mètres
            présentés comme des degrés. Le serveur la refusait au calcul
            d'altitude, mais rien n'empêchait de la SYNCHRONISER telle quelle.
            La synchro traite les stations une par une : celle-ci échoue avec un
            message clair, les autres passent.
    """
    if geom_geojson is not None and not coordonnees_wgs84(geom_geojson):
        raise ValueError(
            "Géométrie hors du domaine WGS84 (longitude ±180, latitude ±90) : "
            "vérifiez le SCR de la couche d'origine."
        )
    fautifs = mesures_incoherentes(station)
    if fautifs:
        raise ValueError(
            "Mesures incohérentes, refusées par GeoNature : %s." % ", ".join(fautifs)
        )
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
        # L'état métier n'a pas de champ natif : il voyage dans le bloc ANA-EVAL.
        # La colonne locale fait foi, le commentaire n'est que son transport —
        # d'où la ré-injection systématique ici plutôt qu'un stockage en double.
        "comment": merge_eval(
            station.get("comment"), statut=station.get("validation_status")
        ) or None,
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
    # Création : on n'envoie ni les clés à None ni la liste d'observateurs vide.
    # Mise à jour : les champs facultatifs partent même vides, sinon rien ne
    # s'efface jamais côté serveur (cf. EFFACABLES_STATION).
    properties = _sans_vides(
        properties,
        EFFACABLES_STATION if station.get("id_station") else frozenset(),
    )
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
    # Un habitat sans `id_habitat` est une création : rien à y effacer.
    return _sans_vides(
        fields, EFFACABLES_HABITAT if habitat.get("id_habitat") else frozenset()
    )


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
    # État métier : extrait du bloc puis RETIRÉ du commentaire local, pour que la
    # colonne `validation_status` reste la seule source de vérité en local.
    commentaire = props.get("comment")
    station["validation_status"] = decode_eval(commentaire).get("statut") or BROUILLON
    nettoye = merge_eval(commentaire, statut=None)
    if nettoye:
        station["comment"] = nettoye
    else:
        station.pop("comment", None)
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


def server_fingerprint(station, habitats, observers):
    """Empreinte stable de l'état SERVEUR d'une station (détection de conflit).

    Calculée uniquement à partir des champs déjà normalisés par
    `parse_server_station` (donc validés contre une vraie instance), sans dépendre
    d'un champ d'horodatage serveur non garanti. Deux GET successifs de la même
    station inchangée produisent la même empreinte ; toute divergence côté serveur
    la fait changer. Comparer `server_fingerprint(parse_server_station(detail))`
    à l'empreinte mémorisée au dernier import/synchro révèle un conflit.
    """
    def _norm(mapping):
        return {k: mapping[k] for k in sorted(mapping)}

    def _sorted(items):
        rows = [_norm(i) for i in (items or []) if isinstance(i, dict)]
        return sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))

    blob = json.dumps(
        {
            "station": _norm(station or {}),
            "habitats": _sorted(habitats),
            "observers": _sorted(observers),
        },
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
