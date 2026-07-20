# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Classe principale du plugin OccHab."""
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

from .src.utils.config import Config
from .src.utils.logger import setup_logger


class OccHabPlugin:
    """Plugin OccHab pour QGIS : point d'entrée, menu/toolbar et dock."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).parent
        self.config = Config(self.plugin_dir)
        self.logger = setup_logger("occhab", self.config)
        self.dock_widget = None
        self.action = None
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
        self.logger.info("Interface initialisée")

    def unload(self):
        """Nettoyer à la désactivation du plugin. Appelé par QGIS."""
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
            except Exception:  # noqa: BLE001 - resizeDocks absent sur très vieux Qt
                pass
        else:
            self.dock_widget.setVisible(not self.dock_widget.isVisible())

    def _on_visibility(self, visible):
        if self.action is not None:
            self.action.setChecked(visible)
