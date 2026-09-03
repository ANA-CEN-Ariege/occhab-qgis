# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de l'accrochage posé le temps d'une saisie, puis rendu.

QGIS n'a qu'un jeu de réglages de numérisation : celui du PROJET. Pour que la
saisie soit jointive, le plugin doit donc écrire dans les réglages de
l'utilisateur — et les lui rendre à l'identique, sans quoi il retrouve, après
une saisie, un accrochage qu'il n'a jamais demandé sur des couches qui ne sont
pas les siennes.

Ce qui se teste ici est précisément ce qu'aucun test de fonction pure n'attrape :
l'état laissé derrière soi. Y compris le drapeau « projet modifié » — changer la
configuration d'accrochage le lève, et QGIS proposerait d'enregistrer le projet
pour un réglage déjà rendu.

Si PyQt/PyQGIS manque, le module s'annonce inutilisable plutôt que d'échouer.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qgis.PyQt.QtWidgets import QApplication
except ImportError:  # pragma: no cover - poste sans PyQGIS
    QApplication = None

if QApplication is not None:
    _APP = QApplication.instance() or QApplication([])
    from occhab.src.ui.map_tools import TOLERANCE_ACCROCHAGE_PX, AideAuTrace
    from qgis.core import QgsProject, QgsSnappingConfig, QgsTolerance, QgsVectorLayer


def _couche(nom="stations"):
    layer = QgsVectorLayer("Polygon?crs=EPSG:4326", nom, "memory")
    QgsProject.instance().addMapLayer(layer, False)
    return layer


def test_accrochage_pose_sur_la_seule_couche_des_stations():
    """Sommet ET segment : sans le segment, on ne peut poser un sommet au milieu
    de la limite d'une voisine sans laisser une fente."""
    QgsProject.instance().clear()
    couche = _couche()
    aide = AideAuTrace(None)
    try:
        aide.appliquer([couche])

        config = QgsProject.instance().snappingConfig()
        reglages = config.individualLayerSettings(couche)
        assert config.enabled()
        assert config.mode() == QgsSnappingConfig.AdvancedConfiguration
        assert reglages.enabled()
        assert reglages.typeFlag() & QgsSnappingConfig.VertexFlag
        assert reglages.typeFlag() & QgsSnappingConfig.SegmentFlag
        assert reglages.tolerance() == TOLERANCE_ACCROCHAGE_PX
        assert reglages.units() == QgsTolerance.Pixels
    finally:
        aide.restaurer()


def test_les_autres_couches_ne_s_accrochent_pas():
    """Un fond cadastral chargé à côté collerait le tracé à la mauvaise limite."""
    QgsProject.instance().clear()
    stations, cadastre = _couche(), _couche("cadastre")
    aide = AideAuTrace(None)
    try:
        aide.appliquer([stations])

        reglages = QgsProject.instance().snappingConfig().individualLayerSettings(
            cadastre
        )
        assert not (reglages.valid() and reglages.enabled())
    finally:
        aide.restaurer()


def test_reglages_rendus_a_l_identique():
    """L'utilisateur retrouve SES réglages, y compris s'il n'en avait aucun."""
    QgsProject.instance().clear()
    couche = _couche()
    avant = QgsProject.instance().snappingConfig()
    aide = AideAuTrace(None)

    aide.appliquer([couche])
    aide.restaurer()

    apres = QgsProject.instance().snappingConfig()
    assert apres.enabled() == avant.enabled()
    assert apres.mode() == avant.mode()


def test_projet_non_marque_modifie():
    """Sinon QGIS propose d'enregistrer le projet après chaque station saisie,
    pour un réglage qu'on a déjà rendu : l'utilisateur finit par dire oui."""
    QgsProject.instance().clear()
    couche = _couche()
    QgsProject.instance().setDirty(False)
    aide = AideAuTrace(None)

    aide.appliquer([couche])
    aide.restaurer()

    assert not QgsProject.instance().isDirty()


def test_sans_couche_de_reference_rien_n_est_touche():
    """Première station d'un secteur : rien où s'accrocher, on ne touche à rien."""
    QgsProject.instance().clear()
    QgsProject.instance().setDirty(False)
    aide = AideAuTrace(None)

    aide.appliquer([])

    assert not QgsProject.instance().isDirty()
    aide.restaurer()  # doit rester sans effet, et surtout ne pas lever


def test_restaurer_deux_fois_est_sans_effet():
    """`_teardown` peut être appelé plusieurs fois (session résiduelle, annulation
    différée) : la deuxième restauration ne doit pas réécrire un état périmé."""
    QgsProject.instance().clear()
    couche = _couche()
    aide = AideAuTrace(None)
    aide.appliquer([couche])
    aide.restaurer()

    QgsProject.instance().setDirty(False)
    aide.restaurer()

    assert not QgsProject.instance().isDirty()
