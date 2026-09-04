# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Couches issues des exports GeoNature (lecture seule, conservées telles quelles).

Groupe distinct de « OccHab (serveur) », qui est **reconstruit à chaque
rafraîchissement** : un export chargé y disparaîtrait au premier refresh. Ici,
chaque chargement produit sa propre couche, nommée d'après l'export et la période
demandée, et plusieurs peuvent coexister — comparer deux années est justement
l'usage.

Le GeoJSON est écrit sur disque puis ouvert via OGR : le fournisseur gère
nativement les géométries mixtes point/ligne/polygone d'une station OccHab, ce
qu'une couche mémoire typée ne saurait pas faire.
"""
import json
import os
import re

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsBlurEffect,
    QgsGeometry,
    QgsRectangle,
    QgsProperty,
    QgsFillSymbol,
    QgsGeometryGeneratorSymbolLayer,
    QgsMarkerSymbol,
    QgsProject,
    QgsRuleBasedRenderer,
    QgsSymbol,
    QgsSymbolLayer,
    QgsUnitTypes,
    QgsVectorLayer,
)

from ..processing import geojson_wkt as gw
from ..processing import pee
from ..processing import referentiels as ref
from ..processing import habitat_style as hs

GROUP_NAME = "OccHab (exports)"

#: Énumérations déplacées d'une version de QGIS à l'autre. `Qgis.RenderUnit`
#: n'apparaît qu'en 3.30 et `Qgis.SymbolType` en 3.20 ; l'extension annonce
#: prendre en charge la 3.28. Les anciennes places existent encore dans les
#: versions récentes, mais elles ne sont pas les mieux documentées : d'où la
#: nouvelle d'abord, l'ancienne en repli.
_MILLIMETRES = getattr(getattr(Qgis, "RenderUnit", None), "Millimeters", None)
if _MILLIMETRES is None:
    _MILLIMETRES = QgsUnitTypes.RenderMillimeters
_SYMBOLE_SURFACIQUE = getattr(getattr(Qgis, "SymbolType", None), "Fill", None)
if _SYMBOLE_SURFACIQUE is None:
    _SYMBOLE_SURFACIQUE = QgsSymbol.Fill
_SYMBOLE_PONCTUEL = getattr(getattr(Qgis, "SymbolType", None), "Marker", None)
if _SYMBOLE_PONCTUEL is None:
    _SYMBOLE_PONCTUEL = QgsSymbol.Marker
#: Même histoire, mais celle-là s'est vue sur le terrain : là où l'énumération
#: est encore un `sip.enumtype` — les QGIS d'avant les énumérations Python — ses
#: membres gardent le préfixe du type (`PropertyFillColor`). Le nom court y
#: échouait AVANT que le rendu soit posé : plus de couleurs d'habitats, plus de
#: légende, la couche s'affichait dans le gris uni de QGIS.
#: `try` plutôt que `getattr` : sip ne lève pas forcément une `AttributeError`
#: sur un membre inconnu, et une exception ici empêcherait le module de
#: s'importer — donc l'extension de se charger du tout.
try:
    _PROP_COULEUR_FOND = QgsSymbolLayer.Property.FillColor
except Exception:  # noqa: BLE001
    _PROP_COULEUR_FOND = QgsSymbolLayer.PropertyFillColor



def nom_de_fichier(libelle):
    """Nom de fichier sûr dérivé d'un libellé d'export (jamais vide)."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (libelle or "").strip()).strip("_")
    return (base[:80] or "export").lower()


def _litteral(valeur):
    """Chaîne SQL échappée pour une expression QGIS.

    La clé d'habitat peut retomber sur un nom cité libre — donc contenir une
    apostrophe (« Prairie d'altitude »), qui casserait l'expression et ferait
    disparaître l'habitat de la carte sans un mot.
    """
    return "'%s'" % str(valeur).replace("'", "''")


#: Façons de représenter une station portant plusieurs habitats. Aucune n'est
#: « la » bonne : le guide méthodologique national ne normalise pas la
#: sémiologie des mosaïques. Elles se choisissent au chargement pour être
#: comparées sur les mêmes données.
MODE_BANDES = "bandes"
MODE_DAMIER = "damier"
MODE_ENJEUX = "enjeux"
MODE_PEE = "pee"

MODES = (
    (MODE_BANDES, "Bandes proportionnelles",
     "Le polygone est partagé en bandes horizontales, une par habitat, "
     "proportionnelles au recouvrement."),
    (MODE_DAMIER, "Damier de mailles carrées",
     "Une grille régulière découpe la station ; chaque maille revient en "
     "entier à un habitat, en nombre proportionnel à son recouvrement."),
    (MODE_ENJEUX, "Carte des enjeux",
     "Une couleur par niveau d'enjeu de la STATION — très fort, fort, moyen, "
     "faible — et les contours des habitats par-dessus."),
    (MODE_PEE, "Carte des plantes exotiques envahissantes",
     "Les habitats en bandes, et par-dessus un cercle par espèce exotique "
     "relevée, une couleur par espèce."),
)

