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
    QgsProperty,
    QgsFillSymbol,
    QgsGeometryGeneratorSymbolLayer,
    QgsProject,
    QgsRuleBasedRenderer,
    QgsSymbol,
    QgsSymbolLayer,
    QgsVectorLayer,
)

from ..processing import habitat_style as hs

GROUP_NAME = "OccHab (exports)"


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


#: Découpe d'un polygone en bandes horizontales proportionnelles au recouvrement.
#: Chaque habitat d'une mosaïque occupe la sienne, en APLAT PLEIN.
#:
#: Remplace des hachures colorées superposées, illisibles dès que la carte se
#: densifie : il fallait comprendre que la hachure reprenait la couleur d'un
#: autre poste de légende, et trois couches translucides sur la même géométrie
#: saturaient tout. Ici plus aucune superposition — la lisibilité d'une carte
#: mono-habitat, quelle que soit la densité.
#:
#: Les bornes sont des pourcentages cumulés calculés à l'export
#: (`habitat_style._bandes`) : les faire calculer par une expression QGIS
#: demanderait un `aggregate` par entité, ruineux au rendu.
_EXPRESSION_BANDE = """intersection($geometry, make_polygon(make_line(
    make_point(x_min($geometry), y_min($geometry) + (y_max($geometry) - y_min($geometry)) * "{debut}" / 100),
    make_point(x_max($geometry), y_min($geometry) + (y_max($geometry) - y_min($geometry)) * "{debut}" / 100),
    make_point(x_max($geometry), y_min($geometry) + (y_max($geometry) - y_min($geometry)) * "{fin}" / 100),
    make_point(x_min($geometry), y_min($geometry) + (y_max($geometry) - y_min($geometry)) * "{fin}" / 100),
    make_point(x_min($geometry), y_min($geometry) + (y_max($geometry) - y_min($geometry)) * "{debut}" / 100))))"""


#: Estompage des limites entre bandes, en millimètres. Juste assez pour dire
#: « ce trait n'est pas une limite de terrain » : à 1,4 mm l'aplat perdait sa
#: franchise et la carte paraissait délavée.
_FLOU_MM = 0.3


def _est_polygone(layer):
    from qgis.core import QgsWkbTypes

    types = getattr(QgsWkbTypes, "GeometryType", QgsWkbTypes)
    return layer.geometryType() == types.PolygonGeometry


def _symbole_bande(layer, couleur):
    """Aplat de `couleur` limité à la bande de l'habitat.

    Hors polygone (station ponctuelle ou linéaire), le découpage n'a pas de sens :
    on retombe sur un symbole plein ordinaire.
    """
    if not _est_polygone(layer):
        symbole = QgsSymbol.defaultSymbol(layer.geometryType())
        symbole.setColor(QColor(couleur))
        return symbole

    # Deux couches dans UN symbole : la station en mosaïque est floutée, celle
    # à un seul habitat reste nette. Chacune s'efface (couleur transparente)
    # quand l'autre s'applique. Deux RÈGLES auraient dédoublé la légende.
    symbole = QgsFillSymbol()
    symbole.changeSymbolLayer(0, _bande(couleur, mosaique=True))
    symbole.appendSymbolLayer(_bande(couleur, mosaique=False))
    symbole.setOpacity(0.85)
    return symbole


def _bande(couleur, mosaique):
    """Couche de symbole découpant la bande, visible pour ce seul cas de figure.

    Un polygone à un seul habitat n'a aucune séparation interne : l'estomper
    reviendrait à brouiller sa limite réelle pour rien.
    """
    condition = "=" if mosaique else "<>"
    remplissage = QgsFillSymbol.createSimple(
        {"color": couleur, "outline_style": "no"}
    )
    remplissage.symbolLayer(0).setDataDefinedProperty(
        QgsSymbolLayer.Property.FillColor,
        QgsProperty.fromExpression(
            "if(\"%s\" %s 1, '%s', color_rgba(0,0,0,0))"
            % (hs.CHAMP_MOSAIQUE, condition, couleur)
        ),
    )
    generateur = QgsGeometryGeneratorSymbolLayer.create({})
    generateur.setSymbolType(Qgis.SymbolType.Fill)
    generateur.setGeometryExpression(
        _EXPRESSION_BANDE.format(debut=hs.CHAMP_DEBUT, fin=hs.CHAMP_FIN)
    )
    generateur.setSubSymbol(remplissage)
    if mosaique:
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
    effet.setBlurUnit(Qgis.RenderUnit.Millimeters)
    couche_symbole.setPaintEffect(effet)


