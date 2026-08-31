# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Aides géométrie : conversion vers EPSG:4326 (attendu par OccHab) et GeoJSON.

Ces fonctions dépendent de PyQGIS et ne sont utilisées qu'à l'exécution.

RÈGLE : tout chemin qui fabrique une géométrie destinée à la base locale doit
passer par `assainir_wkt`. Une géométrie auto-intersectante s'enregistre et
s'affiche sans broncher ; c'est PostGIS qui casse, plusieurs étapes plus loin,
dans un message que l'utilisateur ne voit jamais (cf. `assainir_geometrie`).
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


#: Tolérance de fusion des sommets quasi confondus, en degrés (≈ 0,1 mm).
#: Volontairement SERRÉE : à cette latitude, 1e-7° vaut déjà un centimètre et une
#: station peut légitimement être plus fine que ça. Une tolérance plus large
#: n'aurait rien corrigé — l'auto-intersection est réelle, pas un artefact de
#: précision — mais aurait écrasé les polygones les plus minces en lignes, les
#: rendant irréparables au lieu de réparables.
TOLERANCE_SOMMETS = 1e-9


class GeometrieIrreparable(ValueError):
    """Géométrie invalide dont la réparation ne laisse rien d'exploitable."""


def assainir_geometrie(geometry):
    """(QgsGeometry valide, corrigee) — réparer une géométrie auto-intersectante.

    POURQUOI : GeoNature calcule l'altitude par ST_Intersection sur le MNT. Sur
    une géométrie auto-intersectante, PostGIS répond 500 (« TopologyException:
    Input geom 1 is invalid: Self-intersection at … ») et personne ne peut
    deviner quelle station est en cause. Un polygone dessiné en nœud papillon est
    DÉJÀ invalide en EPSG:4326 : ce n'est pas la reprojection du serveur qui
    l'abîme — rapprocher deux sommets jusqu'à 1e-16° n'a jamais suffi à rendre
    invalide un polygone valide — c'est le tracé lui-même.

    `corrigee` dit à l'appelant s'il doit prévenir l'utilisateur : la géométrie
    rendue n'est alors plus celle qu'il a dessinée. Un nœud papillon devient deux
    lobes, un éperon perd son éperon, et la surface change — or cette surface
    part dans GeoNature.

    Lève `GeometrieIrreparable` si la réparation ne laisse aucune partie de la
    dimension d'origine : un polygone plat, par exemple, ne rend que des lignes.
    """
    if geometry is None:
        raise GeometrieIrreparable("Géométrie absente.")
    geom = QgsGeometry(geometry)
    if geom.isNull() or geom.isEmpty():
        raise GeometrieIrreparable("Géométrie vide.")
    # La dimension se lit AVANT toute réparation : `makeValid` peut rendre une
    # GeometryCollection, dont le type ne dit plus rien de l'original.
    dimension = geom.type()
    if geom.isGeosValid():
        return geom, False  # cas de l'immense majorité des appels

    # Rarement suffisant — GEOS juge valide un polygone à sommets répétés — mais
    # quand ça suffit, le polygone reste SIMPLE au lieu d'être promu en
    # multipartie par `makeValid`.
    geom.removeDuplicateNodes(TOLERANCE_SOMMETS)
    if geom.isGeosValid():
        return geom, True

    # Sans argument : la signature (method, keepCollapsed) et l'énumération
    # Qgis.MakeValidMethod n'existent pas en QGIS 3.28, version minimale annoncée.
    reparee = geom.makeValid()
    if reparee is None or reparee.isNull():
        raise GeometrieIrreparable("Réparation impossible (géométrie dégénérée).")
    # Filtrage MANUEL : `coerceToType` laisse passer une GeometryCollection telle
    # quelle. Un polygone à éperon donne « Polygon + MultiLineString » ; garder la
    # ligne enverrait au serveur une géométrie de dimension mixte.
    parties = [
        partie for partie in reparee.asGeometryCollection()
        if partie.type() == dimension and not partie.isEmpty()
    ]
    if not parties:
        raise GeometrieIrreparable(
            "Géométrie dégénérée : la réparation ne laisse aucune surface "
            "exploitable (sommets alignés ou tracé aplati)."
        )
    resultat = parties[0] if len(parties) == 1 else QgsGeometry.collectGeometry(parties)
    if not resultat.isGeosValid():
        # Les parties rendues par `makeValid` sont disjointes, mais les recoller
        # sans revérifier serait se remettre dans la situation qu'on corrige.
        raise GeometrieIrreparable("La géométrie reste invalide après réparation.")
    return resultat, True


def assainir_wkt(wkt):
    """(WKT assaini, corrige). (None, False) si le WKT est vide.

    Lève `GeometrieIrreparable` si le WKT est illisible ou irrécupérable.
    """
    if not wkt:
        return None, False
    geom = QgsGeometry.fromWkt(wkt)
    if geom.isNull():
        raise GeometrieIrreparable("Géométrie illisible.")
    assainie, corrige = assainir_geometrie(geom)
    # `asWkt()` SANS précision : arrondir écraserait les stations les plus fines
    # (une bande d'un millimètre arrondie au centimètre devient une aire nulle,
    # donc une géométrie invalide) sans rien corriger de l'auto-intersection.
    return assainie.asWkt(), corrige


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
    """Convertir un WKT (supposé EPSG:4326) en dict GeoJSON. None si vide.

    DERNIER FILET avant le serveur : c'est le point de passage unique du calcul
    d'altitude ET de la synchronisation, donc le seul endroit qui protège aussi
    les stations DÉJÀ enregistrées avec une géométrie invalide. Un filet qu'il
    faudrait penser à poser à chaque nouvel appelant n'en serait pas un.

    Lève `GeometrieIrreparable` sur une géométrie irrécupérable, plutôt que de
    renvoyer None : la station partirait alors sans géométrie, et GeoNature
    écraserait celle du serveur par un null. La synchronisation traite les
    stations une par une — celle-ci échoue avec un motif clair, les autres
    passent.
    """
    if not wkt:
        return None
    geom = QgsGeometry.fromWkt(wkt)
    if geom.isNull() or geom.isEmpty():
        return None
    assainie, _ = assainir_geometrie(geom)
    return json.loads(assainie.asJson())


def geom_type_name(geometry):
    """Renvoyer 'point' | 'line' | 'polygon' pour une QgsGeometry."""
    return {
        QgsWkbTypes.GeometryType.PointGeometry: "point",
        QgsWkbTypes.GeometryType.LineGeometry: "line",
        QgsWkbTypes.GeometryType.PolygonGeometry: "polygon",
    }.get(geometry.type(), "point")