MODE_DEFAUT = MODE_BANDES


#: Découpe d'un polygone en bandes horizontales proportionnelles au recouvrement.
#: Chaque habitat d'une mosaïque occupe la sienne, en APLAT PLEIN.
#:
#: Remplace des hachures colorées superposées, illisibles dès que la carte se
#: densifie : il fallait comprendre que la hachure reprenait la couleur d'un
#: autre poste de légende, et trois couches translucides sur la même géométrie
#: saturaient tout. Ici plus aucune superposition — la lisibilité d'une carte
#: mono-habitat, quelle que soit la densité.
#:
#: Les hauteurs de coupe sont des ATTRIBUTS calculés au chargement
#: (`_poser_coupes`), pas des formules : les faire calculer par l'expression
#: demanderait un agrégat par entité, ruineux au rendu, et une fraction de la
#: hauteur ne donne la bonne surface que sur un polygone régulier.
_EXPRESSION_BANDE = """intersection($geometry, make_polygon(make_line(
    make_point(x_min($geometry), "{y_debut}"),
    make_point(x_max($geometry), "{y_debut}"),
    make_point(x_max($geometry), "{y_fin}"),
    make_point(x_min($geometry), "{y_fin}"),
    make_point(x_min($geometry), "{y_debut}"))))"""

#: Hauteurs de coupe de la bande, en coordonnées de la couche, calculées au
#: chargement (cf. `_poser_coupes`).
CHAMP_Y_DEBUT = "bande_y_debut"
CHAMP_Y_FIN = "bande_y_fin"
#: Itérations de dichotomie par coupe. 24 divisent la hauteur par 16 millions :
#: très au-delà de la précision utile, pour un coût négligeable.
_ITERATIONS_COUPE = 24


def _poser_coupes(features, cle_station="id_station"):
    """Convertir les parts cumulées en hauteurs de coupe EXACTES.

    Découper à une fraction de la HAUTEUR ne donne la bonne SURFACE que si le
    polygone est régulier. Mesuré : sur un carré comme sur un rectangle allongé,
    50 / 30 / 20 tombent juste ; sur une forme en L — banale en cartographie
    d'habitats — on obtenait **68,8 / 18,8 / 12,5 %**. La partie basse est plus
    large, donc une tranche de même hauteur y pèse bien davantage.

    On cherche donc, par dichotomie, la hauteur sous laquelle le polygone couvre
    exactement la part voulue. Une fois au chargement, jamais au rendu.
    """
    stations = {}
    for feature in features or []:
        props = feature.get("properties") or {}
        stations.setdefault(props.get(cle_station), []).append(feature)

    for lot in stations.values():
        geom = _geometrie(lot[0])
        if geom is None or geom.isEmpty():
            continue
        emprise = geom.boundingBox()
        aire = geom.area()
        if aire <= 0:
            continue
        cache = {0.0: emprise.yMinimum(), 100.0: emprise.yMaximum()}
        for feature in lot:
            props = feature.setdefault("properties", {})
            for champ_part, champ_y in ((hs.CHAMP_DEBUT, CHAMP_Y_DEBUT),
                                        (hs.CHAMP_FIN, CHAMP_Y_FIN)):
                part = float(props.get(champ_part) or 0.0)
                if part not in cache:
                    cache[part] = _coupe_pour_part(geom, emprise,
                                                   aire * part / 100.0)
                props[champ_y] = cache[part]
    return features


#: Damier : la station découpée en mailles régulières, chacune revenant en
#: ENTIER à un habitat. Les proportions se lisent au NOMBRE de mailles, pas à
#: une position — ce qui convient à une mosaïque, dont on ignore justement la
#: répartition interne. Contrairement aux bandes ou aux anneaux, aucune lecture
#: « du haut vers le bas » ni « du centre vers le bord » ne vient suggérer une
#: organisation spatiale qui n'existe pas.
CHAMP_MAILLES = "mailles"
CHAMP_COTE = "maille_cote"
#: Nombre de mailles visé par station. 64 donnent une résolution de 1,6 % — plus
#: fin que la précision d'un recouvrement relevé sur le terrain — tout en
#: laissant chaque maille assez grande pour être vue. La taille se déduit de
#: l'AIRE : une petite station et une grande se lisent alors pareil, au prix
#: d'une maille dont la taille varie de l'une à l'autre.
_MAILLES_CIBLE = 64
#: Suite R2 (Roberts) : deux irrationnels dont les multiples ne retombent jamais
#: en phase. Parcourir les mailles dans cet ordre disperse les habitats sur tout
#: le polygone ; un parcours ligne par ligne les aurait empilés par bandes,
#: c'est-à-dire aurait refait le mode qu'on cherche à compléter.
_R2 = (0.7548776662466927, 0.5698402909980532)


