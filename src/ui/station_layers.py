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
    "synced": ("#1565c0", "Synchronisée"),
    "conflict": ("#c62828", "Conflit"),
    "to_delete": ("#9e9e9e", "À supprimer"),
}


class StationLayerManager:
    """Maintient les couches carte reflétant les stations locales."""

    def __init__(self, logger=None):
        self.logger = logger
        self._layer_ids = {}  # geom_type -> id de couche
        self._ecouteurs = []  # callables notifiés d'un changement de sélection carte
        self._branchees = set()  # ids de couches déjà connectées au signal
        # Vrai pendant qu'on applique une sélection : sans ce verrou, notifier
        # relancerait le tableau, qui re-sélectionnerait la carte, en boucle.
        self._application_en_cours = False

    # -------------------------------------------------------- sélection
    def add_selection_listener(self, callback):
        """Être averti quand l'utilisateur change la sélection sur la carte."""
        if callback not in self._ecouteurs:
            self._ecouteurs.append(callback)

    def remove_selection_listener(self, callback):
        if callback in self._ecouteurs:
            self._ecouteurs.remove(callback)

    def select_stations(self, ids):
        """Sélectionner sur la carte les entités des stations données (ids locaux)."""
        voulus = {int(i) for i in ids or [] if i is not None}
        self._application_en_cours = True
        try:
            for layer in self.existing_layers():
                if voulus:
                    layer.selectByExpression(
                        '"id" IN (%s)' % ", ".join(str(i) for i in sorted(voulus))
                    )
                else:
                    layer.removeSelection()
        finally:
            self._application_en_cours = False

    def selected_station_ids(self):
        """Ids locaux des stations actuellement sélectionnées sur la carte."""
        ids = []
        for layer in self.existing_layers():
            for feature in layer.selectedFeatures():
                try:
                    ids.append(int(feature["id"]))
                except (TypeError, ValueError, KeyError):
                    continue
        return ids

    def _notifier_selection(self):
        if self._application_en_cours:
            return  # sélection posée par nous : ne pas boucler
        for callback in list(self._ecouteurs):
            try:
                callback()
            except Exception as exc:  # noqa: BLE001 - un écouteur ne doit pas casser la carte
                if self.logger:
                    self.logger.warning("Écouteur de sélection en échec : %s", exc)

    def _brancher_selection(self, layer):
        """Connecter une couche au signal de sélection (une seule fois)."""
        if layer is None or layer.id() in self._branchees:
            return
        layer.selectionChanged.connect(lambda *_: self._notifier_selection())
        self._branchees.add(layer.id())

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
        # Vider les couches vide aussi leur sélection, ce qui émettrait un
        # changement de sélection : les tableaux croiraient que l'utilisateur a
        # tout désélectionné. Une reconstruction n'est pas un geste de l'utilisateur.
        self._application_en_cours = True
        try:
            for geom_type, items in buckets.items():
                self._update_layer(geom_type, items)
        finally:
            self._application_en_cours = False

    def existing_layers(self):
        """Couches locales actuellement présentes dans le projet (non nulles)."""
        layers = []
        for layer_id in self._layer_ids.values():
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer is not None:
                layers.append(layer)
        return layers

    def couches_reference(self, geom_type):
        """Couches sur lesquelles s'accrocher pour saisir une géométrie de ce type.

        Les stations du MÊME type : une mosaïque se construit entre polygones.
        Liste (vide si la couche n'existe pas encore), pour que l'appelant n'ait
        pas à distinguer le cas « aucune station saisie ».
        """
        layer_id = self._layer_ids.get(geom_type)
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        return [layer] if layer is not None else []

    def geometries_wkt(self, geom_type, exclure_id=None):
        """WKT (EPSG:4326) des entités AFFICHÉES pour ce type, hors `exclure_id`.

        Sert de jeu de voisins à la numérisation jointive. On lit la couche, et
        non la base : le jeu d'obstacles est alors exactement ce que
        l'utilisateur voit et sur quoi il peut s'accrocher — même filtre JDD.
        Une station découpée contre une voisine invisible serait incompréhensible.

        `exclure_id` est l'identifiant LOCAL de la station en cours de
        re-numérisation : sans lui, elle se découperait contre elle-même.
        """
        layer_id = self._layer_ids.get(geom_type)
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        if layer is None:
            return []
        wkts = []
        for feature in layer.getFeatures():
            if exclure_id is not None:
                try:
                    if int(feature["id"]) == int(exclure_id):
                        continue
                except (TypeError, ValueError, KeyError):
                    pass
            geometry = feature.geometry()
            if geometry is not None and not geometry.isNull() and not geometry.isEmpty():
                wkts.append(geometry.asWkt())
        return wkts

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
        ids = set(self._layer_ids.values())
        group = self._find_group()
        if group is not None:
            for node in group.findLayers():
                layer = node.layer()
                if layer is not None:
                    ids.add(layer.id())
        for layer_id in ids:
            try:
                QgsProject.instance().removeMapLayer(layer_id)
            except (RuntimeError, KeyError):
                pass
        self._layer_ids = {}
        self._branchees = set()
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
        # Les entités sont écrites DIRECTEMENT dans le provider : QgsVectorLayer
        # n'émet alors aucun des signaux auxquels l'index d'accrochage
        # (QgsPointLocator) est abonné, et ni updateExtents() ni triggerRepaint()
        # ne l'invalident. Le canevas redessinait donc les nouvelles stations
        # pendant que l'accrochage travaillait encore sur l'ancien jeu : une
        # station fraîchement saisie ne s'accrochait pas, et une station
        # supprimée s'accrochait encore, à l'endroit qu'elle occupait.
        layer.emitDataChanged()
        layer.triggerRepaint()

    def _ensure_layer(self, geom_type, create):
        layer_id = self._layer_ids.get(geom_type)
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        if layer is not None:
            self._brancher_selection(layer)
            return layer
        # Cache Python vide (nouvelle instance du manager : rechargement du
        # plugin, nouvelle session QGIS, projet .qgz rouvert...) : chercher une
        # couche de même nom déjà présente dans un groupe existant avant d'en
        # créer une nouvelle, pour éviter un doublon visuel dans le panneau.
        group = self._find_group()
        if group is not None:
            _, name = _LAYER_DEF[geom_type]
            reused = self._reuse_layer(group, name)
            if reused is not None:
                self._layer_ids[geom_type] = reused.id()
                self._brancher_selection(reused)
                return reused
        if not create:
            return None
        return self._create_layer(geom_type, group)

    def _create_layer(self, geom_type, group=None):
        wkb, name = _LAYER_DEF[geom_type]
        uri = "%s?crs=EPSG:4326%s" % (wkb, _FIELDS_URI)
        layer = QgsVectorLayer(uri, name, "memory")
        layer.setReadOnly(True)
        # Sans cela, QGIS avertit à la fermeture que « le contenu sera
        # définitivement perdu ». C'est faux ici : ces couches ne sont qu'un
        # affichage, reconstruit depuis la base SQLite à chaque rafraîchissement.
        # L'avertissement pousserait à croire à une perte de données inexistante.
        layer.setCustomProperty("skipMemoryLayersCheck", 1)
        layer.setRenderer(self._renderer(layer))
        QgsProject.instance().addMapLayer(layer, False)
        (group or self._group()).addLayer(layer)
        self._layer_ids[geom_type] = layer.id()
        self._brancher_selection(layer)
        return layer

    @staticmethod
    def _find_group():
        """Groupe local existant, sans le créer (évite un groupe vide)."""
        return QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME)

    @staticmethod
    def _reuse_layer(group, name):
        """Retrouver une couche `name` dans `group` (recherche par nom, pas par id).

        S'il existe plusieurs couches de même nom (doublons hérités d'avant ce
        correctif), la première est conservée et les suivantes sont supprimées du
        projet — c'est la donnée en base SQLite qui fait foi, ces couches ne sont
        qu'un miroir, aucune perte n'est possible.
        """
        matches = [
            node.layer() for node in group.findLayers()
            if node.layer() is not None and node.layer().name() == name
        ]
        if not matches:
            return None
        keeper, *extras = matches
        for extra in extras:
            try:
                QgsProject.instance().removeMapLayer(extra.id())
            except (RuntimeError, KeyError):
                pass
        return keeper

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
