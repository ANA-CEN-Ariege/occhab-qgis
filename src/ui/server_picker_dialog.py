# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialogue de récupération de stations serveur par recherche texte.

Alternative à la sélection sur la carte : liste cherchable des stations d'un JDD,
pour les utilisateurs peu à l'aise avec la sélection spatiale de QGIS. On coche
les stations voulues ; `selected_ids()` renvoie leurs id_station.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class ServerStationPicker(QDialog):
    """Sélecteur texte de stations serveur (récupération vers la base locale)."""

    def __init__(self, stations, parent=None):
        """`stations` : liste de dicts {id_station, habitat, date, observer}."""
        super().__init__(parent)
        self.setWindowTitle("Récupérer du serveur")
        self.resize(480, 440)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Cherchez une station et cochez-la pour la récupérer dans votre base "
            "locale (vous pourrez alors l'éditer)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrer par habitat, observateur, date…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.listw = QListWidget()
        self.listw.itemChanged.connect(self._update_count)
        layout.addWidget(self.listw, 1)

        for station in stations:
            id_station = station.get("id_station")
            label = station.get("habitat") or ("station %s" % id_station)
            date = station.get("date") or "?"
            observer = station.get("observer") or ""
            text = "%s — %s" % (label, date)
            if observer:
                text += " — %s" % observer
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, id_station)
            item.setData(Qt.ItemDataRole.UserRole + 1, text.lower())
            self.listw.addItem(item)

        foot = QHBoxLayout()
        self.count_label = QLabel("0 sélectionnée")
        self.count_label.setStyleSheet("color: palette(mid);")
        foot.addWidget(self.count_label)
        foot.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Récupérer")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        foot.addWidget(buttons)
        layout.addLayout(foot)

    def _filter(self, text):
        needle = (text or "").lower().strip()
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            haystack = item.data(Qt.ItemDataRole.UserRole + 1) or ""
            item.setHidden(bool(needle) and needle not in haystack)

    def _update_count(self, *_args):
        count = len(self.selected_ids())
        self.count_label.setText(
            "%d sélectionnée%s" % (count, "s" if count > 1 else "")
        )

    def selected_ids(self):
        """id_station des stations cochées."""
        ids = []
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                try:
                    ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
                except (TypeError, ValueError):
                    pass
        return ids