def _poser_mailles(features, cle_station="id_station"):
    """Répartir les mailles du damier entre les habitats de chaque station.

    L'affectation suit le DÉFICIT : à chaque maille, l'habitat qui est le plus
    loin de sa surface due la prend. Une simple règle de trois maille par maille
    aurait laissé les arrondis s'accumuler ; là, l'erreur ne dépasse jamais une
    maille, et les habitats s'alternent d'eux-mêmes.

    Les mailles de bordure sont rognées sur le polygone : le damier couvre donc
    exactement la station, sans débord ni liseré vide.
    """
    stations = {}
    for feature in features or []:
        props = feature.get("properties") or {}
        stations.setdefault(props.get(cle_station), []).append(feature)

    for lot in stations.values():
        # Une station à un seul habitat n'a rien à partager : la quadriller
        # dessinerait un faux découpage, et alourdirait le fichier pour rien.
        if len(lot) < 2:
            continue
        geom = _geometrie(lot[0])
        if geom is None or geom.isEmpty() or geom.area() <= 0:
            continue
        aire = geom.area()
        cote = (aire / _MAILLES_CIBLE) ** 0.5
        mailles = _mailles(geom, cote)
        if not mailles:
            continue
        for feature, part in zip(lot, _repartir(mailles, lot, aire)):
            props = feature.setdefault("properties", {})
            props[CHAMP_COTE] = cote
            props[CHAMP_MAILLES] = _wkt(part, cote)
    return features


def _mailles(geom, cote):
    """Mailles de `cote` couvrant `geom`, rognées, en ordre dispersé."""
    emprise = geom.boundingBox()
    x0, y0 = emprise.xMinimum(), emprise.yMinimum()
    colonnes = int(emprise.width() / cote) + 1
    lignes = int(emprise.height() / cote) + 1
    mailles = []
    for i in range(colonnes):
        for j in range(lignes):
            case = QgsGeometry.fromRect(QgsRectangle(
                x0 + i * cote, y0 + j * cote,
                x0 + (i + 1) * cote, y0 + (j + 1) * cote,
            ))
            part = geom.intersection(case)
            if part.isEmpty() or part.area() <= 0:
                continue
            rang = ((i * _R2[0] + j * _R2[1]) % 1.0)
            mailles.append((rang, part.area(), part))
    mailles.sort(key=lambda m: m[0])
    return mailles


def _repartir(mailles, lot, aire):
    """Mailles revenant à chaque habitat, dans l'ordre de `lot`."""
    cibles = [aire * float(_proprietes(f).get(hs.CHAMP_FIN) or 0.0)
              - aire * float(_proprietes(f).get(hs.CHAMP_DEBUT) or 0.0)
              for f in lot]
    cibles = [c / 100.0 for c in cibles]
    acquis = [0.0] * len(lot)
    parts = [[] for _ in lot]
    for _rang, surface, maille in mailles:
        gagnant = max(range(len(lot)), key=lambda k: cibles[k] - acquis[k])
        acquis[gagnant] += surface
        parts[gagnant].append(maille)
    # Un habitat très minoritaire peut n'avoir décroché aucune maille : lui en
    # céder une prise au plus servi. Mieux vaut 1,6 % de trop que l'absence pure
    # et simple d'un habitat pourtant relevé.
    for k, part in enumerate(parts):
        if part or cibles[k] <= 0:
            continue
        donneur = max(range(len(lot)), key=lambda d: acquis[d] - cibles[d])
        if len(parts[donneur]) > 1:
            parts[k].append(parts[donneur].pop())
    return parts


def _decimales(cote):
    """Décimales à garder dans le WKT, d'après la taille d'une maille.

    Un nombre fixe est un piège : les exports GeoNature arrivent en degrés
    (WGS84), où une décimale vaut ONZE KILOMÈTRES — tout le damier s'effondrait
    sur un point et les mosaïques ressortaient vides. En mètres, la même
    décimale vaut dix centimètres. On cale donc la précision sur la maille :
    deux chiffres de plus qu'elle, soit un centième de maille, invisible.
    """
    from math import ceil, log10

    if cote <= 0:
        return 6
    return max(0, min(12, int(ceil(-log10(cote))) + 2))


def _wkt(mailles, cote):
    """Mailles d'un habitat en WKT.

    Les mailles voisines d'un même habitat sont fusionnées : elles se touchent,
    donc rien ne change à l'écran, mais les côtés communs quittent le fichier —
    un quart de son poids sur des mosaïques ordinaires.
    """
    if not mailles:
        return None
    return QgsGeometry.unaryUnion(mailles).asWkt(_decimales(cote))


def _proprietes(feature):
    return feature.get("properties") or {}


