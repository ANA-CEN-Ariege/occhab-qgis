# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Classe principale du plugin OccHab."""
from pathlib import Path

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication, QgsProject

from .src.utils.config import Config
from .src.utils.logger import setup_logger

try:  # QGIS ≥ 3.16
    from qgis.gui import QgsApplicationExitBlockerInterface
except ImportError:  # pragma: no cover
    QgsApplicationExitBlockerInterface = None

if QgsApplicationExitBlockerInterface is not None:
    class _GardeFermeture(QgsApplicationExitBlockerInterface):
        """Consultée par QGIS AVANT de se fermer, quand il est encore temps de
        demander quelque chose (cf. `OccHabPlugin.peut_fermer`)."""

        def __init__(self, plugin):
            super().__init__()
            self._plugin = plugin

        def allowExit(self):
            return self._plugin.peut_fermer("QGIS va se fermer.")
else:  # pragma: no cover
    _GardeFermeture = None


class OccHabPlugin:
    """Plugin OccHab pour QGIS : point d'entrée, menu/toolbar et dock."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).parent
        self.config = Config(self.plugin_dir)
        self.logger = setup_logger("occhab", self.config)
        self.dock_widget = None
        self.action = None
        self._garde_fermeture = None
        self.logger.info("Plugin OccHab initialisé")

    # ------------------------------------------------------------------ GUI
    def _icon(self):
        for name in ("occhab.svg", "occhab.png"):
            path = self.plugin_dir / "resources" / "icons" / name
            if path.exists():
                return QIcon(str(path))
        # Repli sur une icône du thème QGIS si l'asset est absent.
        return QgsApplication.getThemeIcon("/mActionAddPolygon.svg")

    def initGui(self):
        """Créer l'action de menu/toolbar. Appelé par QGIS au démarrage."""
        self.action = QAction(
            self._icon(), "OccHab GeoNature", self.iface.mainWindow()
        )
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_dock)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("OccHab", self.action)
        # Ici et non dans le panneau, créé seulement au premier clic sur le
        # bouton : un projet ouvert puis fermé sans l'avoir affiché doit être
        # réparé lui aussi, ou QGIS plante à sa fermeture.
        QgsProject.instance().readProject.connect(self._reparer_mises_en_page)
        self._reparer_mises_en_page()  # projet déjà ouvert (extension activée en cours de route)
        if _GardeFermeture is not None:
            # Fermer QGIS avec le tableau modifié et non enregistré perdait
            # tout : le déchargement ne peut plus rien demander. QGIS consulte
            # cette garde avant, et renonce à se fermer si on annule.
            self._garde_fermeture = _GardeFermeture(self)
            self.iface.registerApplicationExitBlocker(self._garde_fermeture)
        self.logger.info("Interface initialisée")

    def peut_fermer(self, raison, annulable=True):
        """Le tableau a-t-il des modifications à sauver ? Demande si oui."""
        dock = self.dock_widget
        tableau = getattr(dock, "_table_dialog", None) if dock is not None else None
        if tableau is None:
            return True
        try:
            return tableau.proposer_enregistrement(raison, annulable=annulable)
        except Exception as exc:  # noqa: BLE001 - ne jamais empêcher QGIS de se fermer
            self.logger.warning("Garde de fermeture ignorée : %s", exc)
            return True

    def unload(self):
        """Nettoyer à la désactivation du plugin. Appelé par QGIS."""
        try:
            QgsProject.instance().readProject.disconnect(self._reparer_mises_en_page)
        except (TypeError, RuntimeError):
            pass
        if self._garde_fermeture is not None:
            try:
                self.iface.unregisterApplicationExitBlocker(self._garde_fermeture)
            except (AttributeError, RuntimeError, TypeError):
                pass
            self._garde_fermeture = None
        # Extension rechargée, mise à jour ou désactivée : à la fermeture de
        # QGIS la garde a déjà posé la question, il ne reste donc rien ici.
        self.peut_fermer("L'extension OccHab va être déchargée (mise à jour, "
                         "désactivation ou rechargement).", annulable=False)
        if self.dock_widget is not None:
            self.dock_widget.shutdown()
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None
        if self.action is not None:
            self.iface.removePluginMenu("OccHab", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        self.logger.info("Plugin OccHab déchargé")

    def _reparer_mises_en_page(self, *_args):
        """Remplacer les cadres recopiés par les versions précédentes (cf.
        `print_layout.reparer_cadres_orphelins`) : ils font planter QGIS à la
        fermeture du projet."""
        if not QgsProject.instance().layoutManager().printLayouts():
            return  # cas courant : rien à examiner, rien à importer
        try:
            from .src.ui.print_layout import reparer_cadres_orphelins

            nombre = reparer_cadres_orphelins()
        except Exception as exc:  # noqa: BLE001 - ne jamais bloquer l'ouverture
            self.logger.warning("Mises en page non vérifiées : %s", exc)
            return
        if not nombre:
            return
        self.logger.info("%d cadre(s) de mise en page orphelin(s) réparé(s)", nombre)
        # QGIS remet le drapeau « modifié » à faux juste APRÈS `readProject` :
        # le reposer au tour suivant, pour qu'il propose d'enregistrer la
        # réparation à la fermeture.
        QTimer.singleShot(0, lambda: QgsProject.instance().setDirty(True))
        self.iface.messageBar().pushWarning(
            "OccHab",
            "%d cadre(s) recopié(s) sur une page de légende par une version "
            "précédente du plugin ont été réparés (ils faisaient planter QGIS à "
            "la fermeture du projet). Enregistrez le projet pour conserver la "
            "correction." % nombre,
        )

    # -------------------------------------------------------------- actions
    def toggle_dock(self, checked=None):
        """Afficher / masquer le dock de saisie."""
        if self.dock_widget is None:
            # Import différé : évite de charger l'UI (et ses deps) au démarrage.
            from .src.ui.dock_widget import OccHabDockWidget

            self.dock_widget = OccHabDockWidget(self.iface, self.config, self.logger)
            self.dock_widget.visibilityChanged.connect(self._on_visibility)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_widget)
            # Largeur initiale raisonnable (l'utilisateur peut ensuite redimensionner).
            try:
                self.iface.mainWindow().resizeDocks(
                    [self.dock_widget], [450], Qt.Orientation.Horizontal
                )
            except Exception as exc:  # noqa: BLE001 - resizeDocks absent sur très vieux Qt
                self.logger.debug("Largeur initiale du dock non appliquée : %s", exc)
        else:
            self.dock_widget.setVisible(not self.dock_widget.isVisible())

    def _on_visibility(self, visible):
        if self.action is not None:
            self.action.setChecked(visible)
