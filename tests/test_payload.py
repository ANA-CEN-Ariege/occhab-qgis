# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du module pur `payload` (construction et lecture du GeoJSON OccHab)."""
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
    assert "comment" not in props  # les valeurs None sont retirées


def test_build_station_payload_drops_empty_observers():
    feature = p.build_station_payload({"id_dataset": 3}, [], [], None)
    assert "observers" not in feature["properties"]


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