def _geometrie(feature):
    """QgsGeometry d'une entité GeoJSON, ou None si illisible.

    Par le WKT et non par `QgsJsonUtils.geometryFromGeoJson`, qui n'existe qu'à
    partir de QGIS 3.36 : sur une 3.28 — la version minimale annoncée — l'appel
    levait un `AttributeError` et le chargement d'un export échouait purement et
    simplement (cf. `processing.geojson_wkt`).
    """
    texte = gw.wkt((feature or {}).get("geometry"))
    if not texte:
        return None
    geom = QgsGeometry.fromWkt(texte)
    return None if geom is None or geom.isNull() else geom


def _coupe_pour_part(geom, emprise, aire_cible):
    """Hauteur sous laquelle le polygone couvre `aire_cible`."""
    bas, haut = emprise.yMinimum(), emprise.yMaximum()
    for _ in range(_ITERATIONS_COUPE):
        milieu = (bas + haut) / 2.0
        tranche = QgsGeometry.fromRect(QgsRectangle(
            emprise.xMinimum(), emprise.yMinimum(), emprise.xMaximum(), milieu
        ))
        if geom.intersection(tranche).area() < aire_cible:
            bas = milieu
        else:
            haut = milieu
    return (bas + haut) / 2.0


#: Estompage des limites entre bandes, en millimètres. Juste assez pour dire
#: « ce trait n'est pas une limite de terrain » : à 1,4 mm l'aplat perdait sa
#: franchise et la carte paraissait délavée.
_FLOU_MM = 0.3


def _est_polygone(layer):
    from qgis.core import QgsWkbTypes

    types = getattr(QgsWkbTypes, "GeometryType", QgsWkbTypes)
    return layer.geometryType() == types.PolygonGeometry


def _symbole_habitat(layer, couleur, mode):
    """Symbole d'un habitat selon le mode de représentation des mosaïques.

    Hors polygone (station ponctuelle ou linéaire), aucun de ces partages n'a
    de sens : on retombe sur un symbole plein ordinaire — comme pour un mode
    inconnu, qu'un fichier de projet plus ancien pourrait encore nommer.
    """
    if not _est_polygone(layer):
        symbole = QgsSymbol.defaultSymbol(layer.geometryType())
        symbole.setColor(QColor(couleur))
        return symbole
    if mode == MODE_BANDES:
        return _symbole_bandes(couleur)
    if mode == MODE_DAMIER:
        # Sans estompage : un damier n'a aucune chance d'être pris pour un
        # découpage de terrain, et flouter soixante mailles coûterait cher.
        return _symbole_decoupe(couleur, _EXPRESSION_MAILLES, flou=False)
    return _symbole_plein(couleur)


def _symbole_plein(couleur):
    symbole = QgsFillSymbol.createSimple({"color": couleur, "outline_style": "no"})
    symbole.setOpacity(0.85)
    return symbole


def _symbole_bandes(couleur):
    """Bandes horizontales proportionnelles au recouvrement."""
    return _symbole_decoupe(
        couleur, _EXPRESSION_BANDE.format(y_debut=CHAMP_Y_DEBUT, y_fin=CHAMP_Y_FIN)
    )


#: Mailles du damier, calculées au chargement ; le polygone entier hors mosaïque.
_EXPRESSION_MAILLES = 'coalesce(geom_from_wkt("%s"), $geometry)' % CHAMP_MAILLES


def _symbole_decoupe(couleur, expression, flou=True):
    """Symbole partageant le polygone selon `expression`.

    Deux couches dans UN symbole : la station en mosaïque est floutée, celle à un
    seul habitat reste nette. Chacune s'efface (couleur transparente) quand
    l'autre s'applique. Deux RÈGLES auraient dédoublé la légende.
    """
    symbole = QgsFillSymbol()
    symbole.changeSymbolLayer(
        0, _decoupe(couleur, expression, mosaique=True, flou=flou)
    )
    symbole.appendSymbolLayer(_decoupe(couleur, expression, mosaique=False))
    symbole.setOpacity(0.85)
    return symbole


def _decoupe(couleur, expression, mosaique, flou=True):
    """Couche de symbole découpant la part, visible pour ce seul cas de figure.

    Un polygone à un seul habitat n'a aucune séparation interne : l'estomper
    reviendrait à brouiller sa limite réelle pour rien.
    """
    condition = "=" if mosaique else "<>"
    remplissage = QgsFillSymbol.createSimple(
        {"color": couleur, "outline_style": "no"}
    )
    # `@symbol_color` et non la couleur en toutes lettres : l'expression ne sert
    # qu'à ÉTEINDRE la couche quand elle ne s'applique pas, jamais à décider de
    # la teinte. Écrite en dur, elle rendait la symbologie inmodifiable — on
    # changeait la couleur d'un habitat dans le panneau, la pastille de légende
    # suivait, la carte gardait l'ancienne.
    # `coalesce` : si une version de QGIS ne connaissait pas `@symbol_color`,
    # l'expression rendrait NULL — donc une couche invisible, et une carte
    # blanche. Le repli garde la couleur d'origine, celle d'avant ce correctif.
    remplissage.symbolLayer(0).setDataDefinedProperty(
        _PROP_COULEUR_FOND,
        QgsProperty.fromExpression(
            "if(\"%s\" %s 1, coalesce(@symbol_color, '%s'), color_rgba(0,0,0,0))"
            % (hs.CHAMP_MOSAIQUE, condition, couleur)
        ),
    )
    generateur = QgsGeometryGeneratorSymbolLayer.create({})
    generateur.setSymbolType(_SYMBOLE_SURFACIQUE)
    generateur.setGeometryExpression(expression)
    generateur.setSubSymbol(remplissage)
    if mosaique and flou and _FLOU_MM > 0:
        _adoucir(generateur)
    return generateur


