# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Configuration pytest : rendre importables les modules purs (sans QGIS).

`payload` et `sqlite_local` n'importent que la bibliothèque standard, donc on peut
les tester directement en ajoutant leurs dossiers au chemin d'import.

`scripts/` suit la même règle : ses outils hors QGIS (import du catalogue de
typologie) portent des règles métier qui méritent d'être testées.

Le DOSSIER PARENT est ajouté en plus, pour que `occhab.src.ui…` s'importe comme
dans QGIS : les modules d'interface utilisent des imports relatifs
(`from ..processing import …`) et ne s'atteignent donc pas par leur seul dossier.
C'est ce qui permet à `test_interface_habitat` de construire les vrais widgets
hors écran — une suite qui ne teste que les modules purs laisse passer une
extension qui ne se charge plus.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("src/api", "src/database", "src/processing", "scripts"):
    _path = os.path.join(_ROOT, _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)

_PARENT = os.path.dirname(_ROOT)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)
