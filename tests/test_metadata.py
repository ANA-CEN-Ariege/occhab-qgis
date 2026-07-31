# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vérifie que `metadata.txt` est lisible comme QGIS le lit.

QGIS analyse ce fichier avec `configparser` **interpolation activée** : un `%`
littéral doit y être doublé (`%%`). L'erreur ne se manifeste pas à la lecture du
fichier mais à l'accès à la valeur — et côté QGIS elle se solde par un
« There were errors reading plugin package », l'extension étant alors
**impossible à installer**.

Un simple « 100 % par polygone » dans le changelog a suffi à rendre une release
inutilisable : d'où ce test.
"""
import configparser
import os

_RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_METADATA = os.path.join(_RACINE, "metadata.txt")

# Champs attendus par le dépôt d'extensions QGIS.
_OBLIGATOIRES = ("name", "qgisMinimumVersion", "description", "version", "author",
                 "email", "about", "repository")


def _config():
    parser = configparser.ConfigParser()  # interpolation par défaut, comme QGIS
    parser.read(_METADATA, encoding="utf-8")
    return parser


def test_toutes_les_valeurs_sont_interpolables():
    """Le vrai piège : l'erreur ne survient qu'à l'ACCÈS à la valeur."""
    parser = _config()
    for section in parser.sections():
        for cle in parser[section]:
            parser.get(section, cle)  # lève InterpolationSyntaxError si un % est nu


def test_champs_obligatoires_presents():
    parser = _config()
    for cle in _OBLIGATOIRES:
        assert parser.get("general", cle).strip(), cle


def test_version_au_format_attendu():
    version = _config().get("general", "version").strip()
    morceaux = version.split(".")
    assert len(morceaux) == 3, version
    assert all(m.isdigit() for m in morceaux), version


def test_changelog_commence_par_la_version_courante():
    """Publier une version sans son entrée de changelog passe sinon inaperçu."""
    parser = _config()
    version = parser.get("general", "version").strip()
    changelog = parser.get("general", "changelog").strip()
    assert changelog.startswith(version), changelog[:60]