def _adoucir(couche_symbole):
    """Estomper les limites entre bandes d'une même station.

    Une limite nette se lit comme une limite de terrain — or la bande dit une
    PROPORTION, pas un contour. Le flou l'annonce : ce trait-là n'existe pas.

    Posé sur la couche de symbole, donc sur les bandes seules : le contour de
    station est une règle à part et reste net, ce qui maintient la distinction
    entre la limite réelle (dessinée) et la séparation conventionnelle (floue).

    En millimètres et non en pixels, pour que l'estompage garde la même
    épaisseur à l'écran comme sur une planche à 300 ppp.
    """
    effet = QgsBlurEffect()
    effet.setBlurMethod(QgsBlurEffect.BlurMethod.StackBlur)  # bien plus rapide
    effet.setBlurLevel(_FLOU_MM)
    effet.setBlurUnit(_MILLIMETRES)
    couche_symbole.setPaintEffect(effet)


def _symbole_contour(layer, couleur="#37474f", epaisseur=0.26):
    """Contour sans remplissage."""
    if not _est_polygone(layer):
        return None
    return QgsFillSymbol.createSimple({
        "style": "no", "outline_color": couleur,
        "outline_width": "%s" % epaisseur, "outline_width_unit": "MM",
    })


class ExportLayerManager:
    """Écrit un export en GeoJSON et l'ajoute au projet, en lecture seule."""

    def __init__(self, directory, logger=None):
        self._directory = str(directory)
        self.logger = logger

    def show(self, libelle, features, mode=MODE_DEFAUT, typologie=None):
        """Charger `features` (liste GeoJSON) sous le nom `libelle`.

        `mode` choisit la représentation des mosaïques (cf. `MODES`).

        `typologie` (nom court : « corine », « eunis »…) cartographie les
        habitats dans CETTE typologie plutôt que dans celle où ils ont été
        déterminés — couleur, regroupement et légende suivent ensemble. Un
        habitat sans correspondance garde son habitat saisi : une carte ne doit
        pas perdre un polygone parce que HABREF ne sait pas le traduire.

        Returns:
            (QgsVectorLayer ou None, nombre d'entités réellement chargées).
        """
        features = [f for f in features or [] if isinstance(f, dict)]
        if not features:
            return None, 0
        # Champs de style calculés AVANT l'écriture : ils doivent exister dans le
        # fichier pour que la couche les porte (et qu'on puisse les relire dans
        # la table attributaire). `palette` en fait partie — elle repose la
        # couleur sur chaque entité, dont le rendu des mosaïques a besoin.
        hs.enrichir(features, typologie=typologie)
        palette = hs.palette(features, typologie)
        especes = pee.palette(features) if mode == MODE_PEE else ()
        # Chaque mode a ses besoins : inutile de payer la dichotomie des bandes
        # pour un semis de points.
        if mode in (MODE_BANDES, MODE_PEE):
            _poser_coupes(features)
        if mode == MODE_PEE:
            _poser_pee(features)
        elif mode == MODE_DAMIER:
            _poser_mailles(features)
        elif mode == MODE_ENJEUX:
            # Ni bandes ni mailles : la carte des enjeux colorie la STATION,
            # dont tous les habitats partagent le niveau.
            pass
        # Nom LIBRE, et fichier qui va avec : une couche déjà chargée peut avoir
        # été retouchée — couleurs, étiquettes, ordre — et enregistrée dans le
        # projet. La remplacer effacerait ce travail sans le dire. Le rechargement
        # d'un même export dépose donc une couche de plus, à côté.
        libelle = self._nom_libre(libelle)
        chemin = os.path.join(self._directory, "%s.geojson" % nom_de_fichier(libelle))
        collection = {"type": "FeatureCollection", "features": features}
        try:
            with open(chemin, "w", encoding="utf-8") as handle:
                json.dump(collection, handle)
        except OSError as exc:
            if self.logger:
                self.logger.warning("Écriture de l'export impossible : %s", exc)
            return None, 0

        layer = self._charger(chemin, libelle)
        if layer is None:
            return None, 0
        self._styler(layer, palette, mode, especes)
        QgsProject.instance().addMapLayer(layer, False)
        # EN TÊTE du groupe, pas à la suite : `addLayer` ajoute en dernier
        # enfant, c'est-à-dire SOUS les couches déjà là. Un deuxième export se
        # retrouvait caché par le premier, et on le croyait vide.
        self._group().insertLayer(0, layer)
        return layer, layer.featureCount()

    def _charger(self, chemin, nom, filtre=None):
        """Couche OGR lecture seule, éventuellement restreinte par `filtre`."""
        layer = QgsVectorLayer(chemin, nom, "ogr")
        if not layer.isValid():
            if self.logger:
                self.logger.warning("Couche d'export invalide : %s", chemin)
            return None
        if filtre:
            layer.setSubsetString(filtre)
        layer.setReadOnly(True)
        return layer

    def _styler(self, layer, palette, mode=MODE_DEFAUT, especes=()):
        """Colorer chaque habitat, partager les mosaïques selon `mode`.

        Le style ne doit jamais empêcher l'affichage : en cas de pépin, la
        couche reste chargée avec le rendu par défaut de QGIS.
        """
        try:
            layer.setRenderer(self._renderer(layer, palette, mode, especes))
            self._infobulle(layer)
        except Exception as exc:  # noqa: BLE001
            if self.logger:
                self.logger.warning("Symbologie non appliquée : %s", exc)

    @staticmethod
    def _infobulle(layer):
        """Infobulle carte : la composition chiffrée, que le figuré ne dit pas.

        Le figuré montre QUE plusieurs habitats se partagent le polygone,
        pas dans quelles proportions — d'où la composition, recouvrements compris.
        """
        layer.setMapTipTemplate(
            "<b>[% coalesce(\"nom_station\", 'Station sans nom') %]</b><br/>"
            "[% \"libelle_milieu\" %]"
            # D'où vient la couleur : sur une carto PVF1, elle est déduite des
            # codes Natura 2000 et non d'EUNIS. Le dire évite de prendre une
            # approximation pour une détermination.
            "[% coalesce(' (d''après ' || \"source_classe\" || ')', '') %]<br/>"
            "[% coalesce(\"composition\", 'aucun habitat') %]"
        )
        # Le libellé d'identification suit la même logique.
        layer.setDisplayExpression(
            "coalesce(\"nom_station\", \"nom_cite\", \"id_ligne\")"
        )

    @staticmethod
    def _renderer(layer, palette, mode=MODE_DEFAUT, especes=()):
        if mode == MODE_ENJEUX:
            return _renderer_enjeux(layer)
        rendu = _renderer_habitats(layer, palette, mode)
        if mode == MODE_PEE:
            _ajouter_regles_pee(rendu, especes)
        return rendu

    def cleanup(self):
        """Ne retirer que le groupe s'il est VIDE, au déchargement du plugin.

        Les couches d'export appartiennent au PROJET, pas à la session du
        plugin : on les recolore, on les range, on enregistre le projet. Les
        retirer au déchargement — c'est-à-dire à la fermeture de QGIS comme au
        rechargement de l'extension — effaçait ce travail, et un projet
        enregistré après coup en ressortait amputé.

        Le groupe vide, lui, ne sert à rien : il ne resterait qu'un dossier sans
        contenu dans le panneau des couches.
        """
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(GROUP_NAME)
        if group is not None and not group.children():
            root.removeChildNode(group)

    def _nom_libre(self, souhaite):
        """Nom de couche encore inutilisé dans le projet, en numérotant au besoin."""
        pris = {c.name() for c in QgsProject.instance().mapLayers().values()}
        if souhaite not in pris:
            return souhaite
        for numero in range(2, 100):
            candidat = "%s (%d)" % (souhaite, numero)
            if candidat not in pris:
                return candidat
        return "%s (%d)" % (souhaite, len(pris) + 1)

    # ------------------------------------------------------------- interne
    @staticmethod
    def _group():
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(GROUP_NAME)
        return group if group is not None else root.insertGroup(0, GROUP_NAME)


