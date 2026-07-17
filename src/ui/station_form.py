"""Formulaire de saisie d'une station OccHab (aligné sur le formulaire GeoNature)."""
from qgis.PyQt.QtCore import Qt, QDate
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..processing.eval_fields import (
    ETATS_CONSERVATION,
    NIVEAUX_ENJEU,
    decode_eval,
    encode_eval,
    fill_eval_combo,
    select_combo_data,
    strip_eval,
)


class StationForm(QWidget):
    """Champs de la station + niveau d'enjeu / état de conservation (extension ANA).

    Args:
        nomenclatures: dict {clé: [(id_nomenclature, libellé)]} pour les listes
            'exposure', 'surface_method', 'geo_object'. Vide → combos vides.
    """

    def __init__(self, config=None, nomenclatures=None, observers=None,
                 current_observer=None, datasets=None, defaults=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.nomenclatures = nomenclatures or {}
        self._defaults = defaults or {}  # id_nomenclature par défaut (instance)
        self._observers = observers or []  # [(id_role, nom)]
        self._current_observer = current_observer  # {id_role, observer_name} ou None
        self._datasets = datasets or []  # [(id_dataset, nom)]
        self.combo_dataset = None
        self.spin_dataset = None
        self._geom_wkt = None
        self._geom_type = None
        self._build()

    def _build(self):
        form = QFormLayout(self)

        self.label_geom = QLabel("Aucune géométrie")
        form.addRow("Géométrie", self.label_geom)

        default_ds = None
        if self.config is not None and self.config.get("id_dataset"):
            default_ds = int(self.config.get("id_dataset"))
        if self._datasets:  # combo par NOM (plus lisible qu'un id)
            self.combo_dataset = QComboBox()
            for id_ds, name in self._datasets:
                self.combo_dataset.addItem(name, id_ds)
            index = self.combo_dataset.findData(default_ds)
            if index >= 0:
                self.combo_dataset.setCurrentIndex(index)
            form.addRow("Jeu de données (JDD) *", self.combo_dataset)
        else:  # repli hors-ligne : saisie de l'id
            self.spin_dataset = QSpinBox()
            self.spin_dataset.setRange(0, 10_000_000)
            if default_ds:
                self.spin_dataset.setValue(default_ds)
            form.addRow("Jeu de données (JDD) *", self.spin_dataset)

        self.edit_name = QLineEdit()
        form.addRow("Nom de la station", self.edit_name)

        form.addRow("Observateur(s)", self._build_observers_widget())

        self.date_min = QDateEdit(QDate.currentDate())
        self.date_min.setCalendarPopup(True)
        form.addRow("Date début", self.date_min)

        self.date_max = QDateEdit(QDate.currentDate())
        self.date_max.setCalendarPopup(True)
        form.addRow("Date fin", self.date_max)

        self.spin_alt_min = QSpinBox()
        self.spin_alt_min.setRange(0, 9000)
        form.addRow("Altitude min", self.spin_alt_min)

        self.spin_alt_max = QSpinBox()
        self.spin_alt_max.setRange(0, 9000)
        form.addRow("Altitude max", self.spin_alt_max)

        # Profondeur (m) — pour les stations en milieu aquatique/marin.
        self.spin_depth_min = QSpinBox()
        self.spin_depth_min.setRange(0, 12000)
        self.spin_depth_min.setSpecialValueText("—")  # 0 = non renseigné
        form.addRow("Profondeur min", self.spin_depth_min)

        self.spin_depth_max = QSpinBox()
        self.spin_depth_max.setRange(0, 12000)
        self.spin_depth_max.setSpecialValueText("—")
        form.addRow("Profondeur max", self.spin_depth_max)

        # Type de sol / mosaïque : champs absents des instances GeoNature anciennes
        # (nomenclature non fournie) → on ne crée le menu que si des valeurs existent.
        self.combo_type_sol = None
        if self.nomenclatures.get("type_sol"):
            self.combo_type_sol = QComboBox()
            fill_eval_combo(self.combo_type_sol, self.nomenclatures["type_sol"])
            select_combo_data(self.combo_type_sol, self._defaults.get("type_sol"))
            form.addRow("Type de sol", self.combo_type_sol)

        self.combo_mosaique = None
        if self.nomenclatures.get("mosaique"):
            self.combo_mosaique = QComboBox()
            fill_eval_combo(self.combo_mosaique, self.nomenclatures["mosaique"])
            select_combo_data(self.combo_mosaique, self._defaults.get("mosaique"))
            form.addRow("Type de mosaïque d'habitats", self.combo_mosaique)

        self.combo_exposure = QComboBox()
        fill_eval_combo(self.combo_exposure, self.nomenclatures.get("exposure", []))
        select_combo_data(self.combo_exposure, self._defaults.get("exposure"))
        form.addRow("Exposition", self.combo_exposure)

        self.spin_area = QSpinBox()
        self.spin_area.setRange(0, 2_000_000_000)
        self.spin_area.setSuffix(" m²")
        form.addRow("Surface", self.spin_area)

        self.combo_surface_method = QComboBox()
        fill_eval_combo(self.combo_surface_method, self.nomenclatures.get("surface_method", []))
        select_combo_data(self.combo_surface_method, self._defaults.get("surface_method"))
        form.addRow("Méthode de calcul de la surface", self.combo_surface_method)

        self.combo_geo_object = QComboBox()
        fill_eval_combo(self.combo_geo_object, self.nomenclatures.get("geo_object", []))
        select_combo_data(self.combo_geo_object, self._defaults.get("geo_object"))
        form.addRow("Nature objet géographique", self.combo_geo_object)

        # Extension ANA : encodés dans le commentaire (voir README §6).
        self.combo_enjeu = QComboBox()
        fill_eval_combo(self.combo_enjeu, NIVEAUX_ENJEU)
        form.addRow("Niveau d'enjeu", self.combo_enjeu)

        self.combo_etat = QComboBox()
        fill_eval_combo(self.combo_etat, ETATS_CONSERVATION)
        form.addRow("État de conservation", self.combo_etat)

        self.text_comment = QTextEdit()
        self.text_comment.setPlaceholderText("Commentaire libre…")
        self.text_comment.setMaximumHeight(70)
        form.addRow("Commentaire", self.text_comment)

    # -------------------------------------------------------- observateurs
    def _build_observers_widget(self):
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        self.filter_observers = QLineEdit()
        self.filter_observers.setPlaceholderText("Filtrer les observateurs…")
        self.filter_observers.textChanged.connect(self._filter_observers)
        box.addWidget(self.filter_observers)
        self.list_observers = QListWidget()
        self.list_observers.setMaximumHeight(110)
        box.addWidget(self.list_observers)

        items = list(self._observers)
        known = {id_role for id_role, _ in items}
        current = self._current_observer
        if current and current.get("id_role") not in known:
            items.insert(0, (current["id_role"],
                             current.get("observer_name") or str(current["id_role"])))
        for id_role, name in items:
            checked = bool(current and id_role == current.get("id_role"))
            self._add_observer_item(id_role, name, checked)
        return container

    def _add_observer_item(self, id_role, name, checked):
        item = QListWidgetItem(name or str(id_role))
        item.setData(Qt.UserRole, id_role)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.list_observers.addItem(item)

    def _filter_observers(self, text):
        needle = text.lower()
        for i in range(self.list_observers.count()):
            item = self.list_observers.item(i)
            item.setHidden(needle not in item.text().lower())

    def _selected_observers(self):
        result = []
        for i in range(self.list_observers.count()):
            item = self.list_observers.item(i)
            if item.checkState() == Qt.Checked:
                result.append(
                    {"id_role": item.data(Qt.UserRole), "observer_name": item.text()}
                )
        return result

    def _apply_observers(self, observers):
        """Cocher exactement les observateurs de la station (édition)."""
        wanted = {
            o.get("id_role"): o.get("observer_name")
            for o in observers
            if o.get("id_role")
        }
        present = set()
        for i in range(self.list_observers.count()):
            item = self.list_observers.item(i)
            id_role = item.data(Qt.UserRole)
            present.add(id_role)
            item.setCheckState(Qt.Checked if id_role in wanted else Qt.Unchecked)
        for id_role, name in wanted.items():
            if id_role not in present:
                self._add_observer_item(id_role, name, True)

    # ------------------------------------------------------------- API
    def _id_dataset(self):
        if self.combo_dataset is not None:
            return self.combo_dataset.currentData()
        return self.spin_dataset.value() if self.spin_dataset is not None else None

    def _select_dataset(self, id_dataset):
        if self.combo_dataset is not None:
            index = self.combo_dataset.findData(id_dataset)
            if index >= 0:
                self.combo_dataset.setCurrentIndex(index)
        elif self.spin_dataset is not None:
            self.spin_dataset.setValue(id_dataset)

    def set_geometry(self, wkt, geom_type, metrics=None):
        self._geom_wkt = wkt
        self._geom_type = geom_type
        self.label_geom.setText(
            "%s (EPSG:4326)" % (geom_type or "géométrie") if wkt else "Aucune géométrie"
        )
        if metrics:  # surface / altitude calculées auto (polygone, MNT serveur)
            if metrics.get("area") is not None:
                self.spin_area.setValue(int(metrics["area"]))
            if metrics.get("altitude_min") is not None:
                self.spin_alt_min.setValue(int(metrics["altitude_min"]))
            if metrics.get("altitude_max") is not None:
                self.spin_alt_max.setValue(int(metrics["altitude_max"]))

    def validate(self):
        if not self._id_dataset():
            return False, "Le jeu de données (JDD) est obligatoire."
        if self.date_min.date() > self.date_max.date():
            return False, "La date de début doit précéder la date de fin."
        return True, ""

    def get_data(self):
        comment = encode_eval(
            self.text_comment.toPlainText(),
            enjeu=self.combo_enjeu.currentData(),
            etat_conservation=self.combo_etat.currentData(),
        )
        observers = self._selected_observers()
        return {
            "id_dataset": self._id_dataset(),
            "station_name": self.edit_name.text().strip() or None,
            "date_min": self.date_min.date().toString("yyyy-MM-dd"),
            "date_max": self.date_max.date().toString("yyyy-MM-dd"),
            "observers_txt": ", ".join(o["observer_name"] for o in observers) or None,
            "_observers": observers,  # géré à part (cor_station_observer)
            "altitude_min": self.spin_alt_min.value() or None,
            "altitude_max": self.spin_alt_max.value() or None,
            "depth_min": self.spin_depth_min.value() or None,
            "depth_max": self.spin_depth_max.value() or None,
            "area": self.spin_area.value() or None,
            "id_nomenclature_exposure": self.combo_exposure.currentData(),
            "id_nomenclature_area_surface_calculation": self.combo_surface_method.currentData(),
            "id_nomenclature_geographic_object": self.combo_geo_object.currentData(),
            "id_nomenclature_type_sol": (
                self.combo_type_sol.currentData() if self.combo_type_sol else None
            ),
            "id_nomenclature_type_mosaique_habitat": (
                self.combo_mosaique.currentData() if self.combo_mosaique else None
            ),
            "comment": comment or None,
            "geom": self._geom_wkt,
            "geom_type": self._geom_type,
            "created_by": _current_user(),
        }

    def set_data(self, station):
        if station.get("id_dataset"):
            self._select_dataset(int(station["id_dataset"]))
        self.edit_name.setText(station.get("station_name") or "")
        self._apply_observers(station.get("observers", []))
        if station.get("altitude_min"):
            self.spin_alt_min.setValue(int(station["altitude_min"]))
        if station.get("altitude_max"):
            self.spin_alt_max.setValue(int(station["altitude_max"]))
        if station.get("depth_min"):
            self.spin_depth_min.setValue(int(station["depth_min"]))
        if station.get("depth_max"):
            self.spin_depth_max.setValue(int(station["depth_max"]))
        if station.get("area"):
            self.spin_area.setValue(int(station["area"]))
        select_combo_data(self.combo_exposure, station.get("id_nomenclature_exposure"))
        select_combo_data(
            self.combo_surface_method,
            station.get("id_nomenclature_area_surface_calculation"),
        )
        select_combo_data(
            self.combo_geo_object, station.get("id_nomenclature_geographic_object")
        )
        if self.combo_type_sol:
            select_combo_data(self.combo_type_sol, station.get("id_nomenclature_type_sol"))
        if self.combo_mosaique:
            select_combo_data(
                self.combo_mosaique, station.get("id_nomenclature_type_mosaique_habitat")
            )
        comment = station.get("comment") or ""
        self.text_comment.setPlainText(strip_eval(comment))
        codes = decode_eval(comment)
        select_combo_data(self.combo_enjeu, codes.get("enjeu"))
        select_combo_data(self.combo_etat, codes.get("etat_conservation"))


def _current_user():
    try:
        from qgis.core import QgsApplication

        return QgsApplication.userFullName() or "qgis"
    except Exception:
        return "qgis"
