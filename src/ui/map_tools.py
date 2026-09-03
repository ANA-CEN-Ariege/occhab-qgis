# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

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
    QgsSnappingConfig,
    QgsTolerance,
    QgsVectorLayer,
)
from qgis.gui import QgsMapCanvasTracer, QgsMapToolCapture, QgsMapToolDigitizeFeature

from ..processing.geometry import (
    CrsIndetermine,
    GeometrieIrreparable,
    assainir_wkt,
    geometry_to_wkt_4326,
)

_CAPTURE_MODE = {
    "point": QgsMapToolCapture.CaptureMode.CapturePoint,
    "line": QgsMapToolCapture.CaptureMode.CaptureLine,
    "polygon": QgsMapToolCapture.CaptureMode.CapturePolygon,
}
_WKB_TYPE = {"point": "Point", "line": "LineString", "polygon": "Polygon"}

#: Avertissement commun à la numérisation et à l'édition de sommets. La forme
#: enregistrée n'est plus celle qui a été dessinée — un contour qui se recoupe
#: est découpé en plusieurs parties, et sa surface change : il faut le dire.
_MESSAGE_CORRIGEE = (
    "Le tracé se recoupait lui-même : la géométrie a été corrigée automatiquement "
    "(elle peut être découpée en plusieurs parties). Vérifiez la forme sur la carte."
)


#: Tolérance d'accrochage, en PIXELS : indépendante du zoom, donc identique à
#: toutes les échelles d'affichage. C'est le défaut de QGIS, et le seul réglage
#: utilisable sur le terrain, où l'on numérise aussi bien au 1:500 qu'au 1:5000.
TOLERANCE_ACCROCHAGE_PX = 12


class AideAuTrace:
    """Accrocher aux stations voisines et suivre leur contour, le temps d'une saisie.

    Les stations d'habitat forment des mosaïques : deux polygones voisins doivent
    partager EXACTEMENT leur limite. Sans accrochage sur segment, l'utilisateur
    repose ses sommets « à peu près » sur la limite du voisin et laisse des fentes
    d'un mètre, invisibles à l'écran.

    Les réglages sont posés sur le PROJET (QGIS n'en a pas d'autre) puis rendus à
    l'identique en fin de session : le reste du travail de l'utilisateur dans QGIS
    ne doit pas se retrouver avec un accrochage qu'il n'a pas demandé.

    Deux précautions :

    1. Mode « configuration avancée » avec les seules couches de stations, la liste
       des réglages par couche étant vidée d'abord. Sinon l'accrochage attraperait
       aussi le cadastre ou un fond de plan chargé à côté, et le tracé se collerait
       à la mauvaise limite.
    2. Changer la configuration d'accrochage marque le projet comme MODIFIÉ, et
       QGIS proposerait de l'enregistrer à la fermeture pour un réglage qu'on a
       déjà rendu. On restaure donc aussi ce drapeau — sans écraser un état
       « modifié » légitime, mesuré juste avant.
    """

    def __init__(self, canvas, logger=None):
        self._canvas = canvas
        self._logger = logger
        self._config_precedente = None
        self._tracage_precedent = None

    def appliquer(self, couches):
        """Poser l'accrochage sur `couches` et activer le suivi de contour."""
        couches = [c for c in (couches or []) if c is not None]
        if not couches or self._config_precedente is not None:
            return  # rien où s'accrocher, ou réglages déjà posés
        projet = QgsProject.instance()
        modifie = projet.isDirty()
        try:
            self._config_precedente = QgsSnappingConfig(projet.snappingConfig())
            projet.setSnappingConfig(self._config_jointive(couches))
            self._activer_tracage()
        except Exception as exc:  # noqa: BLE001 - une aide ne doit pas bloquer la saisie
            self._avertir("Accrochage non configuré : %s", exc)
        finally:
            projet.setDirty(modifie)

    def restaurer(self):
        """Rendre les réglages de numérisation tels qu'ils étaient."""
        if self._config_precedente is None:
            return
        projet = QgsProject.instance()
        modifie = projet.isDirty()
        try:
            projet.setSnappingConfig(self._config_precedente)
            self._restaurer_tracage()
        except Exception as exc:  # noqa: BLE001
            self._avertir("Accrochage non restauré : %s", exc)
        finally:
            projet.setDirty(modifie)
            self._config_precedente = None
            self._tracage_precedent = None

    # ------------------------------------------------------------- interne
    def _config_jointive(self, couches):
        config = QgsSnappingConfig(QgsProject.instance().snappingConfig())
        # Les réglages par couche se lisent AVANT le vidage : ils portent les
        # valeurs par défaut de QGIS (échelles), qu'on ne fait que compléter.
        modeles = {c.id(): config.individualLayerSettings(c) for c in couches}
        config.setEnabled(True)
        config.setMode(QgsSnappingConfig.AdvancedConfiguration)
        config.clearIndividualLayerSettings()
        for couche in couches:
            config.setIndividualLayerSettings(
                couche, self._reglages_couche(modeles.get(couche.id()))
            )
        return config

    @staticmethod
    def _reglages_couche(modele):
        # Sommet ET segment : sans le segment, on ne peut poser un sommet au
        # milieu de la limite d'une station voisine sans créer de fente.
        types = QgsSnappingConfig.VertexFlag | QgsSnappingConfig.SegmentFlag
        if modele is not None and modele.valid():
            # Un réglage existant est déjà valide : le compléter évite le
            # constructeur paramétré, déprécié à partir de QGIS 3.40.
            reglages = modele
        else:
            # Le constructeur SANS argument rend un réglage `valid() == False`,
            # que l'accrochage ignore : il faut celui-ci, disponible dès la 3.28.
            reglages = QgsSnappingConfig.IndividualLayerSettings(
                True, types, TOLERANCE_ACCROCHAGE_PX, QgsTolerance.Pixels
            )
        reglages.setEnabled(True)
        reglages.setTypeFlag(types)
        reglages.setTolerance(TOLERANCE_ACCROCHAGE_PX)
        reglages.setUnits(QgsTolerance.Pixels)
        return reglages

    def _action_tracage(self):
        tracer = QgsMapCanvasTracer.tracerForCanvas(self._canvas)
        return tracer.actionEnableTracing() if tracer is not None else None

    def _activer_tracage(self):
        # Suivi de contour (touche T) : entre deux points posés sur des limites
        # existantes, le tracé les LONGE au lieu de couper tout droit. C'est ce
        # qui permet d'épouser une station voisine sans la redessiner sommet
        # par sommet. Ailleurs, le tracé reste rectiligne : rien n'est perdu.
        action = self._action_tracage()
        if action is not None:
            self._tracage_precedent = action.isChecked()
            action.setChecked(True)

    def _restaurer_tracage(self):
        action = self._action_tracage()
        if action is not None and self._tracage_precedent is not None:
            action.setChecked(self._tracage_precedent)

    def _avertir(self, message, exc):
        if self._logger is not None:
            self._logger.warning(message, exc)