def _symbole_contour(layer):
    """Contour de la station, sans remplissage."""
    if not _est_polygone(layer):
        return None
    return QgsFillSymbol.createSimple({
        "style": "no", "outline_color": "#37474f",
        "outline_width": "0.26", "outline_width_unit": "MM",
    })


class ExportLayerManager:
    """Écrit un export en GeoJSON et l'ajoute au projet, en lecture seule."""

    def __init__(self, directory, logger=None):
        self._directory = str(directory)
        self.logger = logger

    def show(self, libelle, features):
        """Charger `features` (liste GeoJSON) sous le nom `libelle`.

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
        hs.enrichir(features)
        palette = hs.palette(features)
        chemin = os.path.join(self._directory, "%s.geojson" % nom_de_fichier(libelle))
        collection = {"type": "FeatureCollection", "features": features}
        try:
            with open(chemin, "w", encoding="utf-8") as handle:
                json.dump(collection, handle)
        except OSError as exc:
            if self.logger:
                self.logger.warning("Écriture de l'export impossible : %s", exc)
            return None, 0

        # Une couche du même nom serait un doublon muet : on remplace.
        self._retirer(libelle)
        layer = QgsVectorLayer(chemin, libelle, "ogr")
        if not layer.isValid():
            if self.logger:
                self.logger.warning("Couche d'export invalide : %s", chemin)
            return None, 0
        layer.setReadOnly(True)
        self._styler(layer, palette)
        QgsProject.instance().addMapLayer(layer, False)
        self._group().addLayer(layer)
        return layer, layer.featureCount()

    # ------------------------------------------------------------ symbologie
    def _styler(self, layer, palette):
        """Colorer chaque habitat, partager les mosaïques en bandes.

        Le style ne doit jamais empêcher l'affichage : en cas de pépin, la
        couche reste chargée avec le rendu par défaut de QGIS.
        """
        try:
            layer.setRenderer(self._renderer(layer, palette))
            self._infobulle(layer)
        except Exception as exc:  # noqa: BLE001
            if self.logger:
                self.logger.warning("Symbologie non appliquée : %s", exc)

    @staticmethod
    def _infobulle(layer):
        """Infobulle carte : la composition chiffrée, que les hachures ne disent pas.

        Les hachures montrent QUE plusieurs habitats se partagent le polygone,
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
    def _renderer(layer, palette):
        """Rendu par règles : UNE COULEUR PAR HABITAT, groupées par grand milieu.

        La légende a deux niveaux — le grand milieu porte le groupe, chaque
        habitat sa nuance — ce qui permet de replier un milieu entier dans le
        panneau des couches.

        Une station en mosaïque occupe plusieurs entités superposées, et toutes
        sont dessinées : aplat pour l'habitat dominant, hachures de leur propre
        couleur pour les suivants. Des aplats superposés se masqueraient les uns
        les autres — des hachures se lisent ensemble.
        """
        racine = QgsRuleBasedRenderer.Rule(None)
        for classe, libelle_milieu, habitats in palette or []:
            # Règle-groupe sans symbole : elle ne dessine rien, elle range.
            groupe = QgsRuleBasedRenderer.Rule(None)
            groupe.setLabel(libelle_milieu)
            racine.appendChild(groupe)
            for cle, libelle, couleur in habitats:
                regle = QgsRuleBasedRenderer.Rule(_symbole_bande(layer, couleur))
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

    def cleanup(self):
        """Retirer le groupe et ses couches (au déchargement du plugin)."""
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(GROUP_NAME)
        if group is None:
            return
        for node in group.findLayers():
            layer = node.layer()
            if layer is not None:
                try:
                    QgsProject.instance().removeMapLayer(layer.id())
                except (RuntimeError, KeyError):
                    pass
        root.removeChildNode(group)

    # ------------------------------------------------------------- interne
    def _retirer(self, nom):
        group = QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME)
        if group is None:
            return
        for node in group.findLayers():
            layer = node.layer()
            if layer is not None and layer.name() == nom:
                try:
                    QgsProject.instance().removeMapLayer(layer.id())
                except (RuntimeError, KeyError):
                    pass

    @staticmethod
    def _group():
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(GROUP_NAME)
        return group if group is not None else root.insertGroup(0, GROUP_NAME)
