# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du module pur `payload` (construction et lecture du GeoJSON OccHab)."""
import eval_fields
import payload as p


def test_date_value():
    assert p._date_value("2025-05-07T00:00:00") == "2025-05-07"
    assert p._date_value("2025-05-07") == "2025-05-07"
    assert p._date_value(None) is None


def test_build_station_payload_structure():
    station = {
        "id_station": 42, "id_dataset": 3, "station_name": "S",
        "date_min": "2025-05-07", "observers_txt": "X", "comment": None,
    }
    habitats = [{"cd_hab": 10, "nom_cite": "h"}]
    observers = [{"id_role": 5}]
    geom = {"type": "Point", "coordinates": [1, 2]}

    feature = p.build_station_payload(station, habitats, observers, geom)

    assert feature["type"] == "Feature"
    assert feature["geometry"] == geom
    props = feature["properties"]
    assert props["id_station"] == 42
    assert props["id_dataset"] == 3
    assert props["date_min"] == "2025-05-07"
    assert props["observers"] == [{"id_role": 5}]
    assert props["habitats"][0]["cd_hab"] == 10
    # Station déjà sur le serveur : un commentaire vide part explicitement à
    # null, sans quoi l'ancien resterait en place (cf. tests d'effacement).
    assert props["comment"] is None


def test_build_station_payload_drops_empty_observers():
    feature = p.build_station_payload({"id_dataset": 3}, [], [], None)
    assert "observers" not in feature["properties"]


def test_creation_ne_transmet_aucune_valeur_vide():
    """À la création, les champs vides sont omis : GeoNature applique ses défauts."""
    station = {"id_dataset": 3, "station_name": None, "comment": None}
    habitats = [{"cd_hab": 10, "nom_cite": "h", "determiner": None}]

    props = p.build_station_payload(station, habitats, [], None)["properties"]

    assert "station_name" not in props
    assert "comment" not in props
    assert "id_nomenclature_type_sol" not in props
    assert "determiner" not in props["habitats"][0]


def test_mise_a_jour_efface_un_champ_vide():
    """Un champ vidé dans QGIS doit partir à null, sinon rien ne s'efface jamais.

    Le serveur n'écrit que les clés reçues : une clé retirée du payload laissait
    la colonne à sa valeur d'avant. « Habitat d'intérêt communautaire » effacé
    dans le tableau réapparaissait ainsi intact dans GeoNature, la synchro se
    déclarant réussie.
    """
    station = {"id_station": 42, "id_dataset": 3, "station_name": None,
               "id_nomenclature_type_sol": None}
    habitats = [{
        "id_habitat": 7, "cd_hab": 10, "nom_cite": "h",
        "id_nomenclature_community_interest": None, "determiner": None,
    }]

    props = p.build_station_payload(station, habitats, [], None)["properties"]

    assert props["station_name"] is None
    assert props["id_nomenclature_type_sol"] is None
    habitat = props["habitats"][0]
    assert habitat["id_nomenclature_community_interest"] is None
    assert habitat["determiner"] is None


def test_mise_a_jour_ne_met_jamais_les_identifiants_a_null():
    """Un null sur ces clés détacherait la station de son enregistrement serveur
    ou serait rejeté par une colonne NOT NULL."""
    station = {"id_station": 42, "id_dataset": 3, "date_min": None}
    habitats = [{"id_habitat": 7, "cd_hab": 10, "nom_cite": "h",
                 "unique_id_sinp_hab": None,
                 "id_nomenclature_collection_technique": None}]

    props = p.build_station_payload(station, habitats, [], None)["properties"]

    assert "date_min" not in props
    habitat = props["habitats"][0]
    assert "unique_id_sinp_hab" not in habitat
    assert "id_nomenclature_collection_technique" not in habitat


def test_mise_a_jour_n_efface_jamais_la_nature_d_objet_geographique():
    """`t_stations.id_nomenclature_geographic_object` est NOT NULL.

    Le DEFAULT posé côté serveur n'en dispense pas : il ne joue que sur une
    colonne ABSENTE de l'UPDATE, jamais contre un null explicite — que le schéma
    laisse passer (le modèle la donne pour `Optional`) et que la base rejette en
    500. Vide en local veut donc dire « ne pas y toucher ».
    """
    station = {"id_station": 42, "id_dataset": 3,
               "id_nomenclature_geographic_object": None}

    props = p.build_station_payload(station, [], [], None)["properties"]

    assert "id_nomenclature_geographic_object" not in props


def test_mise_a_jour_transmet_la_nature_d_objet_geographique_renseignee():
    """Non effaçable ne veut pas dire non modifiable."""
    station = {"id_station": 42, "id_dataset": 3,
               "id_nomenclature_geographic_object": 614}

    props = p.build_station_payload(station, [], [], None)["properties"]

    assert props["id_nomenclature_geographic_object"] == 614