class GeometryCaptureController(QObject):
    """Pilote une session de numérisation et émet la géométrie en EPSG:4326."""

    captured = pyqtSignal(str, str)  # wkt (EPSG:4326), geom_type
    cancelled = pyqtSignal()

    def __init__(self, iface, parent=None, logger=None):
        super().__init__(parent)
        self.iface = iface
        self._canvas = iface.mapCanvas()
        self._aide = AideAuTrace(self._canvas, logger)
        self._tool = None
        self._layer = None
        self._prev_tool = None
        self._geom_type = None
        self._pending_wkt = None
        self._pending_notice = None  # message à pousser une fois le nettoyage fait
        self._finished = False
        self._session = 0

    # --------------------------------------------------------------- API
    def start(self, geom_type, couches_reference=None):
        """Démarrer une numérisation (nettoie proprement une session résiduelle).

        `couches_reference` : couches sur lesquelles s'accrocher pendant le tracé
        (les stations déjà saisies), pour une saisie jointive. Les réglages de
        numérisation du projet sont rendus à l'identique en fin de session.
        """
        self._session += 1  # invalide les callbacks différés en attente
        # Conserver l'outil d'origine réel si une session traîne encore.
        original_prev = self._prev_tool if self._tool is not None else None
        self._teardown(restore_tool=False)

        self._finished = False
        self._geom_type = geom_type if geom_type in _CAPTURE_MODE else "polygon"
        self._pending_wkt = None

        self._aide.appliquer(couches_reference)
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
        notice = None if cancelled else self._pending_notice
        geom_type = self._geom_type
        # Ne pas restaurer l'outil si l'utilisateur en a déjà choisi un autre.
        self._teardown(restore_tool=not cancelled)
        if notice:
            # Après `_teardown` : pousser un message depuis le code natif de
            # l'outil ferait vaciller le cycle de vie décrit en tête de module.
            self.iface.messageBar().pushWarning("OccHab", notice)
        if wkt:
            self.captured.emit(wkt, geom_type)
        else:
            self.cancelled.emit()

    # ------------------------------------------------------------- interne
    def _teardown(self, restore_tool):
        """Déconnecter, (option) restaurer l'outil, retirer la couche jetable."""
        self._aide.restaurer()
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
        self._pending_notice = None

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
        """WKT EPSG:4326 assaini, ou None (motif retenu dans `_pending_notice`).

        Appelée depuis le code natif de l'outil : elle ne pousse aucun message,
        elle le met de côté pour `_finish`, qui s'exécute après le nettoyage.
        """
        if geometry is None or geometry.isNull() or geometry.isEmpty():
            return None
        source_crs = self._canvas.mapSettings().destinationCrs()
        try:
            wkt, corrigee = assainir_wkt(geometry_to_wkt_4326(geometry, source_crs))
            if corrigee:
                self._pending_notice = _MESSAGE_CORRIGEE
            return wkt
        except (CrsIndetermine, GeometrieIrreparable, ValueError) as exc:
            # Sans ce motif, un refus ressortait en « Numérisation annulée. » :
            # message faux, et l'utilisateur recommençait le même tracé.
            self._pending_notice = str(exc)
            return None
        except Exception:  # noqa: BLE001 - rien ne doit planter le code natif
            self._pending_notice = "Géométrie inexploitable."
            return None

    @staticmethod
    def _make_layer(geom_type, crs):
        wkb = _WKB_TYPE.get(geom_type, "Polygon")
        authid = crs.authid() if crs is not None and crs.authid() else "EPSG:4326"
        layer = QgsVectorLayer("%s?crs=%s" % (wkb, authid), "occhab_capture", "memory")
        # Couche de travail éphémère : exclue de l'avertissement « couches
        # temporaires » de QGIS à la fermeture (cf. station_layers).
        layer.setCustomProperty("skipMemoryLayersCheck", 1)
        return layer


