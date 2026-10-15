# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gestion de la configuration du plugin OccHab.

Configuration stockée en JSON dans le répertoire de profil QGIS de l'utilisateur.
Les valeurs par défaut sont fusionnées récursivement avec le fichier existant.
"""
import json
import os
import shutil
from pathlib import Path

try:  # disponible dans QGIS, absent lors de tests unitaires purs
    from qgis.core import QgsApplication
except ImportError:  # pragma: no cover
    QgsApplication = None


DEFAULT_CONFIG = {
    "geonature": {
        # Vide, et non l'adresse d'un serveur réel : pré-remplie avec celle
        # de geonature.fr, un premier « Se connecter » y envoyait l'identifiant
        # et le mot de passe de l'utilisateur. Vide, le dialogue montre un
        # exemple grisé et exige une adresse.
        "api_url": "",
        "verify_ssl": True,
    },
    "local_db": {"path": None},  # renseigné à l'initialisation
    "id_dataset": None,  # JDD par défaut pour la saisie
    # Reprise de la saisie précédente : observateurs, typologie HABREF et
    # dernier habitat saisi (sans son nom cité, son code, son recouvrement ni
    # son abondance — cf. processing/duplicate.py). Les dates ne sont PAS
    # persistées ici : elles ne valent que pour la session QGIS en cours (au
    # redémarrage on repart d'aujourd'hui plutôt que d'une date périmée). La
    # typologie et la façon de déterminer, elles, ne se périment pas : une
    # campagne se mène dans une même typologie (CORINE, EUNIS…).
    "last_entry": {"observers": [], "cd_typo": None, "habitat": None},
    # Numérisation jointive : accrochage sommet + segment sur les stations
    # voisines pendant le tracé, et retrait du recouvrement à la validation.
    # Les stations d'habitat forment des mosaïques ; deux polygones voisins
    # doivent partager exactement leur limite. Passer à false rend la saisie
    # libre et ne touche plus aux réglages de numérisation de QGIS.
    "numerisation": {"jointif": True},
}
# Retirées en 0.12.0 parce qu'aucune n'était lue nulle part, et qu'écrites dans
# le config.json de chaque utilisateur elles promettaient ce qui n'existe pas :
# `database` (host/port/database/user) une connexion PostgreSQL directe — le
# plugin passe exclusivement par l'API REST ; `auto_sync_interval` une synchro
# automatique — elle se déclenche au bouton ; `projection` un SCR de travail —
# tout le circuit est en EPSG:4326, la reprojection se fait au cas par cas
# depuis le SCR de la couche source. Une clé résiduelle dans un config.json
# existant est simplement ignorée : rien à migrer.


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
        #: Message à montrer à l'utilisateur (fichier illisible), ou None.
        self.avertissement = None
        self._load()

    def _lire(self):
        """(contenu, None) ; ({}, None) si le fichier n'existe pas ; (None, erreur).

        `utf-8-sig` : le Bloc-notes de Windows enregistre en « UTF-8 avec BOM »,
        que `json` refuse en UTF-8 strict — toute la configuration revenait
        alors aux défauts, sans un mot.
        """
        if not self.config_file.exists():
            return {}, None
        try:
            with open(self.config_file, encoding="utf-8-sig") as fh:
                contenu = json.load(fh)
        except (OSError, ValueError) as exc:
            return None, exc
        if not isinstance(contenu, dict):
            return None, ValueError("le fichier ne contient pas un objet JSON")
        return contenu, None

    def _depuis(self, contenu):
        data = json.loads(json.dumps(DEFAULT_CONFIG))  # copie profonde
        _merge(data, contenu or {})
        if not data.get("local_db", {}).get("path"):
            data["local_db"]["path"] = str(self.user_config_dir / "occhab_local.db")
        return data

    def _mettre_de_cote(self, erreur):
        """Garder une copie d'un config.json illisible, et le dire.

        Les défauts s'appliquaient en silence (URL, authentification, chemin de
        la base : la liste des stations paraissait vide), puis le premier
        réglage écrasait le fichier d'origine. Il est désormais copié à côté
        avant d'être remplacé, et l'utilisateur prévenu.
        """
        copie = self.config_file.with_name(self.config_file.name + ".illisible")
        try:
            shutil.copy2(self.config_file, copie)
        except OSError:
            copie = None
        self.avertissement = (
            "config.json est illisible (%s) : réglages par défaut appliqués.%s"
            % (erreur, " Le fichier d'origine est conservé sous %s." % copie.name
               if copie else "")
        )

    def _load(self):
        contenu, erreur = self._lire()
        if erreur is not None:
            self._mettre_de_cote(erreur)
        self.data = self._depuis(contenu)

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
        """Écrire une valeur par clé pointée et sauvegarder.

        Le fichier est RELU juste avant : le guide invite à le modifier à la
        main, forcément pendant que QGIS tourne, et un second QGIS peut l'avoir
        réécrit. Repartir de la copie lue au lancement effaçait ces
        modifications au premier réglage venu.
        """
        contenu, erreur = self._lire()
        if erreur is None:
            self.data = self._depuis(contenu)
        else:
            self._mettre_de_cote(erreur)  # ne pas écraser sans garder de copie
        keys = key.split(".")
        node = self.data
        for part in keys[:-1]:
            node = node.setdefault(part, {})
        node[keys[-1]] = value
        self.save()

    def save(self):
        """Persister la configuration en JSON, d'un bloc.

        Écrite dans un fichier voisin puis substituée à l'ancienne : réécrire
        `config.json` en place laissait, si QGIS tombait pendant l'écriture, un
        fichier tronqué — et toute la configuration revenait silencieusement
        aux valeurs par défaut au lancement suivant.
        """
        provisoire = Path(str(self.config_file) + ".tmp")
        with open(provisoire, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)
        os.replace(provisoire, self.config_file)