def test_combler_defauts_serveur_ne_rend_que_les_trous():
    """Après un envoi, on récupère ce que GeoNature a posé sur les champs omis.

    Uniquement les colonnes restées vides : recopier la station entière
    ramènerait le commentaire serveur avec son bloc ANA-EVAL et écraserait
    `validation_status`, dont la colonne locale fait foi.
    """
    locale = {
        "id_nomenclature_geographic_object": None,
        "id_nomenclature_type_sol": 475,
        "comment": "note locale",
        "validation_status": "valide",
    }
    serveur = {
        "id_nomenclature_geographic_object": 614,
        "id_nomenclature_type_sol": 999,
        "comment": "[ANA-EVAL] …",
        "validation_status": "brouillon",
    }

    assert p.combler_defauts_serveur(locale, serveur) == {
        "id_nomenclature_geographic_object": 614
    }


def test_combler_defauts_serveur_sans_valeur_serveur():
    """`parse_server_station` retire les clés nulles : rien à combler."""
    locale = {"id_nomenclature_geographic_object": None}

    assert p.combler_defauts_serveur(locale, {}) == {}


def test_habitat_neuf_dans_une_station_connue_reste_une_creation():
    """Sans `id_habitat`, l'habitat est créé : ses champs vides restent omis."""
    station = {"id_station": 42, "id_dataset": 3}
    habitats = [{"cd_hab": 10, "nom_cite": "h", "determiner": None}]

    habitat = p.build_station_payload(
        station, habitats, [], None
    )["properties"]["habitats"][0]

    assert "determiner" not in habitat


def test_mise_a_jour_efface_les_observateurs():
    station = {"id_station": 42, "id_dataset": 3}

    props = p.build_station_payload(station, [], [], None)["properties"]

    assert props["observers"] == []


def test_extract_id_station():
    assert p.extract_id_station({"id_station": 7}) == 7
    assert p.extract_id_station({"id": 8}) == 8
    assert p.extract_id_station({"properties": {"id_station": 9}}) == 9
    assert p.extract_id_station({"features": [{"id_station": 10}]}) == 10
    assert p.extract_id_station("pas un dict") is None


def test_geojson_to_wkt():
    assert p.geojson_to_wkt({"type": "Point", "coordinates": [1, 2]}) == "POINT (1 2)"
    assert p.geojson_to_wkt(
        {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    ) == "LINESTRING (0 0, 1 1)"
    poly = p.geojson_to_wkt(
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    )
    assert poly == "POLYGON ((0 0, 1 0, 1 1, 0 0))"
    assert p.geojson_to_wkt({"type": "Inconnu"}) is None
    assert p.geojson_to_wkt(None) is None


def test_parse_server_station_roundtrip():
    feature = {
        "type": "Feature",
        "id": 42,
        "geometry": {"type": "Point", "coordinates": [1.5, 43.0]},
        "properties": {
            "id_station": 42, "id_dataset": 3, "station_name": "S",
            "date_min": "2025-05-07T00:00:00",
            "habitats": [{"id_habitat": 1, "cd_hab": 10, "nom_cite": "h"}],
            "observers": [{"id_role": 5, "nom_complet": "Roy Cédric"}],
        },
    }
    station, habitats, observers = p.parse_server_station(feature)

    assert station["id_station"] == 42
    assert station["geom"] == "POINT (1.5 43.0)"
    assert station["geom_type"] == "point"
    assert station["date_min"] == "2025-05-07"
    assert habitats[0]["cd_hab"] == 10
    assert observers[0]["id_role"] == 5
    assert observers[0]["observer_name"] == "Roy Cédric"


def test_parse_server_station_bad_input():
    assert p.parse_server_station("pas un dict") == ({}, [], [])


def test_server_fingerprint_stable_and_sensitive():
    station = {"id_station": 42, "station_name": "A", "geom": "POINT (1 2)"}
    habitats = [{"id_habitat": 1, "cd_hab": 10}, {"id_habitat": 2, "cd_hab": 20}]
    observers = [{"id_role": 5}, {"id_role": 7}]

    fingerprint = p.server_fingerprint(station, habitats, observers)

    # Insensible à l'ordre des listes.
    assert fingerprint == p.server_fingerprint(
        dict(station), list(reversed(habitats)), list(reversed(observers))
    )
    # Sensible à un changement de contenu.
    assert fingerprint != p.server_fingerprint(
        dict(station, station_name="B"), habitats, observers
    )
    assert len(fingerprint) == 64  # SHA-256 hexdigest


# --------------------------------------------- aller-retour de l'état métier
def test_statut_injecte_dans_le_commentaire_envoye():
    """Aucun champ natif pour l'état métier : il voyage dans le bloc ANA-EVAL."""
    feature = p.build_station_payload(
        {"id_dataset": 3, "comment": "Note de terrain.",
         "validation_status": "valide"},
        [], [], {"type": "Point", "coordinates": [1, 2]},
    )

    envoye = feature["properties"]["comment"]
    assert "Note de terrain." in envoye
    assert eval_fields.decode_eval(envoye)["statut"] == "valide"


def test_statut_n_ecrase_pas_les_autres_champs_du_bloc():
    comment = eval_fields.encode_eval("Note.", enjeu="fort", zone_humide=True)

    feature = p.build_station_payload(
        {"id_dataset": 3, "comment": comment, "validation_status": "brouillon"},
        [], [], {"type": "Point", "coordinates": [1, 2]},
    )

    codes = eval_fields.decode_eval(feature["properties"]["comment"])
    # `True` est l'ANCIEN format du champ, encore présent dans les stations déjà
    # synchronisées : il se relit en « oui ».
    assert codes == {"enjeu": "fort", "zone_humide": "oui", "statut": "brouillon"}


def test_statut_relu_du_serveur_et_retire_du_commentaire():
    """En local, la colonne fait foi : le commentaire ne doit pas porter le statut."""
    comment = eval_fields.encode_eval("Note.", enjeu="fort", statut="valide")
    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [1, 2]},
        "properties": {"id_station": 7, "id_dataset": 3, "comment": comment},
    }

    station, _habitats, _observers = p.parse_server_station(feature)

    assert station["validation_status"] == "valide"
    assert "statut" not in eval_fields.decode_eval(station["comment"])
    assert eval_fields.decode_eval(station["comment"])["enjeu"] == "fort"
    assert "Note." in station["comment"]


