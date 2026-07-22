# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Configuration pytest : rendre importables les modules purs (sans QGIS).

`payload` et `sqlite_local` n'importent que la bibliothèque standard, donc on peut
les tester directement en ajoutant leurs dossiers au chemin d'import.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("src/api", "src/database", "src/processing"):
    _path = os.path.join(_ROOT, _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
