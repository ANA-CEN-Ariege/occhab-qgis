"""Numérisation de la géométrie d'une station avec l'outil natif de QGIS.

`QgsMapToolDigitizeFeature` (accrochage, saisie CAD, annulation de sommet,
traçage) numérise dans une couche vectorielle. Son contrat : la couche cible
doit être **enregistrée dans le projet et en mode édition**. Comme on ne veut pas
toucher aux couches de l'utilisateur, on utilise une couche mémoire temporaire,
ajoutée au projet sans être affichée, mise en édition, puis retirée à la fin.

Deux pièges de cycle de vie, gérés ici :

1. `digitizingCompleted(QgsFeature)` est émis DEPUIS le code natif de l'outil.
   Détruire l'outil/la couche dans le slot → access violation. Tout le nettoyage
   est donc **différé** via QTimer.singleShot.
2. Une nouvelle session peut démarrer alors qu'un nettoyage différé est encore en
   attente. On utilise un **jeton de session** (les callbacks d'une session
   périmée sont ignorés) et on **préserve l'outil d'origine réel** entre sessions
   pour ne jamais restaurer un de nos propres outils déjà supprimé.
"""
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import QPushButton
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import QgsMapToolCapture, QgsMapToolDigitizeFeature

from ..processing.geometry import geometry_to_wkt_4326

_CAPTURE_MODE = {
    "point": QgsMapToolCapture.CaptureMode.CapturePoint,
    "line": QgsMapToolCapture.CaptureMode.CaptureLine,
    "polygon": QgsMapToolCapture.CaptureMode.CapturePolygon,
}
_WKB_TYPE = {"point": "Point", "line": "LineString", "polygon": "Polygon"}


