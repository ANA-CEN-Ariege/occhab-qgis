"""Journalisation du plugin.

Écrit dans le panneau « Journal des messages » de QGIS (onglet OccHab) et,
si possible, dans un fichier occhab.log du répertoire de configuration.
"""
import logging

try:
    from qgis.core import QgsMessageLog, Qgis
except ImportError:  # pragma: no cover
    QgsMessageLog = None
    Qgis = None

TAG = "OccHab"


def _qgis_level(levelno):
    if Qgis is None:
        return None
    if levelno >= logging.ERROR:
        return Qgis.Critical
    if levelno >= logging.WARNING:
        return Qgis.Warning
    return Qgis.Info


class _QgisLogHandler(logging.Handler):
    """Redirige les logs Python vers le panneau de messages QGIS."""

    def emit(self, record):
        if QgsMessageLog is None:
            return
        try:
            QgsMessageLog.logMessage(self.format(record), TAG, _qgis_level(record.levelno))
        except Exception:  # pragma: no cover - ne jamais casser sur un log
            pass


def setup_logger(name="occhab", config=None):
    """Créer (une seule fois) le logger du plugin."""
    logger = logging.getLogger(name)
    if logger.handlers:  # déjà configuré
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    qgis_handler = _QgisLogHandler()
    qgis_handler.setFormatter(fmt)
    logger.addHandler(qgis_handler)

    if config is not None:
        try:
            from pathlib import Path

            log_path = Path(config.user_config_dir) / "occhab.log"
            file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except Exception:  # pragma: no cover
            pass

    return logger