class GeometryEditController(QObject):
    """Édite la géométrie EXISTANTE d'une station avec l'outil de sommets QGIS.

    On charge la géométrie enregistrée (EPSG:4326) dans une couche mémoire
    temporaire éditable (dans le CRS du projet), on active `QgsVertexTool`, et on
    valide/annule via des boutons de la barre de messages (appels synchrones, donc
    pas de piège de ré-entrance). La géométrie éditée est renvoyée en EPSG:4326.
    """

    edited = pyqtSignal(str, str)  # wkt (EPSG:4326), geom_type
    cancelled = pyqtSignal()

    def __init__(self, iface, parent=None, logger=None):
        super().__init__(parent)
        self.iface = iface
        self._canvas = iface.mapCanvas()
        self._aide = AideAuTrace(self._canvas, logger)
        self._layer = None
        self._prev_tool = None
        self._prev_active = None
        self._msg_item = None
        self._geom_type = None
        self._finished = False

    # --------------------------------------------------------------- API
    def start(self, wkt_4326, geom_type, couches_reference=None):
        """Éditer les sommets d'une géométrie existante.

        `couches_reference` : couches sur lesquelles s'accrocher (les stations
        voisines), pour recoller une limite commune sans laisser de fente.
        """
        if self._layer is not None and not self._finished:
            self._teardown()  # session résiduelle
        self._finished = False
        self._geom_type = geom_type if geom_type in _WKB_TYPE else "polygon"

        geom = self._to_project_geometry(wkt_4326)
        if geom is None:
            self.cancelled.emit()
            return

        self._aide.appliquer(couches_reference)
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
        wkt, notice = self._read_wkt_4326()
        geom_type = self._geom_type
        self._teardown()
        if notice:
            # Après `_teardown`, qui retire la barre de validation : sans quoi le
            # message serait poussé puis aussitôt masqué.
            self.iface.messageBar().pushWarning("OccHab", notice)
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
        self._aide.restaurer()
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
        """(WKT EPSG:4326 assaini, message) — message non nul si l'utilisateur doit
        être averti (géométrie corrigée) ou informé d'un refus."""
        if self._layer is None:
            return None, None
        feature = next(self._layer.getFeatures(), None)
        if feature is None or not feature.hasGeometry():
            return None, None
        project_crs = self._canvas.mapSettings().destinationCrs()
        try:
            wkt, corrigee = assainir_wkt(
                geometry_to_wkt_4326(feature.geometry(), project_crs)
            )
            return wkt, (_MESSAGE_CORRIGEE if corrigee else None)
        except (CrsIndetermine, GeometrieIrreparable, ValueError) as exc:
            return None, str(exc)
        except Exception:  # noqa: BLE001
            return None, "Géométrie inexploitable."

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
        layer = QgsVectorLayer("%s?crs=%s" % (wkb, authid), "occhab_edit", "memory")
        # Couche de travail éphémère : exclue de l'avertissement « couches
        # temporaires » de QGIS à la fermeture (cf. station_layers).
        layer.setCustomProperty("skipMemoryLayersCheck", 1)
        return layer
