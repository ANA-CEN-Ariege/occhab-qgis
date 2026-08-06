# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Conversion d'une géométrie GeoJSON en WKT (module pur, testable sans QGIS).

`QgsJsonUtils.geometryFromGeoJson()` ferait le travail en une ligne — mais elle
n'existe qu'à partir de **QGIS 3.36**. Sur une installation plus ancienne, et
l'extension annonce prendre en charge la **3.28**, l'appel se solde par un
`AttributeError` au chargement d'un export : la couche ne se charge pas du tout.

`QgsGeometry.fromWkt()`, elle, existe depuis toujours. D'où ce convertisseur, qui
donne au passage un chemin unique pour toutes les versions plutôt qu'une branche
selon celle qu'on a sous la main.

Les coordonnées sont ramenées à **deux dimensions** : une altitude GeoJSON ne
sert ni au calcul des surfaces, ni au découpage des bandes, ni au damier.
"""

#: Correspondance entre le type GeoJSON et le mot-clé WKT, avec la profondeur
#: d'imbrication des coordonnées (0 = un point, 1 = une liste de points…).
_TYPES = {
    "Point": ("POINT", 0),
    "MultiPoint": ("MULTIPOINT", 1),
    "LineString": ("LINESTRING", 1),
    "MultiLineString": ("MULTILINESTRING", 2),
    "Polygon": ("POLYGON", 2),
    "MultiPolygon": ("MULTIPOLYGON", 3),
}


def wkt(geometrie):
    """WKT d'une géométrie GeoJSON (dict), ou None si elle est inexploitable.

    None plutôt qu'une exception : une station sans géométrie est un cas normal
    — le serveur en rend — et elle ne doit pas empêcher les autres de s'afficher.
    """
    if not isinstance(geometrie, dict):
        return None
    type_geojson = geometrie.get("type")

    if type_geojson == "GeometryCollection":
        morceaux = [wkt(g) for g in geometrie.get("geometries") or []]
        morceaux = [m for m in morceaux if m]
        return "GEOMETRYCOLLECTION (%s)" % ", ".join(morceaux) if morceaux else None

    if type_geojson not in _TYPES:
        return None
    mot_cle, profondeur = _TYPES[type_geojson]
    corps = _coordonnees(geometrie.get("coordinates"), profondeur)
    if corps is None:
        return None
    # Une seule paire de parenthèses ici, quelle que soit la profondeur : les
    # niveaux intérieurs ont déjà été parenthésés par `_coordonnees`.
    return "%s (%s)" % (mot_cle, corps)


def _coordonnees(valeur, profondeur):
    """Coordonnées WKT, parenthésées selon la profondeur, ou None."""
    if profondeur == 0:
        return _point(valeur)
    if not isinstance(valeur, (list, tuple)) or not valeur:
        return None
    morceaux = []
    for element in valeur:
        rendu = _coordonnees(element, profondeur - 1)
        if rendu is None:
            return None
        morceaux.append(rendu if profondeur == 1 else "(%s)" % rendu)
    return ", ".join(morceaux)


def _point(valeur):
    """« x y » depuis [x, y] ou [x, y, z], ou None."""
    if not isinstance(valeur, (list, tuple)) or len(valeur) < 2:
        return None
    try:
        x, y = float(valeur[0]), float(valeur[1])
    except (TypeError, ValueError):
        return None
    return "%s %s" % (_nombre(x), _nombre(y))


def _nombre(valeur):
    """Nombre sans notation scientifique ni zéros inutiles.

    `repr()` écrirait « 1e-05 » pour une petite valeur, que l'analyseur WKT de
    QGIS n'accepte pas ; `%f` tronquerait des coordonnées en degrés, où la
    septième décimale vaut encore un centimètre.
    """
    texte = "%.9f" % valeur
    texte = texte.rstrip("0").rstrip(".")
    return texte or "0"