#: Colonne des taxons exotiques dans la vue d'export, et champs posés au
#: chargement pour les dessiner.
CHAMP_PEE = "habitat_pee"
CHAMP_PEE_POINTS = "pee_points"
#: Cercles visés par station. Douze suffisent à faire alterner trois espèces sans
#: couvrir le polygone : la carte dit une PRÉSENCE, pas une abondance, et un
#: semis dense se lirait comme une densité que la donnée ne contient pas.
_CERCLES_PAR_STATION = 8
#: Mailles calculées, avant tri. Bien plus que de cercles voulus : les mailles de
#: BORDURE sont écartées, et sur un polygone étroit ou découpé — une ripisylve,
#: un ourlet — elles sont la majorité. Une grille au plus juste ne laissait alors
#: que des échardes, et les cercles se posaient tous sur le contour.
_MAILLES_PEE = 40
#: Part de maille pleine en deçà de laquelle on n'y pose pas de cercle.
_PART_MAILLE_PLEINE = 0.55
#: Diamètre d'un cercle d'espèce, en millimètres.
_CERCLE_MM = 2.6


def _poser_pee(features, cle_station="id_station"):
    """Répartir les cercles des espèces exotiques, station par station.

    Les points sont posés sur une grille régulière et attribués aux espèces EN
    ALTERNANCE (cf. `pee.repartir`), puis écrits en JSON sur la seule entité
    dominante : les habitats d'une station partagent sa géométrie, et laisser
    chaque ligne poser ses cercles les empilerait au même endroit.
    """
    import json as _json

    stations = {}
    for feature in features or []:
        props = feature.get("properties") or {}
        stations.setdefault(props.get(cle_station), []).append(feature)

    for lot in stations.values():
        noms = []
        for feature in lot:
            for nom in pee.especes(_proprietes(feature).get(CHAMP_PEE)):
                if nom not in noms:
                    noms.append(nom)
        porteuse = next(
            (f for f in lot if _proprietes(f).get(hs.CHAMP_DOMINANT) == 1), lot[0]
        )
        if not noms:
            continue
        geom = _geometrie(lot[0])
        if geom is None or geom.isEmpty() or geom.area() <= 0:
            continue
        cote = (geom.area() / _MAILLES_PEE) ** 0.5
        pleine = cote * cote * _PART_MAILLE_PLEINE
        points = [maille.pointOnSurface()
                  for _rang, aire, maille in _mailles(geom, cote)
                  if aire >= pleine][:_CERCLES_PAR_STATION]
        if not points:  # polygone trop étroit pour une seule maille pleine
            points = [geom.pointOnSurface()]
        parts = pee.repartir(noms, points)
        if not parts:
            continue
        props = porteuse.setdefault("properties", {})
        props[CHAMP_PEE_POINTS] = _json.dumps(
            {nom: QgsGeometry.collectGeometry(pts).asWkt(_decimales(cote))
             for nom, pts in parts.items()},
            ensure_ascii=False,
        )
    return features


