# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialogues de saisie : une station et ses habitats (création et édition)."""
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .habitat_form import HabitatForm
from .station_form import StationForm

# Identifiants serveur à préserver quand on rééedite un habitat déjà synchronisé
# (pour une synchro en mise à jour et non en re-création).
_HAB_KEEP_KEYS = ("id_habitat", "unique_id_sinp_hab")


class _FormDialog(QDialog):
    """Enveloppe un formulaire (`.validate()` / `.get_data()`) dans un OK / Annuler."""

    def __init__(self, form, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.form = form
        layout = QVBoxLayout(self)
        layout.addWidget(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_ok(self):
        ok, msg = self.form.validate()
        if not ok:
            QMessageBox.warning(self, "Validation", msg)
            return
        self.accept()

    def get_data(self):
        return self.form.get_data()


class StationDialog(QDialog):
    """Saisie/édition d'une station complète (métadonnées + 1..N habitats)."""

    def __init__(self, config=None, geom_wkt=None, geom_type=None,
                 station=None, station_nomenclatures=None,
                 habitat_nomenclatures=None, habref_search=None,
                 habref_typologies=None, observers=None, current_observer=None,
                 user_names=None, default_determiner=None, datasets=None,
                 geo_metrics=None, station_defaults=None, habitat_defaults=None,
                 abundance_cover_map=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.station = station  # dict existant → mode édition
        self.datasets = datasets or []
        self.geo_metrics = geo_metrics
        self.station_defaults = station_defaults or {}
        self.habitat_defaults = habitat_defaults or {}
        self.abundance_cover_map = abundance_cover_map or {}
        self.station_nomenclatures = station_nomenclatures or {}
        self.habitat_nomenclatures = habitat_nomenclatures or {}
        self.habref_search = habref_search
        self.habref_typologies = habref_typologies or []
        self.observers = observers or []
        self.current_observer = current_observer
        self.user_names = user_names or []
        self.default_determiner = default_determiner

        # En édition, la géométrie et les habitats viennent de la station existante.
        if station is not None:
            self.geom_wkt = geom_wkt if geom_wkt is not None else station.get("geom")
            self.geom_type = geom_type if geom_type is not None else station.get("geom_type")
            self.habitats = [dict(h) for h in station.get("habitats", [])]
        else:
            self.geom_wkt = geom_wkt
            self.geom_type = geom_type
            self.habitats = []

        self.setWindowTitle(
            "Modifier la station" if station is not None else "Nouvelle station OccHab"
        )
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)

        self.station_form = StationForm(
            self.config,
            self.station_nomenclatures,
            observers=self.observers,
            current_observer=self.current_observer,
            datasets=self.datasets,
            defaults=self.station_defaults,
        )
        if self.station is not None:
            self.station_form.set_data(self.station)
        self.station_form.set_geometry(self.geom_wkt, self.geom_type, self.geo_metrics)
        layout.addWidget(self.station_form)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)

        layout.addWidget(QLabel("Habitats de la station (double-clic pour éditer) :"))
        self.list_habitats = QListWidget()
        self.list_habitats.itemDoubleClicked.connect(
            lambda item: self._edit_habitat(self.list_habitats.row(item))
        )
        layout.addWidget(self.list_habitats)
        for habitat in self.habitats:
            self.list_habitats.addItem(self._habitat_label(habitat))

        row = QHBoxLayout()
        btn_add = QPushButton("Ajouter un habitat")
        btn_add.clicked.connect(self.add_habitat)
        btn_remove = QPushButton("Retirer")
        btn_remove.clicked.connect(self.remove_habitat)
        row.addWidget(btn_add)
        row.addWidget(btn_remove)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------ habitats
    @staticmethod
    def _habitat_label(habitat):
        label = "cd_hab %s — %s" % (habitat.get("cd_hab"), habitat.get("nom_cite") or "")
        recovery = habitat.get("recovery_percentage")
        if isinstance(recovery, (int, float)) and recovery:  # 0 / None = non renseigné
            label += " — %g %% de recouvrement" % recovery
        return label

    def _new_habitat_form(self):
        return HabitatForm(
            self.habitat_nomenclatures,
            self.habref_search,
            typologies=self.habref_typologies,
            user_names=self.user_names,
            default_determiner=self.default_determiner,
            defaults=self.habitat_defaults,
            abundance_cover_map=self.abundance_cover_map,
        )

    def add_habitat(self):
        dialog = _FormDialog(self._new_habitat_form(), "Nouvel habitat", self)
        if dialog.exec():
            data = dialog.get_data()
            self.habitats.append(data)
            self.list_habitats.addItem(self._habitat_label(data))

    def _edit_habitat(self, row):
        if row < 0 or row >= len(self.habitats):
            return
        form = self._new_habitat_form()
        form.set_data(self.habitats[row])
        dialog = _FormDialog(form, "Modifier l'habitat", self)
        if dialog.exec():
            edited = dialog.get_data()
            # Préserver les identifiants serveur pour une synchro en mise à jour.
            for key in _HAB_KEEP_KEYS:
                if self.habitats[row].get(key):
                    edited[key] = self.habitats[row][key]
            self.habitats[row] = edited
            self.list_habitats.item(row).setText(self._habitat_label(edited))

    def remove_habitat(self):
        row = self.list_habitats.currentRow()
        if row < 0:
            QMessageBox.information(self, "OccHab", "Sélectionnez un habitat à retirer.")
            return
        confirm = QMessageBox.question(
            self,
            "Retirer l'habitat",
            "Retirer l'habitat « %s » de la station ?"
            % self._habitat_label(self.habitats[row]),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.list_habitats.takeItem(row)
        del self.habitats[row]

    # --------------------------------------------------------------- OK
    def _on_ok(self):
        ok, msg = self.station_form.validate()
        if not ok:
            QMessageBox.warning(self, "Validation", msg)
            return
        if not self.habitats:
            QMessageBox.warning(
                self, "Validation", "Ajoutez au moins un habitat à la station."
            )
            return
        self.accept()

    def get_result(self):
        """Retourne (données_station, [données_habitats])."""
        return self.station_form.get_data(), list(self.habitats)
