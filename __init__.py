# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
OccHab QGIS Extension - Saisie d'habitats pour GeoNature.

Point d'entrée requis par QGIS.
"""


def classFactory(iface):  # noqa: N802 (nom imposé par QGIS)
    """Charger la classe principale du plugin.

    Args:
        iface: interface QGIS fournie par l'application.

    Returns:
        Instance de OccHabPlugin.
    """
    from .plugin import OccHabPlugin

    return OccHabPlugin(iface)
