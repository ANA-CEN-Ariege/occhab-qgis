# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gestion de la configuration du plugin OccHab.

Configuration stockée en JSON dans le répertoire de profil QGIS de l'utilisateur.
Les valeurs par défaut sont fusionnées récursivement avec le fichier existant.
"""
import json
from pathlib import Path

try:  # disponible dans QGIS, absent lors de tests unitaires purs
    from qgis.core import QgsApplication
except ImportError:  # pragma: no cover
    QgsApplication = None


DEFAULT_CONFIG = {
    "geonature": {
        "api_url": "http://localhost:8000/api",
        "verify_ssl": True,
    },
    "database": {
        "host": "localhost",
        "port": 5432,
        "database": "geonature",
        "user": "geonature_user",
    },
    "local_db": {"path": None},  # renseigné à l'initialisation
    "id_dataset": None,  # JDD par défaut pour la saisie
    "projection": "EPSG:2154",
    "auto_sync_interval": 300,
}


def _user_config_dir():
    """Répertoire de configuration inscriptible pour le plugin."""
    if QgsApplication is not None:
        base = Path(QgsApplication.qgisSettingsDirPath())
    else:  # pragma: no cover
        base = Path.home() / ".qgis3"
    directory = base / "occhab"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _merge(base, override):
    """Fusion récursive (les dicts imbriqués ne sont pas écrasés en bloc)."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


class Config:
    """Configuration du plugin, persistée en JSON."""

    def __init__(self, plugin_dir=None):
        self.plugin_dir = Path(plugin_dir) if plugin_dir else None
        self.user_config_dir = _user_config_dir()
        self.config_file = self.user_config_dir / "config.json"
        self.data = {}
        self._load()

    def _load(self):
        data = json.loads(json.dumps(DEFAULT_CONFIG))  # copie profonde
        if self.config_file.exists():
            try:
                with open(self.config_file, encoding="utf-8") as fh:
                    _merge(data, json.load(fh))
            except (OSError, ValueError):
                pass  # fichier illisible/corrompu → on garde les défauts
        if not data.get("local_db", {}).get("path"):
            data["local_db"]["path"] = str(self.user_config_dir / "occhab_local.db")
        self.data = data

    def get(self, key, default=None):
        """Lire une valeur par clé pointée (ex. 'geonature.api_url').

        Renvoie aussi les valeurs 'falsy' légitimes (0, '', False).
        """
        value = self.data
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def set(self, key, value):
        """Écrire une valeur par clé pointée et sauvegarder."""
        keys = key.split(".")
        node = self.data
        for part in keys[:-1]:
            node = node.setdefault(part, {})
        node[keys[-1]] = value
        self.save()

    def save(self):
        """Persister la configuration en JSON."""
        with open(self.config_file, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)
