# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Affichage des stations locales sur le canevas QGIS.

La base SQLite est la source de vérité ; ces couches en sont un **miroir en
lecture seule**. Une couche mémoire par type de géométrie (point / ligne /
polygone, en EPSG:4326) est regroupée sous « OccHab (local) » et reconstruite à
chaque rafraîchissement. Les entités sont colorées selon l'état de synchro.

Les couches sont suivies par leur identifiant (pas par référence directe) pour
rester robustes si l'utilisateur les supprime du projet.
"""
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsRendererCategory,
    QgsSymbol,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

GROUP_NAME = "OccHab (local)"

_LAYER_DEF = {
    "point": ("Point", "OccHab – Stations (points)"),
    "line": ("LineString", "OccHab – Stations (lignes)"),
    "polygon": ("Polygon", "OccHab – Stations (polygones)"),
}
_FIELDS_URI = (
    "&field=id:integer&field=id_station:integer&field=station_name:string(255)"
    "&field=nb_habitats:integer&field=id_dataset:integer&field=date_min:string(30)"
    "&field=sync_status:string(20)"
)
_SYNC_STYLE = {
    "pending": ("#e69100", "À synchroniser"),
    "synced": ("#2e7d32", "Synchronisée"),
    "to_delete": ("#9e9e9e", "À supprimer"),
    "error": ("#c62828", "Erreur"),
}


class StationLayerManager:
    """Maintient les couches carte reflétant les stations locales."""

    def __init__(self, logger=None):
        self.logger = logger
        self._layer_ids = {}  # geom_type -> id de couche

    # ------------------------------------------------------------- API
    def refresh(self, stations):
        """Reconstruire les entités des couches à partir des stations locales."""
        buckets = {"point": [], "line": [], "polygon": []}
        for station in stations:
            geom_type = (station.get("geom_type") or "").lower()
            wkt = station.get("geom")
            if geom_type in buckets and wkt:
                geom = QgsGeometry.fromWkt(wkt)
                if not geom.isNull():
                    buckets[geom_type].append((station, geom))
        for geom_type, items in buckets.items():
            self._update_layer(geom_type, items)

    def extent(self):
        """Emprise combinée (EPSG:4326) des couches non vides, ou None."""
        rect = None
        for layer_id in self._layer_ids.values():
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer is None or layer.featureCount() == 0:
                continue
            layer.updateExtents()
            extent = layer.extent()
            if rect is None:
                rect = QgsRectangle(extent)
            else:
                rect.combineExtentWith(extent)
        return rect

    def export_geopackage(self, path):
        """Exporter les couches affichées (vue courante) en GeoPackage.

        Retourne le nombre d'entités écrites. Lève une exception en cas d'échec.
        """
        layers = []
        for layer_id in self._layer_ids.values():
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer is not None and layer.featureCount() > 0:
                layers.append(layer)
        if not layers:
            raise ValueError("Aucune station à exporter.")

        context = QgsProject.instance().transformContext()
        total = 0
        for index, layer in enumerate(layers):
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer.name()
            options.actionOnExistingFile = (
                QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
                if index == 0
                else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            )
            result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, path, context, options
            )
            if result[0] != QgsVectorFileWriter.WriterError.NoError:
                raise RuntimeError(result[1])
            total += layer.featureCount()
        return total

    def cleanup(self):
        """Retirer les couches et le groupe (au déchargement du plugin)."""
        for layer_id in self._layer_ids.values():
            try:
                QgsProject.instance().removeMapLayer(layer_id)
            except (RuntimeError, KeyError):
                pass
        self._layer_ids = {}
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(GROUP_NAME)
        if group is not None:
            root.removeChildNode(group)

    # ------------------------------------------------------------- interne
    def _update_layer(self, geom_type, items):
        layer = self._ensure_layer(geom_type, create=bool(items))
        if layer is None:
            return
        provider = layer.dataProvider()
        provider.truncate()  # vider avant de reconstruire
        if items:
            provider.addFeatures(self._features(layer, items))
        layer.updateExtents()
        layer.triggerRepaint()

    def _ensure_layer(self, geom_type, create):
        layer_id = self._layer_ids.get(geom_type)
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        if layer is not None:
            return layer
        if not create:
            return None
        return self._create_layer(geom_type)

    def _create_layer(self, geom_type):
        wkb, name = _LAYER_DEF[geom_type]
        uri = "%s?crs=EPSG:4326%s" % (wkb, _FIELDS_URI)
        layer = QgsVectorLayer(uri, name, "memory")
        layer.setReadOnly(True)
        layer.setRenderer(self._renderer(layer))
        QgsProject.instance().addMapLayer(layer, False)
        self._group().addLayer(layer)
        self._layer_ids[geom_type] = layer.id()
        return layer

    @staticmethod
    def _group():
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(GROUP_NAME)
        if group is None:
            group = root.insertGroup(0, GROUP_NAME)
        return group

    @staticmethod
    def _renderer(layer):
        categories = []
        for value, (color, label) in _SYNC_STYLE.items():
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            symbol.setColor(QColor(color))
            symbol.setOpacity(0.7)
            categories.append(QgsRendererCategory(value, symbol, label))
        return QgsCategorizedSymbolRenderer("sync_status", categories)

    @staticmethod
    def _features(layer, items):
        fields = layer.fields()
        features = []
        for station, geom in items:
            feature = QgsFeature(fields)
            feature.setGeometry(geom)
            feature["id"] = station.get("id")
            feature["id_station"] = station.get("id_station")
            feature["station_name"] = station.get("station_name")
            feature["nb_habitats"] = station.get("_nb_habitats")
            feature["id_dataset"] = station.get("id_dataset")
            feature["date_min"] = station.get("date_min")
            feature["sync_status"] = station.get("sync_status")
            features.append(feature)
        return features
