# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Aides géométrie : conversion vers EPSG:4326 (attendu par OccHab) et GeoJSON.

Ces fonctions dépendent de PyQGIS et ne sont utilisées qu'à l'exécution.
"""
import json

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsWkbTypes,
)

CRS_4326 = "EPSG:4326"


class CrsIndetermine(ValueError):
    """Le SCR de la géométrie source est inconnu : impossible de reprojeter."""


def wkt_en_degres_plausibles(wkt):
    """Toutes les coordonnées tiennent-elles dans le domaine WGS84 ?

    Longitude dans [-180, 180], latitude dans [-90, 90]. Des mètres présentés
    comme des degrés (349907, 4774384) échouent ici — c'est le seul contrôle qui
    rattrape TOUS les chemins, y compris ceux qu'on n'a pas identifiés.
    """
    geom = QgsGeometry.fromWkt(wkt or "")
    if geom.isNull() or geom.isEmpty():
        return False
    for sommet in geom.vertices():
        if not (-180 <= sommet.x() <= 180 and -90 <= sommet.y() <= 90):
            return False
    return True


def geometry_to_wkt_4326(geometry, source_crs):
    """Reprojeter une géométrie vers EPSG:4326 et renvoyer son WKT.

    Lève `CrsIndetermine` si le SCR source est inconnu. Supposer EPSG:4326 dans
    ce cas enregistrait des mètres présentés comme des degrés : géométrie fausse
    en base, surface aberrante, et refus du serveur au calcul d'altitude
    (« transform: Invalid coordinate »).
    """
    if source_crs is None or not source_crs.isValid():
        raise CrsIndetermine(
            "SCR de la géométrie source inconnu : définissez-le avant de "
            "reprendre cette géométrie."
        )
    geom = QgsGeometry(geometry)
    if source_crs.authid() != CRS_4326:
        dest = QgsCoordinateReferenceSystem(CRS_4326)
        transform = QgsCoordinateTransform(source_crs, dest, QgsProject.instance())
        geom.transform(transform)
    wkt = geom.asWkt()
    if not wkt_en_degres_plausibles(wkt):
        raise ValueError(
            "Coordonnées hors du domaine WGS84 après reprojection depuis %s."
            % (source_crs.authid() or "SCR sans code")
        )
    return wkt


def wkt_to_geojson(wkt):
    """Convertir un WKT (supposé EPSG:4326) en dict GeoJSON. None si vide/invalide."""
    if not wkt:
        return None
    geom = QgsGeometry.fromWkt(wkt)
    if geom.isNull():
        return None
    return json.loads(geom.asJson())


def geom_type_name(geometry):
    """Renvoyer 'point' | 'line' | 'polygon' pour une QgsGeometry."""
    return {
        QgsWkbTypes.GeometryType.PointGeometry: "point",
        QgsWkbTypes.GeometryType.LineGeometry: "line",
        QgsWkbTypes.GeometryType.PolygonGeometry: "polygon",
    }.get(geometry.type(), "point")