def _ajouter_regles_pee(rendu, especes):
    """Une règle par espèce, par-dessus les bandes d'habitats."""
    racine = rendu.rootRule()
    for nom, couleur in especes or []:
        regle = QgsRuleBasedRenderer.Rule(_symbole_pee(couleur, nom))
        regle.setLabel(nom)
        # Seule l'entité qui PORTE les points dessine : c'est elle qui a reçu
        # la répartition (cf. `_poser_pee`).
        regle.setFilterExpression(
            "map_get(from_json(\"%s\"), %s) is not null"
            % (CHAMP_PEE_POINTS, _litteral(nom))
        )
        racine.appendChild(regle)


def _symbole_pee(couleur, nom):
    """Cercles d'une espèce, posés aux points que l'entité porte.

    Le nom de l'espèce est écrit DANS l'expression, une règle par espèce :
    `@symbol_label` semblait plus élégant, mais la variable n'est pas résolue
    dans un générateur de géométrie — les cercles ne sortaient pas du tout,
    sans le moindre message.
    """
    # Taille FIXE, en millimètres. Une taille définie par données en unités de
    # carte semblait plus juste — le cercle aurait suivi la taille de la station
    # — mais les bornes en millimètres d'un `QgsMapUnitScale` ne s'appliquent
    # pas à une taille définie par données : sur des coordonnées en degrés, le
    # cercle tombait à deux centièmes de millimètre, donc invisible, sans le
    # moindre message. Un symbole de PRÉSENCE n'a de toute façon pas à changer
    # de taille : il dit oui ou non, pas combien.
    marqueur = QgsMarkerSymbol.createSimple({
        "name": "circle", "color": couleur,
        "outline_style": "solid", "outline_color": "#1a1a1a",
        "outline_width": "0.2", "outline_width_unit": "MM",
        "size": "%s" % _CERCLE_MM, "size_unit": "MM",
    })
    generateur = QgsGeometryGeneratorSymbolLayer.create({})
    generateur.setSymbolType(_SYMBOLE_PONCTUEL)
    generateur.setGeometryExpression(
        "geom_from_wkt(map_get(from_json(\"%s\"), %s))"
        % (CHAMP_PEE_POINTS, _litteral(nom))
    )
    generateur.setSubSymbol(marqueur)
    symbole = QgsFillSymbol()
    symbole.changeSymbolLayer(0, generateur)
    return symbole


#: Colonne de l'enjeu de la station dans la vue d'export.
CHAMP_ENJEU = "station_niveau_enjeu"
#: Trait des contours sur la carte des enjeux. Fin et gris très sombre plutôt
#: que noir et épais : sur des aplats clairs — jaune, orange, rose — un trait
#: noir de 0,26 mm écrase la couleur et fait ressortir le découpage plus que le
#: propos de la carte, qui est le niveau d'enjeu.
_CONTOUR_ENJEUX = "#1a1a1a"
_CONTOUR_ENJEUX_MM = 0.16


