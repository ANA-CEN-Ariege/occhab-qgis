# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du damier : la précision du WKT doit suivre l'unité de la couche.

Les exports GeoNature arrivent en degrés (WGS84). Une précision fixe, calée sur
des mètres, y écrasait tout le damier sur un point : les mosaïques ressortaient
vides, sans la moindre erreur au chargement. D'où ces tests, qui prennent les
deux unités au sérieux.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(_ROOT)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from occhab.src.ui import export_layers as el  # noqa: E402
from qgis.core import QgsGeometry  # noqa: E402

#: Une station ordinaire d'un demi-hectare, dans les deux unités qu'on rencontre.
_CARRE_METRES = [[(0.0, 0.0), (70.0, 0.0), (70.0, 70.0), (0.0, 70.0), (0.0, 0.0)]]
_CARRE_DEGRES = [[(1.904521, 43.012345), (1.905371, 43.012345),
                  (1.905371, 43.012965), (1.904521, 43.012965),
                  (1.904521, 43.012345)]]


def _station(anneau, parts):
    """Entités GeoJSON d'une station et de ses habitats."""
    coords = [[list(point) for point in anneau[0]]]
    return [{"type": "Feature",
             "geometry": {"type": "Polygon", "coordinates": coords},
             "properties": {"id_station": 1, "nom_cite": "H%d" % i,
                            "cd_hab": 1000 + i, "recouvrement_pct": part,
                            "cd_typo": 22,
                            el.hs.CHAMP_DEBUT: sum(parts[:i]),
                            el.hs.CHAMP_FIN: sum(parts[:i + 1])}}
            for i, part in enumerate(parts)]


def test_decimales_suivent_l_unite():
    # En degrés, une décimale vaut onze kilomètres : il en faut bien davantage.
    assert el._decimales(6.8e-5) >= 6
    # En mètres, deux décimales suffisent largement pour une maille métrique.
    assert el._decimales(1.25) <= 3
    assert el._decimales(0.0) > 0  # aucune division par zéro sur une aire nulle


def test_le_damier_survit_aux_degres():
    """Le WKT relu doit couvrir la même surface qu'à l'écriture."""
    for anneau, tolerance in ((_CARRE_METRES, 1e-3), (_CARRE_DEGRES, 1e-3)):
        features = _station(anneau, [50.0, 30.0, 20.0])
        el._poser_mailles(features)
        polygone = el._geometrie(features[0])
        relues = [QgsGeometry.fromWkt(f["properties"][el.CHAMP_MAILLES])
                  for f in features]
        for geometrie in relues:
            assert not geometrie.isEmpty()
        union = QgsGeometry.unaryUnion(relues)
        assert abs(union.area() / polygone.area() - 1.0) < tolerance


def test_les_parts_du_damier_suivent_le_recouvrement():
    features = _station(_CARRE_DEGRES, [50.0, 30.0, 20.0])
    el._poser_mailles(features)
    aire = el._geometrie(features[0]).area()
    obtenues = [100.0 * QgsGeometry.fromWkt(f["properties"][el.CHAMP_MAILLES]).area()
                / aire for f in features]
    for obtenue, attendue in zip(obtenues, (50.0, 30.0, 20.0)):
        # Une maille sur 64, soit 1,6 % : l'arrondi ne peut pas faire mieux.
        assert abs(obtenue - attendue) < 2.0


def test_un_habitat_minoritaire_garde_une_maille():
    """Un habitat relevé ne doit jamais disparaître de la carte."""
    features = _station(_CARRE_DEGRES, [60.0, 37.0, 2.0, 1.0])
    el._poser_mailles(features)
    for feature in features:
        assert feature["properties"].get(el.CHAMP_MAILLES)


def test_station_a_un_seul_habitat_non_quadrillee():
    """Quadriller un polygone sans mosaïque dessinerait un faux découpage."""
    features = _station(_CARRE_DEGRES, [100.0])
    el._poser_mailles(features)
    assert features[0]["properties"].get(el.CHAMP_MAILLES) is None


def test_un_nouvel_export_se_place_au_dessus_des_precedents():
    """Sinon le deuxième export est caché par le premier, et paraît vide."""
    import tempfile

    from qgis.core import QgsProject

    gestionnaire = el.ExportLayerManager(tempfile.mkdtemp())
    try:
        for nom in ("Premier", "Deuxième", "Troisième"):
            gestionnaire.show(nom, _station(_CARRE_DEGRES, [100.0]))
        groupe = QgsProject.instance().layerTreeRoot().findGroup(el.GROUP_NAME)
        assert groupe is not None
        # L'ordre du panneau des couches va du dessus vers le dessous.
        assert [n.name() for n in groupe.children()] == \
            ["Troisième", "Deuxième", "Premier"]
    finally:
        gestionnaire.cleanup()
