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


def geometry_to_wkt_4326(geometry, source_crs):
    """Reprojeter une géométrie vers EPSG:4326 et renvoyer son WKT."""
    geom = QgsGeometry(geometry)
    dest = QgsCoordinateReferenceSystem(CRS_4326)
    if source_crs is not None and source_crs.isValid() and source_crs.authid() != CRS_4326:
        transform = QgsCoordinateTransform(source_crs, dest, QgsProject.instance())
        geom.transform(transform)
    return geom.asWkt()


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
        QgsWkbTypes.PointGeometry: "point",
        QgsWkbTypes.LineGeometry: "line",
        QgsWkbTypes.PolygonGeometry: "polygon",
    }.get(geometry.type(), "point")