def _renderer_enjeux(layer):
    """Rendu par NIVEAU D'ENJEU de la station, contours des habitats par-dessus.

    Une autre carte que celle des habitats : ici la couleur ne dit pas ce qui
    pousse, mais ce qui est en jeu. Le niveau appartient à la STATION, que ses
    habitats se partagent — seule l'entité dominante peint donc le fond, sinon
    les lignes d'une mosaïque repeindraient trois fois le même polygone, pour
    rien et en plus sombre.

    Les contours d'habitats passent par-dessus les aplats grâce aux **niveaux de
    symboles** : l'ordre des règles reste celui de la légende — contours en
    tête, comme sur les planches « Flore Ariège » — sans commander l'ordre de
    dessin, qui est celui des passes.
    """
    racine = QgsRuleBasedRenderer.Rule(None)

    contour = _symbole_contour(layer, _CONTOUR_ENJEUX, _CONTOUR_ENJEUX_MM)
    if contour is not None:
        _passe(contour, 1)  # dessiné APRÈS les aplats
        regle = QgsRuleBasedRenderer.Rule(contour)
        regle.setLabel("Contours habitats")
        # UNE fois par station, pas une par ligne. Les habitats d'une mosaïque
        # partagent la géométrie de leur station : sans ce filtre, le même
        # contour était retracé trois fois au même endroit, et l'empilement le
        # faisait grossir et noircir — le trait paraissait sale.
        regle.setFilterExpression('"%s" = 1' % hs.CHAMP_DOMINANT)
        racine.appendChild(regle)

    for code, libelle, couleur in ref.COULEURS_ENJEU:
        symbole = _symbole_plein(couleur)
        _passe(symbole, 0)
        regle = QgsRuleBasedRenderer.Rule(symbole)
        regle.setLabel(libelle)
        regle.setFilterExpression(_filtre_enjeu(code))
        racine.appendChild(regle)

    rendu = QgsRuleBasedRenderer(racine)
    rendu.setUsingSymbolLevels(True)
    return rendu


def _filtre_enjeu(code):
    """Filtre d'un niveau d'enjeu ; le dernier ramasse tout ce qui n'en a pas."""
    dominant = '"%s" = 1' % hs.CHAMP_DOMINANT
    if code:
        return '%s AND "%s" = %s' % (dominant, CHAMP_ENJEU, _litteral(code))
    connus = [c for c, _l, _co in ref.COULEURS_ENJEU if c]
    return '%s AND ("%s" IS NULL OR "%s" NOT IN (%s))' % (
        dominant, CHAMP_ENJEU, CHAMP_ENJEU,
        ", ".join(_litteral(c) for c in connus),
    )


def _passe(symbole, numero):
    """Ranger toutes les couches d'un symbole dans une passe de dessin."""
    for i in range(symbole.symbolLayerCount()):
        symbole.symbolLayer(i).setRenderingPass(numero)


def _renderer_habitats(layer, palette, mode=MODE_DEFAUT):
    """Rendu par règles : UNE COULEUR PAR HABITAT, groupées par grand milieu.

    La légende a deux niveaux — le grand milieu porte le groupe, chaque
    habitat sa nuance — ce qui permet de replier un milieu entier dans le
    panneau des couches.

    Une station en mosaïque occupe plusieurs entités superposées, et toutes
    sont dessinées : chacune ne peint que SA part du polygone (bande, anneau
    ou semis, selon le mode), si bien qu'aucune n'en masque une autre.
    """
    racine = QgsRuleBasedRenderer.Rule(None)
    for classe, libelle_milieu, habitats in palette or []:
        # Règle-groupe sans symbole : elle ne dessine rien, elle range.
        groupe = QgsRuleBasedRenderer.Rule(None)
        # EN CAPITALES, faute de pouvoir les mettre en gras : QGIS rend les
        # règles-groupes d'un rendu par règles comme de simples entrées de
        # légende (`QgsSymbolLegendNode`), au même style que les habitats.
        # Elles se lisaient donc à la même hauteur qu'eux, sans qu'on voie
        # que c'étaient des titres. La capitale est le procédé classique
        # quand la graisse n'est pas disponible.
        groupe.setLabel((libelle_milieu or "").upper())
        racine.appendChild(groupe)
        for cle, libelle, couleur in habitats:
            regle = QgsRuleBasedRenderer.Rule(_symbole_habitat(layer, couleur, mode))
            regle.setLabel(libelle)
            regle.setFilterExpression(
                '"%s" = %s' % (hs.CHAMP_CLE, _litteral(cle))
            )
            groupe.appendChild(regle)

    contour = _symbole_contour(layer)
    if contour is not None:
        # Un seul contour par station, porté par l'habitat dominant : le
        # contour de chaque bande dessinerait de fausses limites d'habitat.
        regle = QgsRuleBasedRenderer.Rule(contour)
        regle.setLabel("limite de station")
        regle.setFilterExpression('"%s" = 1' % hs.CHAMP_DOMINANT)
        racine.appendChild(regle)
    return QgsRuleBasedRenderer(racine)
