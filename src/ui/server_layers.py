"""Couche de contexte : stations déjà présentes sur GeoNature (lecture seule).

Quand on est connecté et qu'un JDD précis est sélectionné, on récupère ses
stations depuis l'API (`GET /occhab/stations/?format=geojson&id_dataset=…`) et on
les affiche en **lecture seule**, dans un style distinct, sous le groupe
« OccHab (serveur) ». Objectif : voir l'existant pour se repérer et éviter les
doublons — sans pouvoir l'éditer depuis QGIS.

La FeatureCollection est écrite dans un fichier GeoJSON temporaire, chargé via le
fournisseur OGR (qui gère nativement les géométries mixtes point/ligne/polygone).
"""
import json

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsVectorLayer,
)

from .station_layers import GROUP_NAME as LOCAL_GROUP_NAME

GROUP_NAME = "OccHab (serveur)"
LAYER_NAME = "OccHab — stations serveur"
_COLOR = "#1565c0"  # bleu, distinct des couches locales (colorées par sync)


class ServerStationLayerManager:
    """Affiche/retire la couche de contexte des stations serveur d'un JDD."""

    def __init__(self, file_path, logger=None):
        self._file = str(file_path)
        self.logger = logger
        self._layer_id = None

    def show(self, feature_collection):
        """Afficher une FeatureCollection serveur. Retourne le nombre de stations."""
        self.clear()  # libère la couche/fichier précédents avant réécriture
        features = []
        if isinstance(feature_collection, dict):
            features = feature_collection.get("features") or []
        try:
            with open(self._file, "w", encoding="utf-8") as handle:
                json.dump(feature_collection, handle)
        except OSError as exc:
            if self.logger:
                self.logger.warning("Écriture GeoJSON serveur impossible : %s", exc)
            return 0
        if not features:
            return 0

        layer = QgsVectorLayer(self._file, LAYER_NAME, "ogr")
        if not layer.isValid():
            if self.logger:
                self.logger.warning("Couche serveur invalide (GeoJSON)")
            return 0
        layer.setReadOnly(True)
        self._style(layer)
        QgsProject.instance().addMapLayer(layer, False)
        self._group().addLayer(layer)
        self._layer_id = layer.id()
        return len(features)

    def selected_id_stations(self):
        """id_station des entités sélectionnées dans la couche serveur."""
        ids = []
        if not self._layer_id:
            return ids
        layer = QgsProject.instance().mapLayer(self._layer_id)
        if layer is None:
            return ids
        if layer.fields().indexOf("id_station") < 0:
            # Sans id_station fiable, ne pas retomber sur le fid OGR (mauvais import).
            return ids
        for feature in layer.selectedFeatures():
            value = feature["id_station"]
            try:
                if value:
                    ids.append(int(value))
            except (TypeError, ValueError):
                pass
        return ids

    def extent(self):
        """Emprise (EPSG:4326) de la couche serveur, ou None si absente/vide."""
        if not self._layer_id:
            return None
        layer = QgsProject.instance().mapLayer(self._layer_id)
        if layer is None:
            return None
        layer.updateExtents()
        ext = layer.extent()
        return ext if ext is not None and not ext.isEmpty() else None

    def clear(self):
        """Retirer la couche serveur (sans toucher au groupe)."""
        if self._layer_id:
            try:
                QgsProject.instance().removeMapLayer(self._layer_id)
            except (RuntimeError, KeyError):
                pass
        self._layer_id = None

    def cleanup(self):
        """Retirer la couche et le groupe (au déchargement du plugin)."""
        self.clear()
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(GROUP_NAME)
        if group is not None:
            root.removeChildNode(group)

    # ------------------------------------------------------------- interne
    @staticmethod
    def _group():
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(GROUP_NAME)
        if group is not None:
            return group
        # Placer le serveur JUSTE SOUS le groupe local (contexte de fond).
        local = root.findGroup(LOCAL_GROUP_NAME)
        if local is not None and local in root.children():
            index = root.children().index(local) + 1
            return root.insertGroup(index, GROUP_NAME)
        return root.insertGroup(0, GROUP_NAME)

    @staticmethod
    def _style(layer):
        try:
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            if symbol is None:
                return
            symbol.setColor(QColor(_COLOR))
            symbol.setOpacity(0.55)
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        except Exception:  # noqa: BLE001 - le style ne doit pas bloquer l'affichage
            pass
