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
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import QPushButton
from qgis.core import (
    Qgis,
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

#: SCR des couches de travail (saisie, édition) : CELUI DES STATIONS, et non
#: celui du canevas. QGIS ne recopie à l'identique un sommet accroché que si la
#: couche accrochée et la couche de travail partagent leur SCR
#: (`QgsMapToolCapture::fetchLayerPoint`, `QgsVertexTool::matchToLayerPoint`).
#: Sinon le sommet faisait un aller-retour de reprojection : une limite pourtant
#: accrochée ne coïncidait plus exactement avec celle de la voisine, et la
#: découpe jointive se déclenchait presque à chaque tracé (« Le tracé débordait
#: sur une station voisine »), laissant parfois un micro-morceau. Le tracé est
#: aussi relu dans le SCR de SA couche, et non dans celui du canevas au moment
#: de valider : changer le SCR du projet en cours d'édition déplaçait la
#: station.
_CRS_TRAVAIL = "EPSG:4326"

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


def _meme_objet(a, b):
    """`a` et `b` désignent-ils le même objet C++ (enveloppes Python comprises) ?"""
    if a is None or b is None:
        return False
    try:
        return sip.unwrapinstance(a) == sip.unwrapinstance(b)
    except (RuntimeError, TypeError):
        return False


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

    Et une contrainte de QGIS : `QgsSnappingConfig` range ses réglages par couche
    sous l'ADRESSE MÉMOIRE de chaque couche. QGIS nettoie la configuration du
    projet quand une couche est retirée, mais pas une copie gardée de côté. Rendre
    telle quelle la copie prise en début de saisie réinstallait l'adresse d'une
    couche détruite entre-temps (couche serveur rechargée par une synchro, couche
    de travail d'une autre saisie…), et QGIS plantait au prochain accrochage ou à
    l'enregistrement du projet. Les réglages par couche sont donc retenus par
    IDENTIFIANT, et rendus aux seules couches encore présentes.
    """

    def __init__(self, canvas, logger=None):
        self._canvas = canvas
        self._logger = logger
        self._config_precedente = None
        self._reglages_precedents = {}  # id de couche -> réglage par couche
        self._tracage_precedent = None

    def appliquer(self, couches):
        """Poser l'accrochage sur `couches` et activer le suivi de contour."""
        couches = [c for c in (couches or []) if c is not None]
        if not couches or self._config_precedente is not None:
            return  # rien où s'accrocher, ou réglages déjà posés
        projet = QgsProject.instance()
        modifie = projet.isDirty()
        try:
            actuelle = projet.snappingConfig()
            self._config_precedente = QgsSnappingConfig(actuelle)
            self._reglages_precedents = self._reglages_par_id(actuelle)
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
            projet.setSnappingConfig(self._config_rendue())
            self._restaurer_tracage()
        except Exception as exc:  # noqa: BLE001
            self._avertir("Accrochage non restauré : %s", exc)
        finally:
            projet.setDirty(modifie)
            self._config_precedente = None
            self._reglages_precedents = {}
            self._tracage_precedent = None

    def oublier(self):
        """Abandonner les réglages retenus SANS les rendre au projet.

        Pour un projet qu'on ferme (nouveau projet, ouverture d'un autre, sortie
        de QGIS). QGIS remet alors l'accrochage à zéro AVANT de signaler le
        retrait des couches, et ne retire plus les couches détruites de cette
        configuration : y rendre les réglages réinstallerait l'adresse de
        couches sur le point de disparaître. Le suivi de contour, réglage de
        l'application et non du projet, est rendu.
        """
        if self._config_precedente is None:
            return
        try:
            self._restaurer_tracage()
        except Exception as exc:  # noqa: BLE001
            self._avertir("Suivi de contour non restauré : %s", exc)
        finally:
            self._config_precedente = None
            self._reglages_precedents = {}
            self._tracage_precedent = None

    # ------------------------------------------------------------- interne
    @staticmethod
    def _couches_vecteur():
        """Couches vecteur VIVANTES du projet."""
        return [
            couche for couche in QgsProject.instance().mapLayers().values()
            if isinstance(couche, QgsVectorLayer)
        ]

    @classmethod
    def _reglages_par_id(cls, config):
        """Réglages par couche de `config`, indexés par identifiant de couche.

        La configuration est interrogée couche VIVANTE par couche vivante, sans
        jamais parcourir ses propres clés : si l'une d'elles désignait déjà une
        couche détruite, la convertir en objet Python suffirait à faire planter
        QGIS.
        """
        reglages = {}
        for couche in cls._couches_vecteur():
            reglage = config.individualLayerSettings(couche)
            if reglage.valid():
                reglages[couche.id()] = reglage
        return reglages

    def _config_rendue(self):
        """La configuration d'avant la saisie, sur les seules couches présentes.

        Réglages généraux (activé, mode, tolérance, intersections…) : ceux
        d'avant, copiés tels quels. Réglages par couche : vidés — ce qui retire
        sans les toucher les adresses périmées — puis reposés couche vivante par
        couche vivante. Une couche arrivée pendant la saisie garde le réglage que
        QGIS lui a donné à son ajout.
        """
        actuelle = QgsProject.instance().snappingConfig()
        config = QgsSnappingConfig(self._config_precedente)
        config.clearIndividualLayerSettings()
        for couche in self._couches_vecteur():
            reglage = self._reglages_precedents.get(couche.id())
            if reglage is None:
                reglage = actuelle.individualLayerSettings(couche)
            if reglage.valid():
                config.setIndividualLayerSettings(couche, reglage)
        return config

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

    def en_cours(self):
        """Une numérisation est-elle en cours (outil actif, tracé non terminé) ?"""
        return self._tool is not None and not self._finished

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
        self._layer = self._make_layer(self._geom_type)
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
        self._tool.digitizingCanceled.connect(self._on_escape)
        # L'outil mémorise À SON ACTIVATION la couche courante, par une adresse
        # brute, pour la remettre à sa désactivation. Si l'utilisateur retirait
        # cette couche pendant le tracé, QGIS plantait en fin de tracé. On lui
        # fait mémoriser notre couche de saisie, qui vit jusqu'après la
        # désactivation ; la couche active est rendue par
        # `_liberer_couche_courante`.
        self._canvas.setCurrentLayer(self._layer)
        self._canvas.setMapTool(self._tool)

    def cancel(self):
        """Annuler explicitement (appel synchrone sûr, ex. fermeture du plugin)."""
        if self._tool is None or self._finished:
            return
        self._finished = True
        self._session += 1
        self._teardown(restore_tool=True)
        self.cancelled.emit()

    def abandonner(self):
        """Le projet se vide : annuler sans rendre l'accrochage (cf. `oublier`)."""
        if not self.en_cours():
            return
        self._aide.oublier()
        self.cancel()

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

    def _on_escape(self):
        # Échap : le message annonce « Échap pour annuler », mais l'outil
        # n'effaçait que le tracé. La session restait ouverte — accrochage
        # jointif en place, double-clic de la carte neutralisé, rechargement
        # serveur reporté —, et le tracé suivant ouvrait encore une fiche
        # OccHab. Émis DEPUIS le code natif : annulation différée, et l'outil
        # d'origine est rendu, puisque l'utilisateur n'en a pas choisi d'autre.
        if self._finished:
            return
        self._finished = True
        session = self._session
        QTimer.singleShot(
            0, lambda: self._finish(session, cancelled=True, restaurer_outil=True)
        )

    def _finish(self, session, cancelled, restaurer_outil=None):
        if session != self._session:
            return  # une nouvelle session a démarré entre-temps → ignorer
        wkt = None if cancelled else self._pending_wkt
        notice = None if cancelled else self._pending_notice
        geom_type = self._geom_type
        # Ne pas restaurer l'outil si l'utilisateur en a déjà choisi un autre.
        if restaurer_outil is None:
            restaurer_outil = not cancelled
        self._teardown(restore_tool=restaurer_outil)
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
        restaure = False
        if restore_tool and self._prev_tool is not None:
            try:
                self._canvas.setMapTool(self._prev_tool)
                restaure = True
            except RuntimeError:
                pass  # l'outil précédent a été supprimé
        if not restaure and tool is not None:
            # Notre outil peut être encore celui du canevas : session résiduelle
            # reprise par `start`, ou outil précédent disparu. Le détruire tel
            # quel sautait sa désactivation, qui rend au canevas sa couche
            # courante : la couche de saisie le restait, détruite juste après.
            # `unsetMapTool` le désactive proprement — et ne fait rien s'il a
            # déjà été remplacé.
            try:
                self._canvas.unsetMapTool(tool)
            except (RuntimeError, TypeError):
                pass
        if self._layer is not None:
            self._liberer_couche_courante()
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

    def _liberer_couche_courante(self):
        """Rendre au canevas la couche active, au lieu de la couche de saisie.

        À sa désactivation, l'outil remet la couche courante qu'il a mémorisée —
        notre couche de saisie (cf. `start`). Le canevas oublie sans bruit une
        couche détruite, mais l'accrochage, lui, garde son adresse : laissée
        courante, la couche de saisie faisait planter QGIS au premier
        accrochage suivant en mode « couche active ».
        """
        try:
            courante = self._canvas.currentLayer()
            if courante is not None and courante.id() == self._layer.id():
                self._canvas.setCurrentLayer(self.iface.activeLayer())
        except (RuntimeError, AttributeError):
            pass

    def _disconnect(self, tool):
        if tool is None:
            return
        for signal, slot in (
            (tool.digitizingCompleted, self._on_completed),
            (tool.deactivated, self._on_deactivated),
            (tool.digitizingCanceled, self._on_escape),
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
        try:
            # L'outil rend la géométrie dans le SCR de SA couche.
            wkt, corrigee = assainir_wkt(
                geometry_to_wkt_4326(geometry, self._layer.crs())
            )
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
    def _make_layer(geom_type):
        wkb = _WKB_TYPE.get(geom_type, "Polygon")
        layer = QgsVectorLayer(
            "%s?crs=%s" % (wkb, _CRS_TRAVAIL), "occhab_capture", "memory"
        )
        # Couche de travail éphémère : exclue de l'avertissement « couches
        # temporaires » de QGIS à la fermeture (cf. station_layers).
        layer.setCustomProperty("skipMemoryLayersCheck", 1)
        return layer


class GeometryEditController(QObject):
    """Édite la géométrie EXISTANTE d'une station avec l'outil de sommets QGIS.

    On charge la géométrie enregistrée (EPSG:4326) dans une couche mémoire
    temporaire éditable (même SCR, cf. `_CRS_TRAVAIL`), on active `QgsVertexTool`, et on
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
        self._prev_active_id = None
        self._outil_sommets = None
        self._msg_item = None
        self._geom_type = None
        self._finished = False

    def en_cours(self):
        """Une édition attend-elle « Valider » ou « Annuler » ?"""
        return self._layer is not None and not self._finished

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

        geom = QgsGeometry.fromWkt(wkt_4326 or "")
        if geom.isNull():
            self.cancelled.emit()
            return

        self._aide.appliquer(couches_reference)
        self._layer = self._make_edit_layer(self._geom_type)
        feature = QgsFeature(self._layer.fields())
        feature.setGeometry(geom)
        self._layer.dataProvider().addFeatures([feature])
        self._layer.updateExtents()
        # Lue AVANT l'ajout : QGIS rend active toute couche ajoutée à l'arbre, et
        # on mémorisait jusqu'ici la couche d'édition elle-même. Retenue par son
        # IDENTIFIANT : une couche chargée par QGIS (et non par Python) peut être
        # détruite pendant l'édition sans que Python le sache, et la lui
        # repasser ferait planter QGIS.
        active = self.iface.activeLayer()
        self._prev_active_id = active.id() if active is not None else None
        QgsProject.instance().addMapLayer(self._layer, True)  # visible

        self._layer.startEditing()
        self.iface.setActiveLayer(self._layer)
        self._prev_tool = self._canvas.mapTool()
        self._activate_vertex_tool()
        self._outil_sommets = self._canvas.mapTool()

        # L'emprise est dans le SCR de la couche : la ramener à celui du canevas.
        self._canvas.setExtent(
            self._canvas.mapSettings().layerExtentToOutputExtent(
                self._layer, self._layer.extent()
            )
        )
        self._canvas.zoomByFactor(1.2)
        self._canvas.refresh()
        self._show_prompt()

    def cancel(self):
        if self._layer is None or self._finished:
            return
        self._finished = True
        self._teardown()
        self.cancelled.emit()

    def abandonner(self):
        """Le projet se vide : annuler sans rendre l'accrochage (cf. `oublier`)."""
        if not self.en_cours():
            return
        self._aide.oublier()
        self.cancel()

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
        self._abandonner_geste()
        courant = self._canvas.mapTool()
        if _meme_objet(courant, self._prev_tool):
            # L'outil d'avant l'édition est aussi l'outil en place (l'utilisateur
            # avait l'outil de sommets en main) : `setMapTool` ne ferait que le
            # RÉACTIVER, sans jamais le désactiver. Il gardait alors ses sommets
            # sélectionnés, ses validations et son entité verrouillée sur la
            # couche d'édition détruite juste après — Suppr suffisait à faire
            # planter QGIS. On le désactive d'abord, puis on le remet.
            try:
                courant.clean()
                self._canvas.unsetMapTool(courant)
            except (RuntimeError, TypeError):
                pass
        if self._prev_tool is not None:
            try:
                # `True` : nettoyer l'outil quitté — par exemple l'outil de
                # sommets « toutes couches », pris pendant la session.
                self._canvas.setMapTool(self._prev_tool, True)
            except RuntimeError:
                pass
        precedente = (
            QgsProject.instance().mapLayer(self._prev_active_id)
            if self._prev_active_id else None
        )
        if precedente is not None:
            self.iface.setActiveLayer(precedente)
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
        self._prev_active_id = None
        self._canvas.refresh()

    def _abandonner_geste(self):
        """Interrompre un déplacement de sommet resté en suspens.

        L'outil de sommets de QGIS est UNIQUE, partagé par toutes les sessions,
        et il déplace un sommet en deux clics : un clic le prend, le suivant le
        pose. Valider entre les deux — ou après un double-clic sur une arête, qui
        arme l'ajout d'un sommet — lui laissait en mémoire un déplacement en
        cours sur la couche d'édition. Changer d'outil ne l'efface pas
        (`setMapTool` ne nettoie pas l'outil quitté), la couche était ensuite
        détruite, et le premier clic sur la carte de la session suivante faisait
        planter QGIS dans `QgsVertexTool::moveVertex`.

        `clean()` est la porte prévue par QGIS pour abandonner le geste en cours,
        que l'outil soit encore actif ou que l'utilisateur en ait changé
        entre-temps. L'outil est retenu tel qu'activé par `start` : c'est
        celui de QGIS, qui vit aussi longtemps que l'application.

        Limite : `clean()` n'efface PAS l'ajout de sommet armé par un double-clic
        dont le relâchement n'est jamais parvenu à l'outil — rien dans l'API ne
        le permet. Ce cas ne survient que si une fenêtre modale s'ouvre entre
        le double-clic et le relâchement ; c'est le filtre du panneau, qui
        n'ouvre plus la fiche station pendant un tracé, qui l'écarte.
        """
        outil, self._outil_sommets = self._outil_sommets, None
        if outil is None:
            return
        try:
            outil.clean()
        except (RuntimeError, AttributeError):
            pass

    def _read_wkt_4326(self):
        """(WKT EPSG:4326 assaini, message) — message non nul si l'utilisateur doit
        être averti (géométrie corrigée) ou informé d'un refus."""
        if self._layer is None:
            return None, None
        feature = next(self._layer.getFeatures(), None)
        if feature is None or not feature.hasGeometry():
            return None, None
        try:
            wkt, corrigee = assainir_wkt(
                geometry_to_wkt_4326(feature.geometry(), self._layer.crs())
            )
            return wkt, (_MESSAGE_CORRIGEE if corrigee else None)
        except (CrsIndetermine, GeometrieIrreparable, ValueError) as exc:
            return None, str(exc)
        except Exception:  # noqa: BLE001
            return None, "Géométrie inexploitable."

    @staticmethod
    def _make_edit_layer(geom_type):
        wkb = _WKB_TYPE.get(geom_type, "Polygon")
        layer = QgsVectorLayer(
            "%s?crs=%s" % (wkb, _CRS_TRAVAIL), "occhab_edit", "memory"
        )
        # Couche de travail éphémère : exclue de l'avertissement « couches
        # temporaires » de QGIS à la fermeture (cf. station_layers).
        layer.setCustomProperty("skipMemoryLayersCheck", 1)
        return layer
