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
from collections import Counter
from urllib.parse import urlsplit

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
#: `id_nomenclature_collection_technique`, `id_nomenclature_geographic_object`),
#: qu'un null ferait rejeter.
#:
#: `id_nomenclature_geographic_object` mérite un mot : la colonne est déclarée
#: `integer NOT NULL` (`pr_occhab.t_stations`), et le DEFAULT posé côté serveur
#: n'en dispense pas — un DEFAULT ne s'applique qu'à une colonne ABSENTE de
#: l'UPDATE, jamais contre un null explicite. Le modèle SQLAlchemy la donne
#: pourtant pour `Optional`, si bien que le schéma laisse passer le null et que
#: la violation n'éclate qu'en base, en 500 illisible. Vide en local veut donc
#: dire « ne pas y toucher » : la clé n'est pas envoyée, GeoNature garde sa
#: valeur. Le formulaire, lui, pose « Ne sait pas » sur les stations neuves.
EFFACABLES_STATION = frozenset({
    "station_name", "observers_txt", "altitude_min", "altitude_max",
    "depth_min", "depth_max", "area", "comment",
    "id_nomenclature_exposure", "id_nomenclature_area_surface_calculation",
    "id_nomenclature_type_sol", "id_nomenclature_type_mosaique_habitat",
    "observers",
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


#: Colonnes que GeoNature renseigne lui-même quand le plugin ne les envoie pas
#: (DEFAULT de colonne). Sans relecture, la copie locale les garde vides à vie :
#: le champ s'affiche « non renseigné » dans QGIS alors que la station en porte
#: une valeur sur le serveur.
COMBLABLES_STATION = (
    "id_nomenclature_geographic_object", "id_nomenclature_type_sol",
    "id_nomenclature_type_mosaique_habitat",
)


def combler_defauts_serveur(locale, serveur):
    """Colonnes vides en local que le serveur, lui, a renseignées.

    Module pur, appelé après un envoi réussi sur le détail déjà rechargé pour
    l'empreinte. Ne rend QUE les trous : recopier la station entière ramènerait
    le commentaire serveur avec son bloc ANA-EVAL et écraserait
    `validation_status`, dont la colonne locale fait foi.
    """
    return {
        cle: serveur[cle]
        for cle in COMBLABLES_STATION
        if not locale.get(cle) and serveur.get(cle) is not None
    }


#: Couples min/max contraints côté GeoNature (`t_stations_altitude_max`,
#: `t_stations_depth_max`, `t_stations_date_max`) : un maximum inférieur au
#: minimum y est rejeté. Les dates se comparent en ISO, sur le jour seul.
COUPLES_MIN_MAX = (
    ("altitude_min", "altitude_max", "altitude"),
    ("depth_min", "depth_max", "profondeur"),
    ("date_min", "date_max", "dates"),
)


def mesures_incoherentes(station):
    """Libellés des couples min/max inversés d'une station (vide si tout va bien).

    Module pur. La contrainte existe côté serveur mais s'y manifeste par une
    erreur 500 illisible : autant la faire respecter avant l'envoi.
    """
    fautifs = []
    for cle_min, cle_max, libelle in COUPLES_MIN_MAX:
        mini, maxi = station.get(cle_min), station.get(cle_max)
        if cle_min == "date_min" and mini and maxi:
            # « 2026-06-12 » et « 2026-06-12 00:00:00 » désignent le même jour.
            mini, maxi = str(mini)[:10], str(maxi)[:10]
        if mini is not None and maxi is not None and mini > maxi:
            fautifs.append("%s (min %s > max %s)" % (libelle, mini, maxi))
    return fautifs


#: Longueur maximale des colonnes texte de GeoNature (schéma pr_occhab). Au-delà,
#: PostgreSQL refuse l'écriture et GeoNature répond « HTTP 500 » pour la
#: station ENTIÈRE, sans dire quel champ dépasse. `technical_precision` porte le
#: bloc ANA-EVAL : enjeu, état, critère, remarque, PEE et correspondances s'y
#: additionnent, et 500 caractères s'atteignent avec un critère un peu détaillé.
LONGUEURS_MAX_STATION = (
    ("station_name", 1000, "nom de la station"),
    ("observers_txt", 500, "observateurs"),
)
LONGUEURS_MAX_HABITAT = (
    ("nom_cite", 500, "nom cité"),
    ("determiner", 500, "déterminateur"),
    ("technical_precision", 500,
     "précision technique, avec enjeu, état, critère, remarque, PEE et "
     "correspondances"),
)


def textes_trop_longs(objet, limites):
    """[(libellé, longueur, maximum)] des textes de `objet` trop longs pour GeoNature."""
    trop = []
    for cle, maximum, libelle in limites:
        valeur = (objet or {}).get(cle)
        if valeur is not None and len(str(valeur)) > maximum:
            trop.append((libelle, len(str(valeur)), maximum))
    return trop


def _en_2d(geometrie):
    """GeoJSON sans Z ni M : GeoNature refuse toute géométrie qui n'est pas 2D.

    Une entité reprise d'une couche 3D (BD TOPO…) gardait son altitude dans
    chaque coordonnée, et la contrainte `enforce_dims_geom_4326` refusait la
    station avec une erreur 500.
    """
    def plat(coordonnees):
        if coordonnees and isinstance(coordonnees[0], (int, float)):
            return list(coordonnees[:2])
        return [plat(c) for c in coordonnees]

    if not isinstance(geometrie, dict) or "coordinates" not in geometrie:
        return geometrie
    return dict(geometrie, coordinates=plat(geometrie["coordinates"]))


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
    if geom_geojson is None:
        # Station créée « sans géométrie (à tracer plus tard) » : la colonne
        # serveur est NOT NULL, l'envoi échouait en « HTTP 500 ».
        raise ValueError(
            "Station sans géométrie : tracez-la (menu « Géométrie ») avant de la "
            "synchroniser."
        )
    geom_geojson = _en_2d(geom_geojson)
    if not coordonnees_wgs84(geom_geojson):
        raise ValueError(
            "Géométrie hors du domaine WGS84 (longitude ±180, latitude ±90) : "
            "vérifiez le SCR de la couche d'origine."
        )
    trop_longs = textes_trop_longs(station, LONGUEURS_MAX_STATION)
    for numero, habitat in enumerate(habitats or [], 1):
        trop_longs += [
            ("habitat %d « %s » : %s" % (numero, habitat.get("nom_cite") or "?",
                                         libelle), longueur, maximum)
            for libelle, longueur, maximum in textes_trop_longs(
                habitat, LONGUEURS_MAX_HABITAT)
        ]
    if trop_longs:
        raise ValueError(
            "Texte trop long pour GeoNature — %s. Raccourcissez-le dans la fiche."
            % " ; ".join("%s : %d caractères (%d au plus)" % t for t in trop_longs)
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
    """Extraire l'id_station renvoyé par l'API (formats JSON ou GeoJSON).

    Une seule station, ou rien. Une LISTE (FeatureCollection) n'est pas la
    réponse d'une création — par exemple un POST changé en GET par une
    redirection : en prendre le premier élément liait la station locale à une
    station tierce, que les envois suivants écrasaient.
    """
    if not isinstance(response, dict) or "features" in response:
        return None
    if response.get("id_station"):
        return response["id_station"]
    if response.get("id"):  # feature_id='id_station' → Feature.id
        return response["id"]
    props = response.get("properties")
    if isinstance(props, dict) and props.get("id_station"):
        return props["id_station"]
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


def _uuid_normalise(valeur):
    """UUID comparable, quelle que soit sa casse ou son type (texte / uuid.UUID)."""
    return str(valeur).strip().lower() if valeur else None


def apparier_habitats(locaux, serveur, par_contenu=False):
    """Retrouver, pour chaque habitat local, son habitat sur GeoNature.

    Renvoie `{index dans locaux: habitat serveur}`. Critères, dans l'ordre : même
    `unique_id_sinp_hab`, puis même `id_habitat`, puis — si `par_contenu` — même
    couple (cd_hab, nom cité), pour les seuls habitats locaux SANS `id_habitat`
    et seulement si le couple est unique des deux côtés : deux habitats
    identiques ne se distinguent pas, mieux vaut alors n'en rattacher aucun.
    Un habitat serveur ne sert qu'une fois.
    """
    paires = {}
    libres = list(range(len(serveur or [])))

    criteres = (
        lambda h: _uuid_normalise(h.get("unique_id_sinp_hab")),
        lambda h: h.get("id_habitat") or None,
    )
    for critere in criteres:
        par_cle = {}
        for j in libres:
            cle = critere(serveur[j])
            if cle is not None:
                par_cle.setdefault(cle, j)
        for i, habitat in enumerate(locaux or []):
            if i in paires:
                continue
            cle = critere(habitat)
            j = par_cle.get(cle) if cle is not None else None
            if j is not None and j in libres:
                paires[i] = serveur[j]
                libres.remove(j)

    if par_contenu:
        def contenu(h):
            return (h.get("cd_hab"), (h.get("nom_cite") or "").strip())

        candidats = [
            i for i, h in enumerate(locaux or [])
            if i not in paires and not h.get("id_habitat")
        ]
        compte_locaux = Counter(contenu(locaux[i]) for i in candidats)
        compte_serveur = Counter(contenu(serveur[j]) for j in libres)
        for i in candidats:
            cle = contenu(locaux[i])
            if compte_locaux.get(cle) != 1 or compte_serveur.get(cle) != 1:
                continue
            j = next(j for j in libres if contenu(serveur[j]) == cle)
            paires[i] = serveur[j]
            libres.remove(j)
    return paires


def identites_habitats(locaux, serveur, par_contenu=False, nouvel_uuid=None):
    """Identité GeoNature de chaque habitat local : `{id local: (id_habitat, uuid)}`.

    GeoNature traite un habitat sans `id_habitat` comme une CRÉATION, et supprime
    de la station ceux qu'il ne voit plus revenir. Sans identité, chaque mise à
    jour effaçait donc tous les habitats et les recréait, sous de nouveaux
    identifiants SINP.

    Un habitat retrouvé sur le serveur (cf. `apparier_habitats`) prend son
    identifiant et son UUID ; les autres gardent les leurs, et reçoivent un UUID
    neuf par `nouvel_uuid()` s'ils n'en ont pas : GeoNature reprend tel quel un
    UUID fourni, c'est par lui qu'on retrouve l'habitat après l'envoi. Les
    habitats sans identifiant local (`id`) sont ignorés.
    """
    paires = apparier_habitats(locaux, serveur, par_contenu=par_contenu)
    identites = {}
    for i, habitat in enumerate(locaux or []):
        if habitat.get("id") is None:
            continue
        retrouve = paires.get(i) or {}
        id_habitat = retrouve.get("id_habitat") or habitat.get("id_habitat")
        uuid_hab = (
            retrouve.get("unique_id_sinp_hab") or habitat.get("unique_id_sinp_hab")
        )
        if not uuid_hab and nouvel_uuid is not None:
            uuid_hab = nouvel_uuid()
        identites[habitat["id"]] = (id_habitat, str(uuid_hab) if uuid_hab else None)
    return identites


def cle_serveur(api_url):
    """Identité d'un serveur GeoNature, stable d'une saisie de l'URL à l'autre.

    Hôte en minuscules, port par défaut omis, chemin sans « / » final, schéma
    ignoré : « https://Geo.exemple.fr:443/geonature/api/ » et
    « http://geo.exemple.fr/geonature/api » désignent le même serveur — passer
    en HTTPS ne doit pas couper une base de ses stations. None si l'URL est vide.
    """
    texte = (api_url or "").strip()
    if not texte:
        return None
    morceaux = urlsplit(texte if "://" in texte else "//" + texte)
    hote = (morceaux.hostname or "").lower()
    if morceaux.port and morceaux.port not in (80, 443):
        hote = "%s:%d" % (hote, morceaux.port)
    return (hote + morceaux.path.rstrip("/")) or None
