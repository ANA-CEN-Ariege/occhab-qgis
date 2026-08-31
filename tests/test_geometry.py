# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de l'assainissement topologique, né d'une 500 PostGIS bien réelle.

GeoNature calculait l'altitude d'une station et répondait :

    lwgeom_intersection_prec: GEOS Error: TopologyException:
    Input geom 1 is invalid: Self-intersection at 601103.78 6165856.10

Le polygone en cause — un mince sliver — était déjà auto-intersectant en
EPSG:4326, avant tout envoi : ni la reprojection du serveur ni un défaut de
précision n'y étaient pour quelque chose. Rien côté plugin ne le voyait passer,
et l'utilisateur n'apprenait jamais que sa station était en cause.
"""
import pytest
from qgis.core import QgsGeometry, QgsWkbTypes

import geometry as geo

#: Nœud papillon : le contour se recroise en son milieu.
NOEUD_PAPILLON = "POLYGON((0 0, 2 2, 2 0, 0 2, 0 0))"
#: Carré prolongé d'un éperon sans épaisseur : `makeValid` en fait une collection
#: mêlant une surface et des lignes.
EPERON = "POLYGON((0 0, 4 0, 4 4, 0 4, 0 0, 2 2, 2 6, 2 2, 0 0))"
#: Sommets alignés : il ne reste rien de surfacique après réparation.
POLYGONE_PLAT = "POLYGON((0 0, 1 1, 2 2, 0 0))"


def test_geometrie_valide_intacte():
    """Le cas courant ne doit rien coûter et ne rien signaler."""
    geom = QgsGeometry.fromWkt("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))")

    assainie, corrigee = geo.assainir_geometrie(geom)

    assert corrigee is False
    assert assainie.asWkt() == geom.asWkt()


def test_noeud_papillon_repare():
    assainie, corrigee = geo.assainir_geometrie(QgsGeometry.fromWkt(NOEUD_PAPILLON))

    assert corrigee is True
    assert assainie.isGeosValid()
    assert assainie.type() == QgsWkbTypes.GeometryType.PolygonGeometry
    # Le nœud papillon se sépare en deux lobes : la promotion en multipartie est
    # assumée, l'alternative (ne garder que le plus grand) perdrait du terrain.
    assert len(assainie.asGeometryCollection()) == 2


def test_eperon_filtre():
    """Aucune partie linéaire ne doit survivre à la réparation d'un polygone.

    C'est ce cas qui interdit `coerceToType` : il rend la GeometryCollection de
    `makeValid` inchangée, éperon compris. Le filtre est donc manuel.
    """
    assainie, corrigee = geo.assainir_geometrie(QgsGeometry.fromWkt(EPERON))

    assert corrigee is True
    assert assainie.isGeosValid()
    assert all(
        partie.type() == QgsWkbTypes.GeometryType.PolygonGeometry
        for partie in assainie.asGeometryCollection()
    )


def test_polygone_plat_refuse():
    with pytest.raises(geo.GeometrieIrreparable):
        geo.assainir_geometrie(QgsGeometry.fromWkt(POLYGONE_PLAT))


def test_ligne_auto_secante_intacte():
    """GEOS juge une ligne auto-sécante VALIDE : rien à réparer, et c'est correct.

    En pratique l'assainissement ne mord donc que sur les polygones — ce qui
    tombe bien, ST_Intersection ne casse que sur des surfaces.
    """
    ligne = QgsGeometry.fromWkt("LINESTRING(0 0, 1 1, 0 1, 1 0)")

    assainie, corrigee = geo.assainir_geometrie(ligne)

    assert corrigee is False
    assert assainie.asWkt() == ligne.asWkt()


def test_point_intact():
    point = QgsGeometry.fromWkt("POINT(1.7967927741429004 42.58570283730006)")

    assainie, corrigee = geo.assainir_geometrie(point)

    assert corrigee is False
    assert assainie.asWkt() == point.asWkt()


def test_precision_preservee():
    """Garde-fou contre un `asWkt(7)` réintroduit un jour « pour faire propre ».

    Arrondir au centimètre écrase les stations les plus fines : une bande d'un
    millimètre de large, valide au départ, en ressort d'aire nulle et invalide.
    """
    wkt = ("POLYGON((1.796792774142900 42.585702837300060, "
           "1.797000000000000 42.585702837300060, "
           "1.797000000000000 42.585712837300061, "
           "1.796792774142900 42.585702837300061))")

    assaini, corrige = geo.assainir_wkt(wkt)

    assert corrige is False
    # Le WKT rendu porte la précision maximale du double (17 chiffres) ; on ne
    # compare pas les chiffres eux-mêmes, seulement qu'aucun arrondi n'a eu lieu.
    decimales = max(len(nombre.split(".")[1])
                    for nombre in assaini.replace("(", " ").replace(")", " ").split()
                    if "." in nombre)
    assert decimales >= 12, "arrondi détecté : %s" % assaini


def test_wkt_vide():
    assert geo.assainir_wkt("") == (None, False)
    assert geo.assainir_wkt(None) == (None, False)


def test_wkt_illisible():
    with pytest.raises(geo.GeometrieIrreparable):
        geo.assainir_wkt("POLYGON((")


def test_filet_de_sortie_repare():
    """`wkt_to_geojson` est l'unique passage vers le serveur : il doit assainir.

    C'est le seul filet qui protège les stations DÉJÀ enregistrées avec une
    géométrie invalide sur les postes de terrain.
    """
    resultat = geo.wkt_to_geojson(NOEUD_PAPILLON)

    assert resultat["type"] == "MultiPolygon"


def test_filet_de_sortie_refuse_l_irreparable():
    """Surtout pas `None` : la station partirait sans géométrie, et GeoNature
    écraserait la géométrie du serveur par un null."""
    with pytest.raises(geo.GeometrieIrreparable):
        geo.wkt_to_geojson(POLYGONE_PLAT)


def test_filet_de_sortie_wkt_vide():
    assert geo.wkt_to_geojson("") is None
    assert geo.wkt_to_geojson(None) is None
