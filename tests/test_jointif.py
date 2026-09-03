# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de la numérisation jointive : deux stations voisines, une seule limite.

Les stations d'habitat forment des mosaïques. Sans découpe, deux polygones
voisins se recouvrent de quelques mètres — invisible à l'écran, mais la somme
des surfaces dépasse celle du site, et les deux stations se disputent la même
bande de terrain. L'accrochage aide au tracé mais ne garantit rien : c'est
`decouper_contre_voisins` qui rend la limite commune EXACTE.

Règle du module : la station voisine n'est JAMAIS modifiée. C'est le nouveau
tracé qui s'efface devant elle — la couche des stations est un miroir en lecture
seule, et la vérité est en base.
"""
from qgis.core import QgsGeometry

import geometry as geo

#: Carré de référence, en degrés. Les autres tracés se positionnent par rapport
#: à lui : chevauchant, jointif, disjoint, ou entièrement contenu.
CARRE = "POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))"


def _aire(wkt):
    return QgsGeometry.fromWkt(wkt).area()


def test_recouvrement_retire():
    """Le tracé déborde d'une unité sur la voisine : cette unité est retirée."""
    deborde = "POLYGON((1 0, 3 0, 3 2, 1 2, 1 0))"

    wkt, statut = geo.decouper_contre_voisins(deborde, [CARRE])

    assert statut == geo.JOINTIF_DECOUPE
    assert _aire(deborde) == 4.0  # avant
    assert abs(_aire(wkt) - 2.0) < 1e-9  # après : la moitié qui empiétait a sauté


def test_voisin_intact():
    """La voisine ne bouge pas : on ne renvoie qu'un tracé, jamais deux."""
    deborde = "POLYGON((1 0, 3 0, 3 2, 1 2, 1 0))"

    wkt, _ = geo.decouper_contre_voisins(deborde, [CARRE])

    assert QgsGeometry.fromWkt(wkt).intersection(
        QgsGeometry.fromWkt(CARRE)
    ).area() < 1e-12


def test_deja_jointif_ne_declenche_aucun_avertissement():
    """Le cas NORMAL, une fois l'accrochage en place : limite commune exacte.

    `QgsGeometry.equals` comparerait sommet à sommet et jugerait « découpé » ce
    tracé, car la différence géométrique renvoie le même contour avec un autre
    point de départ. L'utilisateur aurait reçu l'avertissement à chaque station
    posée le long de sa voisine, jusqu'à ne plus le lire.
    """
    accole = "POLYGON((2 0, 4 0, 4 2, 2 2, 2 0))"

    wkt, statut = geo.decouper_contre_voisins(accole, [CARRE])

    assert statut == geo.JOINTIF_INCHANGE
    assert wkt == accole  # le WKT d'origine, sommets dans l'ordre de la saisie


def test_disjoint_inchange():
    loin = "POLYGON((10 10, 11 10, 11 11, 10 11, 10 10))"

    assert geo.decouper_contre_voisins(loin, [CARRE]) == (loin, geo.JOINTIF_INCHANGE)


def test_trace_contenu_dans_une_voisine_est_conserve():
    """Découper ne laisserait RIEN : on garde la saisie et on avertit.

    Une station entièrement incluse dans une autre est suspecte, mais effacer le
    travail de quelqu'un qui revient du terrain l'est davantage. Le statut dit à
    l'appelant qu'il doit le signaler ; l'arbitrage revient à l'utilisateur.
    """
    dedans = "POLYGON((0.5 0.5, 1 0.5, 1 1, 0.5 1, 0.5 0.5))"

    wkt, statut = geo.decouper_contre_voisins(dedans, [CARRE])

    assert statut == geo.JOINTIF_RECOUVERT
    assert wkt == dedans


def test_points_et_lignes_intacts():
    """Seuls les polygones se disputent une surface."""
    for trace in ("POINT(1 1)", "LINESTRING(0 0, 5 5)"):
        assert geo.decouper_contre_voisins(trace, [CARRE]) == (
            trace, geo.JOINTIF_INCHANGE
        )


def test_voisine_invalide_ignoree_sans_perdre_les_autres():
    """Les stations saisies avant `assainir_wkt` peuvent être auto-intersectantes.

    GEOS refuserait l'union entière et la découpe n'aurait plus lieu du tout :
    une seule vieille station aurait suffi à désactiver le jointif sur tout un
    secteur, sans rien dire.
    """
    papillon = "POLYGON((0 0, 2 2, 2 0, 0 2, 0 0))"
    deborde = "POLYGON((1 0, 3 0, 3 2, 1 2, 1 0))"

    wkt, statut = geo.decouper_contre_voisins(deborde, [papillon, CARRE])

    assert statut == geo.JOINTIF_DECOUPE
    assert abs(_aire(wkt) - 2.0) < 1e-9


def test_decoupe_contre_plusieurs_voisines():
    """Une station peut combler un vide entre deux mosaïques déjà posées."""
    a_gauche = "POLYGON((-3 0, 0 0, 0 2, -3 2, -3 0))"
    comble = "POLYGON((-1 0, 3 0, 3 2, -1 2, -1 0))"

    wkt, statut = geo.decouper_contre_voisins(comble, [CARRE, a_gauche])

    assert statut == geo.JOINTIF_DECOUPE
    assert abs(_aire(wkt) - 2.0) < 1e-9  # ne reste que ce qui n'était à personne


def test_trace_coupe_en_deux_reste_exploitable():
    """Traverser une voisine de part en part laisse deux lobes : c'est valide."""
    traverse = "POLYGON((0.5 -1, 1.5 -1, 1.5 3, 0.5 3, 0.5 -1))"

    wkt, statut = geo.decouper_contre_voisins(traverse, [CARRE])

    assert statut == geo.JOINTIF_DECOUPE
    assert QgsGeometry.fromWkt(wkt).isMultipart()
    assert QgsGeometry.fromWkt(wkt).isGeosValid()


def test_sans_voisine_et_sans_trace():
    assert geo.decouper_contre_voisins(CARRE, []) == (CARRE, geo.JOINTIF_INCHANGE)
    assert geo.decouper_contre_voisins("", [CARRE]) == ("", geo.JOINTIF_INCHANGE)
    assert geo.decouper_contre_voisins(None, [CARRE]) == (None, geo.JOINTIF_INCHANGE)
