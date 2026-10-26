# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de la conversion GeoJSON → WKT (module pur `geojson_wkt`).

Pourquoi ce module existe : `QgsJsonUtils.geometryFromGeoJson()` n'apparaît qu'en
QGIS 3.36, alors que l'extension annonce prendre en charge la 3.28. Sur un poste
Windows en 3.28, charger un export levait un `AttributeError` et la couche ne se
chargeait pas du tout.
"""
import geojson_wkt as gw


def test_polygone():
    geom = {"type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    assert gw.wkt(geom) == "POLYGON ((0 0, 1 0, 1 1, 0 0))"


def test_polygone_a_trou():
    geom = {"type": "Polygon", "coordinates": [
        [[0, 0], [4, 0], [4, 4], [0, 0]],
        [[1, 1], [2, 1], [2, 2], [1, 1]],
    ]}
    assert gw.wkt(geom) == (
        "POLYGON ((0 0, 4 0, 4 4, 0 0), (1 1, 2 1, 2 2, 1 1))")


def test_multipolygone():
    geom = {"type": "MultiPolygon", "coordinates": [
        [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        [[[5, 5], [6, 5], [6, 6], [5, 5]]],
    ]}
    assert gw.wkt(geom) == (
        "MULTIPOLYGON (((0 0, 1 0, 1 1, 0 0)), ((5 5, 6 5, 6 6, 5 5)))")


def test_point_ligne():
    assert gw.wkt({"type": "Point", "coordinates": [1.5, 43.25]}) == \
        "POINT (1.5 43.25)"
    assert gw.wkt({"type": "LineString", "coordinates": [[0, 0], [1, 2]]}) == \
        "LINESTRING (0 0, 1 2)"


def test_les_degres_gardent_leurs_decimales():
    """Une septième décimale vaut encore un centimètre en Lambert comme en WGS84."""
    geom = {"type": "Point", "coordinates": [1.9045213, 43.0123456]}
    assert gw.wkt(geom) == "POINT (1.9045213 43.0123456)"


def test_pas_de_notation_scientifique():
    """L'analyseur WKT de QGIS refuse « 1e-05 »."""
    rendu = gw.wkt({"type": "Point", "coordinates": [0.00001, -0.000002]})
    assert "e" not in rendu.lower()
    assert rendu == "POINT (0.00001 -0.000002)"


def test_altitude_ignoree():
    """Ni les surfaces, ni les bandes, ni le damier n'ont besoin du Z."""
    assert gw.wkt({"type": "Point", "coordinates": [1, 2, 350]}) == "POINT (1 2)"


def test_geometrie_absente_ou_illisible():
    for valeur in (None, {}, [], "POLYGON", {"type": "Inconnu", "coordinates": []},
                   {"type": "Polygon", "coordinates": []},
                   {"type": "Point", "coordinates": [1]},
                   {"type": "Point", "coordinates": ["a", "b"]}):
        assert gw.wkt(valeur) is None, valeur


def test_collection():
    geom = {"type": "GeometryCollection", "geometries": [
        {"type": "Point", "coordinates": [0, 0]},
        {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
    ]}
    assert gw.wkt(geom) == (
        "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (0 0, 1 1))")


# --- Couches d'export : familles de géométrie et projection --------------------
def _f(type_):
    return {"type": "Feature", "geometry": {"type": type_, "coordinates": []}}


def test_une_famille_par_type_polygones_d_abord():
    """Une couche OGR n'a qu'un type : points et polygones mêlés, l'un des deux
    disparaissait de la carte."""
    assert gw.familles_geometriques([_f("Point"), _f("MultiPolygon"), _f("Polygon")]) \
        == [("Polygon", ""), ("Point", "points")]
    assert gw.familles_geometriques([_f("MultiPolygon")]) == [("Polygon", "")]
    assert gw.familles_geometriques([{"geometry": None}]) == []


def test_la_projection_est_declaree_hors_wgs84():
    """Sans membre `crs`, OGR suppose du WGS84 : le gabarit en Lambert 93 était
    chargé en degrés."""
    assert gw.membre_crs(2154) == {
        "type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2154"}}
    for srid in (4326, None, "", "n/a", 0):
        assert gw.membre_crs(srid) is None
