# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialogue de connexion à GeoNature.

L'authentification passe **exclusivement par le système d'authentification de
QGIS** : on sélectionne une configuration (méthode « Basic » : identifiant +
mot de passe GeoNature stockés chiffrés par QGIS). Le plugin lit ces identifiants
pour faire le POST /auth/login. On ne mémorise que l'URL et l'authcfg — jamais le
mot de passe.

`id_application` (souvent auto) et la vérification SSL restent réglables via
config.json (`geonature.id_application`, `geonature.verify_ssl`) mais ne sont pas
exposés dans le formulaire.
"""
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
)
from qgis.gui import QgsAuthConfigSelect


class ConnectionDialog(QDialog):
    """Connexion à GeoNature via une configuration d'authentification QGIS."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connexion à GeoNature")
        self.config = config
        self.client = None
        self.user = None
        self._build()

    def _build(self):
        form = QFormLayout(self)

        self.edit_url = QLineEdit(self.config.get("geonature.api_url") or "")
        self.edit_url.setPlaceholderText("https://serveur/geonature/api")
        form.addRow("URL de l'API", self.edit_url)

        self.auth_select = QgsAuthConfigSelect(self)
        stored_authcfg = self.config.get("geonature.authcfg")
        if stored_authcfg:
            self.auth_select.setConfigId(stored_authcfg)
        form.addRow("Authentification QGIS", self.auth_select)

        hint = QLabel(
            "Créez ou choisissez une configuration d'authentification QGIS "
            "(méthode « Basic » : identifiant + mot de passe GeoNature)."
        )
        hint.setWordWrap(True)
        hint.setEnabled(False)
        form.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Se connecter")
        buttons.accepted.connect(self._on_connect)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_connect(self):
        api_url = self.edit_url.text().strip()
        if not api_url:
            QMessageBox.warning(self, "Connexion", "Renseignez l'URL de l'API.")
            return

        authcfg = self.auth_select.configId()
        if not authcfg:
            QMessageBox.warning(
                self, "Connexion",
                "Choisissez une configuration d'authentification QGIS.",
            )
            return
        login, password = self._credentials_from_authcfg(authcfg)
        if not login:
            QMessageBox.warning(
                self,
                "Connexion",
                "Impossible de lire les identifiants de la configuration "
                "d'authentification QGIS (méthode « Basic » attendue).",
            )
            return

        try:
            from ..api.geonature_client import GeoNatureAPIClient, GeoNatureAPIError
        except ImportError:
            QMessageBox.critical(
                self,
                "Dépendance manquante",
                "Le module 'requests' est introuvable dans le Python de QGIS.\n"
                "Installez-le pour activer la connexion à GeoNature.",
            )
            return

        verify_ssl = bool(self.config.get("geonature.verify_ssl", True))
        id_application = int(self.config.get("geonature.id_application", 0) or 0)
        client = GeoNatureAPIClient(api_url, verify_ssl=verify_ssl)
        try:
            client.login(login, password, id_application=id_application)
        except GeoNatureAPIError as exc:
            QMessageBox.critical(self, "Échec de connexion", str(exc))
            return

        # Succès : mémoriser le client et persister URL + authcfg (jamais le mot de passe).
        self.client = client
        self.user = client.user
        self.config.set("geonature.api_url", api_url)
        self.config.set("geonature.authcfg", authcfg)
        self.accept()

    def _credentials_from_authcfg(self, authcfg):
        """Lire identifiant/mot de passe depuis le gestionnaire d'auth de QGIS."""
        from qgis.core import QgsApplication, QgsAuthMethodConfig

        manager = QgsApplication.authManager()
        cfg = QgsAuthMethodConfig()
        try:
            manager.loadAuthenticationConfig(authcfg, cfg, True)
        except Exception:  # noqa: BLE001
            return None, None
        if not cfg.id():
            return None, None
        return cfg.config("username"), cfg.config("password")

    def user_label(self):
        """Libellé lisible de l'utilisateur connecté (nom, login, id_role)."""
        user = self.user or {}
        if not isinstance(user, dict):
            return "connecté"
        full = (
            user.get("nom_complet")
            or ("%s %s" % (user.get("prenom_role") or "", user.get("nom_role") or "")).strip()
            or user.get("identifiant")
            or "connecté"
        )
        details = []
        if user.get("identifiant"):
            details.append(str(user["identifiant"]))
        if user.get("id_role"):
            details.append("id_role=%s" % user["id_role"])
        return "%s (%s)" % (full, ", ".join(details)) if details else full