def test_station_serveur_sans_statut_est_un_brouillon():
    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [1, 2]},
        "properties": {"id_station": 7, "id_dataset": 3},
    }

    station, _h, _o = p.parse_server_station(feature)

    assert station["validation_status"] == "brouillon"
    assert "comment" not in station


def test_aller_retour_complet_du_statut():
    locale = {"id_dataset": 3, "comment": "Note.", "validation_status": "valide"}

    feature = p.build_station_payload(
        locale, [], [], {"type": "Point", "coordinates": [1, 2]})
    feature["properties"]["id_station"] = 7
    revenue, _h, _o = p.parse_server_station(feature)

    assert revenue["validation_status"] == "valide"
    assert revenue["comment"] == "Note."


# ------------------------------------------- garde-fou géométrie WGS84
def test_coordonnees_wgs84_accepte_les_degres():
    assert p.coordonnees_wgs84({"type": "Point", "coordinates": [1.15, 43.10]})
    assert p.coordonnees_wgs84(
        {"type": "Polygon", "coordinates": [[[1.1, 43.1], [1.2, 43.1], [1.2, 43.2],
                                             [1.1, 43.1]]]}
    )
    assert p.coordonnees_wgs84({"type": "Point", "coordinates": [-180, -90]})


def test_coordonnees_wgs84_refuse_des_metres():
    """Le cas réel : une couche en UTM 31N reprise sans reprojection."""
    assert not p.coordonnees_wgs84(
        {"type": "Point", "coordinates": [349907.277, 4774384.332]}
    )
    assert not p.coordonnees_wgs84(
        {"type": "Polygon", "coordinates": [[[349907.0, 4774384.0], [1.1, 43.1]]]}
    )


def test_payload_refuse_une_geometrie_hors_wgs84():
    """Sans ce filet, la station partait telle quelle sur GeoNature."""
    station = {"id_dataset": 3, "station_name": "S"}
    geom = {"type": "Point", "coordinates": [349907.277, 4774384.332]}
    try:
        p.build_station_payload(station, [], [], geom)
    except ValueError as exc:
        assert "WGS84" in str(exc)
    else:
        raise AssertionError("une géométrie en mètres aurait dû être refusée")


def test_payload_accepte_une_geometrie_valide():
    station = {"id_dataset": 3, "station_name": "S"}
    geom = {"type": "Point", "coordinates": [1.15, 43.10]}
    feature = p.build_station_payload(station, [], [], geom)
    assert feature["geometry"] == geom


# ------------------------------------------- garde-fou mesures min/max
def test_mesures_incoherentes_detecte_le_cas_reel():
    """Le cas rencontré : altitude_min 344 > altitude_max 343."""
    fautifs = p.mesures_incoherentes(
        {"altitude_min": 344, "altitude_max": 343, "depth_min": 1, "depth_max": 76}
    )
    assert len(fautifs) == 1
    assert "altitude" in fautifs[0]


def test_mesures_incoherentes_accepte_le_normal():
    assert p.mesures_incoherentes({"altitude_min": 343, "altitude_max": 344}) == []
    assert p.mesures_incoherentes({"altitude_min": 500, "altitude_max": 500}) == []
    # Non renseigné : rien à comparer.
    assert p.mesures_incoherentes({"altitude_min": 344, "altitude_max": None}) == []
    assert p.mesures_incoherentes({}) == []


def test_mesures_incoherentes_couvre_la_profondeur():
    fautifs = p.mesures_incoherentes({"depth_min": 76, "depth_max": 1})
    assert len(fautifs) == 1 and "profondeur" in fautifs[0]


def test_payload_refuse_des_mesures_inversees():
    """Sans ce filet : erreur 500 PostgreSQL illisible à la synchro."""
    station = {"id_dataset": 3, "altitude_min": 344, "altitude_max": 343}
    geom = {"type": "Point", "coordinates": [1.15, 43.10]}
    try:
        p.build_station_payload(station, [], [], geom)
    except ValueError as exc:
        assert "altitude" in str(exc)
    else:
        raise AssertionError("des mesures inversées auraient dû être refusées")
