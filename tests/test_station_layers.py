# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests des couches miroir locales, côté accrochage.

Les entités sont écrites directement dans le provider : `QgsVectorLayer` n'émet
alors aucun des signaux auxquels l'index d'accrochage (`QgsPointLocator`) est
abonné. Le canevas redessinait donc les nouvelles stations pendant que
l'accrochage travaillait encore sur l'ancien jeu — une station fraîchement
saisie ne s'accrochait pas, et une station supprimée s'accrochait encore.

Le symptôme était trompeur : l'accrochage « se mettait à marcher » une fois la
station synchronisée. C'était la couche de contexte serveur, détruite et
recréée à chaque chargement, qui prenait le relais — la couche locale, elle,
restait périmée.
"""
import os
import sys

_RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(_RACINE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from occhab.src.ui.station_layers import StationLayerManager  # noqa: E402
from qgis.core import (  # noqa: E402
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsPointLocator,
    QgsPointXY,
    QgsProject,
)

#: Deux carrés disjoints, en degrés : un sommet de chacun sert de cible.
_CARRE_A = "POLYGON((1.90 43.05, 1.91 43.05, 1.91 43.06, 1.90 43.05))"
_CARRE_B = "POLYGON((2.20 43.30, 2.21 43.30, 2.21 43.31, 2.20 43.30))"
_SOMMET_A = QgsPointXY(1.90, 43.05)
_SOMMET_B = QgsPointXY(2.20, 43.30)
#: Large au regard des carrés : le test porte sur la présence dans l'index,
#: pas sur la finesse de l'accrochage.
_TOLERANCE = 0.001


def _station(local_id, wkt):
    return {
        "id": local_id, "id_station": None, "station_name": "S%d" % local_id,
        "geom": wkt, "geom_type": "polygon", "id_dataset": 3,
        "date_min": "2026-08-31", "sync_status": "pending", "_nb_habitats": 1,
    }


def _couche_polygones(manager):
    couches = [c for c in manager.existing_layers() if "polygone" in c.name()]
    assert couches, "la couche des polygones devrait exister"
    return couches[0]


def _locator(layer):
    """Index d'accrochage, INTERROGÉ une fois pour forcer son remplissage.

    C'est cette première interrogation qui fige l'index : sans elle, le défaut
    ne se reproduit pas.
    """
    loc = QgsPointLocator(
        layer, QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsCoordinateTransformContext(),
    )
    loc.nearestVertex(_SOMMET_A, _TOLERANCE)
    return loc


def test_station_ajoutee_est_accrochable():
    """Le symptôme d'origine : une station saisie après coup ne s'accrochait pas."""
    QgsProject.instance().clear()
    manager = StationLayerManager()
    try:
        manager.refresh([_station(1, _CARRE_A)])
        locator = _locator(_couche_polygones(manager))

        manager.refresh([_station(1, _CARRE_A), _station(2, _CARRE_B)])

        assert locator.nearestVertex(_SOMMET_B, _TOLERANCE).isValid()
    finally:
        manager.cleanup()


def test_station_retiree_n_est_plus_accrochable():
    """Le revers, plus grave : s'accrocher au fantôme d'une station supprimée.

    Un accrochage silencieusement faux est pire qu'une absence d'accrochage,
    qui, elle, se voit.
    """
    QgsProject.instance().clear()
    manager = StationLayerManager()
    try:
        manager.refresh([_station(1, _CARRE_A), _station(2, _CARRE_B)])
        locator = _locator(_couche_polygones(manager))
        assert locator.nearestVertex(_SOMMET_B, _TOLERANCE).isValid()

        manager.refresh([_station(1, _CARRE_A)])

        assert not locator.nearestVertex(_SOMMET_B, _TOLERANCE).isValid()
    finally:
        manager.cleanup()


def test_voisines_lues_depuis_la_couche_affichee():
    """La numérisation jointive se découpe contre ce que l'utilisateur VOIT.

    Lire la base plutôt que la couche découperait la station contre une voisine
    hors du jeu de données filtré — invisible sur la carte, impossible à
    s'accrocher dessus, et pourtant elle mangerait le tracé.
    """
    QgsProject.instance().clear()
    manager = StationLayerManager()
    try:
        manager.refresh([_station(1, _CARRE_A), _station(2, _CARRE_B)])

        wkts = manager.geometries_wkt("polygon")

        assert len(wkts) == 2
    finally:
        manager.cleanup()


def test_station_re_numerisee_exclue_de_ses_propres_voisines():
    """Sans cette exclusion, la station se découperait contre sa PROPRE géométrie,
    encore affichée sur la carte, et il ne resterait rien du nouveau tracé."""
    QgsProject.instance().clear()
    manager = StationLayerManager()
    try:
        manager.refresh([_station(1, _CARRE_A), _station(2, _CARRE_B)])

        wkts = manager.geometries_wkt("polygon", exclure_id=1)

        assert len(wkts) == 1
        assert "2.2" in wkts[0]  # il ne reste que le carré B
    finally:
        manager.cleanup()


def test_couches_reference_absentes_avant_toute_station():
    """Aucune station saisie : rien où s'accrocher, et surtout aucune exception —
    la première station d'un secteur se numérise comme avant."""
    QgsProject.instance().clear()
    manager = StationLayerManager()
    try:
        assert manager.couches_reference("polygon") == []
        assert manager.geometries_wkt("polygon") == []

        manager.refresh([_station(1, _CARRE_A)])

        assert len(manager.couches_reference("polygon")) == 1
    finally:
        manager.cleanup()
