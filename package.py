#!/usr/bin/env python3
"""Construit le ZIP d'installation du plugin QGIS OccHab.

Produit `dist/occhab-<version>.zip` avec un dossier racine `occhab/` (structure
attendue par le dépôt QGIS et l'installation « depuis un ZIP »). La version est
lue dans `metadata.txt`. Les fichiers compilés / runtime / dev sont exclus.

Usage :
    python package.py
"""
import fnmatch
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = "occhab"  # dossier racine dans le ZIP

# Dossiers exclus (à n'importe quel niveau).
EXCLUDE_DIRS = {
    "__pycache__", ".git", ".github", ".vscode", ".idea", ".pytest_cache",
    "htmlcov", ".venv", "venv", "env", "dist", "memory", "tests",
}
# Motifs de fichiers exclus.
EXCLUDE_GLOBS = [
    "*.pyc", "*.pyo", "*.db", "*.sqlite", "*.sqlite3", "*.log",
    "*.qgz", "*.qgs~", "*.swp", ".coverage", "*.egg-info",
]
# Fichiers dev exclus à la racine du plugin.
EXCLUDE_TOP_FILES = {"package.py"}


def _read_version():
    path = os.path.join(HERE, "metadata.txt")
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip().startswith("version="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("version introuvable dans metadata.txt")


def _excluded_file(name):
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDE_GLOBS)


def main():
    version = _read_version()
    out_dir = os.path.join(HERE, "dist")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "occhab-%s.zip" % version)

    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(HERE):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for filename in files:
                if _excluded_file(filename):
                    continue
                if root == HERE and filename in EXCLUDE_TOP_FILES:
                    continue
                full = os.path.join(root, filename)
                rel = os.path.relpath(full, HERE)
                arc = os.path.join(TOP, rel).replace("\\", "/")
                zf.write(full, arc)
                count += 1

    size = os.path.getsize(out)
    print("OccHab %s : %d fichiers -> %s (%d octets)" % (version, count, out, size))
    return out


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
