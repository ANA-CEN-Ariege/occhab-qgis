# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Choix d'UNE station locale, pour en recopier les renseignements.

Pendant du sélecteur de stations serveur (`server_picker_dialog`), mais à choix
unique et sur la base locale : c'est ce que demande « reprendre une station
renseignée » depuis le formulaire ouvert. La liste dit ce qu'il faut pour
reconnaître un polygone déjà saisi — nom, date, habitats — sans ouvrir la table.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .dialog_size import ajuster_a_l_ecran


def resume_station(station):
    """Libellé d'une station dans la liste : nom — date — habitats."""
    nom = station.get("station_name") or "station sans nom"
    date = (station.get("date_min") or "")[:10]
    habitats = [
        h.get("nom_cite") for h in station.get("habitats") or [] if h.get("nom_cite")
    ]
    parts = [nom]
    if date:
        parts.append(date)
    if habitats:
        parts.append(", ".join(habitats))
    return " — ".join(parts)


class LocalStationPicker(QDialog):
    """Sélecteur d'une station locale ; `selected_id()` renvoie son id local."""

    def __init__(self, stations, parent=None):
        """`stations` : dicts de stations locales (avec leur clé `habitats`).

        L'appelant a déjà écarté la station en cours d'édition : se proposer de
        se recopier soi-même serait sans effet, mais déroutant dans la liste.
        """
        super().__init__(parent)
        self.setWindowTitle("Reprendre une station")
        self._taille_voulue = (520, 460)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choisissez la station dont vous voulez recopier les renseignements "
            "(JDD, dates, observateurs, attributs et habitats). La géométrie et "
            "le nom de la station en cours ne seront pas modifiés."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrer par nom, habitat, date…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.listw = QListWidget()
        # Double-clic = choisir : c'est le geste attendu dans une liste.
        self.listw.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.listw, 1)

        for station in stations:
            texte = resume_station(station)
            item = QListWidgetItem(texte)
            item.setData(Qt.ItemDataRole.UserRole, station.get("id"))
            item.setData(Qt.ItemDataRole.UserRole + 1, texte.lower())
            self.listw.addItem(item)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Reprendre")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _filter(self, text):
        needle = (text or "").lower().strip()
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            haystack = item.data(Qt.ItemDataRole.UserRole + 1) or ""
            item.setHidden(bool(needle) and needle not in haystack)

    def selected_id(self):
        """id local de la station retenue, ou None."""
        item = self.listw.currentItem()
        if item is None or item.isHidden():
            return None
        try:
            return int(item.data(Qt.ItemDataRole.UserRole))
        except (TypeError, ValueError):
            return None

    def showEvent(self, event):
        super().showEvent(event)
        ajuster_a_l_ecran(self, *self._taille_voulue)