class GeometryCaptureController(QObject):
    """Pilote une session de numérisation et émet la géométrie en EPSG:4326."""

    captured = pyqtSignal(str, str)  # wkt (EPSG:4326), geom_type
    cancelled = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._canvas = iface.mapCanvas()
        self._tool = None
        self._layer = None
        self._prev_tool = None
        self._geom_type = None
        self._pending_wkt = None
        self._finished = False
        self._session = 0

    # --------------------------------------------------------------- API
    def start(self, geom_type):
        """Démarrer une numérisation (nettoie proprement une session résiduelle)."""
        self._session += 1  # invalide les callbacks différés en attente
        # Conserver l'outil d'origine réel si une session traîne encore.
        original_prev = self._prev_tool if self._tool is not None else None
        self._teardown(restore_tool=False)

        self._finished = False
        self._geom_type = geom_type if geom_type in _CAPTURE_MODE else "polygon"
        self._pending_wkt = None

        crs = self._canvas.mapSettings().destinationCrs()
        self._layer = self._make_layer(self._geom_type, crs)
        # La couche doit être dans le projet ET éditable pour l'outil natif.
        QgsProject.instance().addMapLayer(self._layer, False)
        self._layer.startEditing()

        self._prev_tool = original_prev if original_prev is not None else self._canvas.mapTool()
        self._tool = QgsMapToolDigitizeFeature(
            self._canvas, self.iface.cadDockWidget(), _CAPTURE_MODE[self._geom_type]
        )
        self._tool.setLayer(self._layer)
        self._tool.digitizingCompleted.connect(self._on_completed)
        self._tool.deactivated.connect(self._on_deactivated)
        self._canvas.setMapTool(self._tool)

    def cancel(self):
        """Annuler explicitement (appel synchrone sûr, ex. fermeture du plugin)."""
        if self._tool is None or self._finished:
            return
        self._finished = True
        self._session += 1
        self._teardown(restore_tool=True)
        self.cancelled.emit()

    # ----------------------------------------------------------- callbacks
    def _on_completed(self, feature):
        # Émis DEPUIS le code natif → on lit seulement la géométrie, nettoyage différé.
        if self._finished:
            return
        self._finished = True
        geometry = feature.geometry() if feature is not None else None
        self._pending_wkt = self._to_wkt_4326(geometry)
        session = self._session
        QTimer.singleShot(0, lambda: self._finish(session, cancelled=False))

    def _on_deactivated(self):
        # L'utilisateur a changé d'outil sans terminer → annulation (différée).
        if self._finished:
            return
        self._finished = True
        session = self._session
        QTimer.singleShot(0, lambda: self._finish(session, cancelled=True))

    def _finish(self, session, cancelled):
        if session != self._session:
            return  # une nouvelle session a démarré entre-temps → ignorer
        wkt = None if cancelled else self._pending_wkt
        geom_type = self._geom_type
        # Ne pas restaurer l'outil si l'utilisateur en a déjà choisi un autre.
        self._teardown(restore_tool=not cancelled)
        if wkt:
            self.captured.emit(wkt, geom_type)
        else:
            self.cancelled.emit()

    # ------------------------------------------------------------- interne
    def _teardown(self, restore_tool):
        """Déconnecter, (option) restaurer l'outil, retirer la couche jetable."""
        tool = self._tool
        self._disconnect(tool)
        if restore_tool and self._prev_tool is not None:
            try:
                self._canvas.setMapTool(self._prev_tool)
            except RuntimeError:
                # L'outil précédent a été supprimé : au moins libérer le nôtre.
                try:
                    self._canvas.unsetMapTool(tool)
                except (RuntimeError, TypeError):
                    pass
        if self._layer is not None:
            try:
                QgsProject.instance().removeMapLayer(self._layer.id())
            except (RuntimeError, AttributeError):
                pass
        if tool is not None:
            tool.deleteLater()
        self._tool = None
        self._layer = None
        self._prev_tool = None
        self._pending_wkt = None

    def _disconnect(self, tool):
        if tool is None:
            return
        for signal, slot in (
            (tool.digitizingCompleted, self._on_completed),
            (tool.deactivated, self._on_deactivated),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def _to_wkt_4326(self, geometry):
        if geometry is None or geometry.isNull() or geometry.isEmpty():
            return None
        source_crs = self._canvas.mapSettings().destinationCrs()
        try:
            return geometry_to_wkt_4326(geometry, source_crs)
        except Exception:  # noqa: BLE001 - une géométrie invalide ne doit pas planter
            return None

    @staticmethod
    def _make_layer(geom_type, crs):
        wkb = _WKB_TYPE.get(geom_type, "Polygon")
        authid = crs.authid() if crs is not None and crs.authid() else "EPSG:4326"
        return QgsVectorLayer("%s?crs=%s" % (wkb, authid), "occhab_capture", "memory")


class GeometryEditController(QObject):
    """Édite la géométrie EXISTANTE d'une station avec l'outil de sommets QGIS.

    On charge la géométrie enregistrée (EPSG:4326) dans une couche mémoire
    temporaire éditable (dans le CRS du projet), on active `QgsVertexTool`, et on
    valide/annule via des boutons de la barre de messages (appels synchrones, donc
    pas de piège de ré-entrance). La géométrie éditée est renvoyée en EPSG:4326.
    """

    edited = pyqtSignal(str, str)  # wkt (EPSG:4326), geom_type
    cancelled = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._canvas = iface.mapCanvas()
        self._layer = None
        self._prev_tool = None
        self._prev_active = None
        self._msg_item = None
        self._geom_type = None
        self._finished = False

    # --------------------------------------------------------------- API
    def start(self, wkt_4326, geom_type):
        if self._layer is not None and not self._finished:
            self._teardown()  # session résiduelle
        self._finished = False
        self._geom_type = geom_type if geom_type in _WKB_TYPE else "polygon"

        geom = self._to_project_geometry(wkt_4326)
        if geom is None:
            self.cancelled.emit()
            return

        project_crs = self._canvas.mapSettings().destinationCrs()
        self._layer = self._make_edit_layer(self._geom_type, project_crs)
        feature = QgsFeature(self._layer.fields())
        feature.setGeometry(geom)
        self._layer.dataProvider().addFeatures([feature])
        self._layer.updateExtents()
        QgsProject.instance().addMapLayer(self._layer, True)  # visible

        self._layer.startEditing()
        self._prev_active = self.iface.activeLayer()
        self.iface.setActiveLayer(self._layer)
        self._prev_tool = self._canvas.mapTool()
        self._activate_vertex_tool()

        self._canvas.setExtent(self._layer.extent())
        self._canvas.zoomByFactor(1.2)
        self._canvas.refresh()
        self._show_prompt()

    def cancel(self):
        if self._layer is None or self._finished:
            return
        self._finished = True
        self._teardown()
        self.cancelled.emit()

    # ----------------------------------------------------------- callbacks
    def _confirm(self):
        if self._finished:
            return
        self._finished = True
        wkt = self._read_wkt_4326()
        geom_type = self._geom_type
        self._teardown()
        if wkt:
            self.edited.emit(wkt, geom_type)
        else:
            self.cancelled.emit()

    # ------------------------------------------------------------- interne
    def _activate_vertex_tool(self):
        # QgsVertexTool n'est pas exposé à Python : on déclenche l'action native
        # de l'outil de sommets (restreinte à la couche active si disponible).
        if hasattr(self.iface, "actionVertexToolActiveLayer"):
            self.iface.actionVertexToolActiveLayer().trigger()
        else:
            self.iface.actionVertexTool().trigger()

    def _show_prompt(self):
        bar = self.iface.messageBar()
        widget = bar.createMessage(
            "OccHab", "Modifiez les sommets de la géométrie, puis validez."
        )
        btn_ok = QPushButton("Valider la géométrie", widget)
        btn_ok.clicked.connect(self._confirm)
        btn_cancel = QPushButton("Annuler", widget)
        btn_cancel.clicked.connect(self.cancel)
        widget.layout().addWidget(btn_ok)
        widget.layout().addWidget(btn_cancel)
        self._msg_item = bar.pushWidget(widget, Qgis.MessageLevel.Info)

    def _teardown(self):
        if self._msg_item is not None:
            try:
                self.iface.messageBar().popWidget(self._msg_item)
            except (RuntimeError, TypeError):
                pass
            self._msg_item = None
        if self._prev_tool is not None:
            try:
                self._canvas.setMapTool(self._prev_tool)
            except RuntimeError:
                pass
        if self._prev_active is not None:
            try:
                self.iface.setActiveLayer(self._prev_active)
            except RuntimeError:
                pass
        if self._layer is not None:
            try:
                if self._layer.isEditable():
                    self._layer.rollBack()  # clôturer l'édition sans invite
            except (RuntimeError, AttributeError):
                pass
            try:
                QgsProject.instance().removeMapLayer(self._layer.id())
            except (RuntimeError, KeyError):
                pass
        self._layer = None
        self._prev_tool = None
        self._prev_active = None
        self._canvas.refresh()

    def _read_wkt_4326(self):
        if self._layer is None:
            return None
        feature = next(self._layer.getFeatures(), None)
        if feature is None or not feature.hasGeometry():
            return None
        project_crs = self._canvas.mapSettings().destinationCrs()
        try:
            return geometry_to_wkt_4326(feature.geometry(), project_crs)
        except Exception:  # noqa: BLE001
            return None

    def _to_project_geometry(self, wkt_4326):
        geom = QgsGeometry.fromWkt(wkt_4326 or "")
        if geom.isNull():
            return None
        project_crs = self._canvas.mapSettings().destinationCrs()
        if project_crs.isValid() and project_crs.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:4326"), project_crs,
                QgsProject.instance(),
            )
            geom.transform(transform)
        return geom

    @staticmethod
    def _make_edit_layer(geom_type, crs):
        wkb = _WKB_TYPE.get(geom_type, "Polygon")
        authid = crs.authid() if crs is not None and crs.authid() else "EPSG:4326"
        return QgsVectorLayer("%s?crs=%s" % (wkb, authid), "occhab_edit", "memory")
