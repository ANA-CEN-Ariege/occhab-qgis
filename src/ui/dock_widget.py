# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dock principal du plugin OccHab : connexion, saisie et synchronisation."""
import os

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..database.sqlite_local import OccHabDatabase
from .connection_dialog import ConnectionDialog
from .station_dialog import StationDialog
from .station_layers import StationLayerManager
from .server_layers import ServerStationLayerManager

_GEOM_TYPES = [("Polygone", "polygon"), ("Point", "point")]

# Nomenclatures OccHab, par champ de formulaire → mnémonique GeoNature.
STATION_NOMENCLATURES = {
    "exposure": "EXPOSITION",
    "surface_method": "METHOD_CALCUL_SURFACE",
    "geo_object": "NAT_OBJ_GEO",
    "type_sol": "TYPE_SOL",
    "mosaique": "MOSAIQUE_HAB",
}
HABITAT_NOMENCLATURES = {
    "technique": "TECHNIQUE_COLLECT_HAB",
    "determination": "DETERMINATION_TYP_HAB",
    "abundance": "ABONDANCE_HAB",
    "sensitivity": "SENSIBILITE",
    "community_interest": "HAB_INTERET_COM",
}


class OccHabDockWidget(QDockWidget):
    """Widget d'ancrage : connexion GeoNature, tableau des stations, synchro."""

    def __init__(self, iface, config, logger, parent=None):
        super().__init__("OccHab GeoNature", parent)
        self.iface = iface
        self.config = config
        self.logger = logger
        self.db = OccHabDatabase(config.get("local_db.path"))
        self.client = None
        self._user_label = None
        self.nomenclatures = {}
        self.default_nomenclatures = {}
        self.typologies = []
        self.observers = []
        self.layers = StationLayerManager(self.logger)
        self.server_layers = ServerStationLayerManager(
            str(config.user_config_dir / "server_stations.geojson"), self.logger
        )
        self._capture = None
        self._capture_target = None  # None/"new" = nouvelle station ; int = id station à re-géométrer
        self._geom_editor = None
        self._edit_geom_station_id = None
        self._map_filter_installed = False
        self._server_prompt = None
        self._build_ui()
        self._install_map_interaction()
        self.refresh()

    # ------------------------------------------------------------- UI
    def _build_ui(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        # Connexion + JDD : bloc compact repliable (divulgation progressive).
        conn_frame = QFrame()
        conn_frame.setFrameShape(QFrame.Shape.StyledPanel)
        conn_v = QVBoxLayout(conn_frame)
        conn_v.setContentsMargins(9, 7, 9, 7)
        conn_v.setSpacing(5)

        summary = QHBoxLayout()
        self.label_conn = QLabel("● Non connecté")
        self.label_conn.setStyleSheet("font-weight: 600;")
        # Retour à la ligne : évite qu'un JDD au nom long n'impose une largeur
        # minimale énorme au dock (sinon impossible de le rétrécir).
        self.label_conn.setWordWrap(True)
        summary.addWidget(self.label_conn, 1)
        self.btn_conn_toggle = QToolButton()
        self.btn_conn_toggle.setText("changer")
        self.btn_conn_toggle.setAutoRaise(True)
        self.btn_conn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_conn_toggle.clicked.connect(self._toggle_conn_details)
        summary.addWidget(self.btn_conn_toggle)
        conn_v.addLayout(summary)

        self.label_server = QLabel("")  # nb de stations serveur (contexte)
        self.label_server.setStyleSheet("color: palette(mid);")
        self.label_server.setWordWrap(True)
        self.label_server.setToolTip("Stations déjà présentes sur GeoNature pour ce JDD")
        conn_v.addWidget(self.label_server)

        # Détails repliables : (re)connexion, choix du JDD, filtre « mes stations ».
        self.conn_details = QWidget()
        det_v = QVBoxLayout(self.conn_details)
        det_v.setContentsMargins(0, 4, 0, 0)
        det_v.setSpacing(6)

        self.btn_connect = QPushButton("Connexion GeoNature…")
        self.btn_connect.clicked.connect(self.open_connection)
        det_v.addWidget(self.btn_connect)

        row_jdd = QHBoxLayout()
        row_jdd.addWidget(QLabel("JDD :"))
        self.combo_jdd = QComboBox()
        self.combo_jdd.setEnabled(False)
        # Éditable + autocomplétion « contient » (utile quand les JDD sont nombreux).
        self.combo_jdd.setEditable(True)
        self.combo_jdd.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo_jdd.lineEdit().setPlaceholderText("Rechercher un JDD…")
        jdd_completer = self.combo_jdd.completer()
        jdd_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        jdd_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        jdd_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        jdd_completer.setMaxVisibleItems(15)
        # Popup plus lisible : lignes aérées (le nom complet est cadré dans
        # _fit_jdd_popup_width une fois les JDD chargés).
        jdd_completer.popup().setStyleSheet("QListView::item { padding: 4px 8px; }")
        self.combo_jdd.currentIndexChanged.connect(self._on_jdd_changed)
        # Choix EXPLICITE d'un JDD par l'utilisateur → replier le bloc connexion.
        # `activated` (contrairement à `currentIndexChanged`) ne se déclenche pas sur
        # la sélection automatique du JDD par défaut au chargement.
        self.combo_jdd.activated.connect(lambda _i: self._collapse_conn_details())
        row_jdd.addWidget(self.combo_jdd, 1)
        det_v.addLayout(row_jdd)

        self.check_only_mine = QCheckBox("N'afficher que mes stations serveur")
        self.check_only_mine.setEnabled(False)  # activé une fois connecté (JDD chargés)
        self.check_only_mine.setToolTip(
            "Sur la carte serveur, ne montrer que les stations dont je suis le "
            "numérisateur (id_digitiser)."
        )
        self.check_only_mine.stateChanged.connect(lambda _s: self._load_server_stations())
        det_v.addWidget(self.check_only_mine)

        conn_v.addWidget(self.conn_details)
        layout.addWidget(conn_frame)

        # Mes stations locales : source de vérité éditable (id local caché en donnée).
        row_head = QHBoxLayout()
        lbl_local = QLabel("Mes stations")
        lbl_local.setStyleSheet("font-weight: 600;")
        row_head.addWidget(lbl_local)
        row_head.addStretch(1)
        self.label_count = QLabel("")
        self.label_count.setStyleSheet("color: palette(mid);")
        row_head.addWidget(self.label_count)
        layout.addLayout(row_head)

        # Barre d'action ancrée AU-DESSUS de la liste (idiome QGIS : agit sur la
        # station sélectionnée). Icône + texte, grisée sans sélection ; Supprimer
        # (destructif) isolé à droite et en rouge.
        self.btn_edit = self._action_button(
            "Éditer", "/mActionMultiEdit.svg",
            "Éditer les attributs et habitats de la station sélectionnée.",
        )
        self.btn_edit.clicked.connect(self.edit_station)
        self.btn_geom = self._action_button(
            "Géométrie", "/mActionVertexTool.svg",
            "Modifier la géométrie de la station sélectionnée.",
        )
        geom_menu = QMenu(self.btn_geom)
        geom_menu.setToolTipsVisible(True)
        geom_menu.addAction("Redessiner / éditer sur la carte", self.edit_geometry)
        act_reuse_geom = geom_menu.addAction(
            "Copier l'entité sélectionnée d'une autre couche", self._assign_selection_to_station
        )
        act_reuse_geom.setToolTip(
            "Sélectionnez d'abord une entité dans une autre couche, puis choisissez ceci."
        )
        geom_menu.addSeparator()
        geom_menu.addAction(
            "Rétablir la géométrie précédente", self.restore_previous_geometry
        )
        self.btn_geom.setMenu(geom_menu)
        self.btn_geom.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_zoom = self._action_button(
            "Zoom", "/mActionZoomToSelected.svg",
            "Zoomer sur la station sélectionnée ; sans sélection, sur l'emprise du JDD.",
        )
        self.btn_zoom.clicked.connect(self.zoom_to_stations)
        self.btn_delete = self._action_button(
            "Supprimer", "/mActionDeleteSelected.svg",
            "Supprimer la station sélectionnée.",
        )
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_delete.setStyleSheet("QToolButton { color: #b23125; }")
        row_actions = QHBoxLayout()
        row_actions.setSpacing(3)
        row_actions.setContentsMargins(0, 0, 0, 0)
        row_actions.addWidget(self.btn_edit)
        row_actions.addWidget(self.btn_geom)
        row_actions.addWidget(self.btn_zoom)
        row_actions.addStretch(1)
        row_actions.addWidget(self.btn_delete)
        layout.addLayout(row_actions)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Habitat(s)", "Date", "État"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.edit_station())
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        layout.addWidget(self.table, 1)

        # Créer une nouvelle station : un seul menu répond à « d'où vient la
        # géométrie ? » (dessiner, reprendre une entité d'une couche, ou aucune).
        self.btn_new = QPushButton("＋ Nouvelle station")
        new_menu = QMenu(self.btn_new)
        new_menu.setToolTipsVisible(True)
        new_menu.addAction("Dessiner un polygone", lambda: self._new_station_draw("polygon"))
        new_menu.addAction("Dessiner un point", lambda: self._new_station_draw("point"))
        act_reuse_new = new_menu.addAction(
            "Copier l'entité sélectionnée d'une autre couche", self._new_station_from_selection
        )
        act_reuse_new.setToolTip(
            "Sélectionnez d'abord une entité dans une autre couche, puis choisissez ceci."
        )
        new_menu.addSeparator()
        new_menu.addAction("Sans géométrie (à tracer plus tard)", self._new_station_no_geom)
        self.btn_new.setMenu(new_menu)
        layout.addWidget(self.btn_new)

        # Contexte SERVEUR : synchroniser, rafraîchir, récupérer (deux chemins).
        label_srv = QLabel("Serveur")
        label_srv.setStyleSheet("font-weight: 600;")
        layout.addWidget(label_srv)

        row_srv = QHBoxLayout()
        row_srv.setSpacing(4)
        self.btn_sync = QPushButton("Synchroniser")
        self.btn_sync.setToolTip(
            "Envoyer vos créations / modifications / suppressions vers GeoNature."
        )
        self.btn_sync.clicked.connect(self.synchronize)
        self.btn_refresh = QPushButton("Rafraîchir")
        self.btn_refresh.setToolTip("Recharger les stations locales et le contexte serveur.")
        self.btn_refresh.clicked.connect(self.refresh)
        row_srv.addWidget(self.btn_sync, 1)
        row_srv.addWidget(self.btn_refresh)
        layout.addLayout(row_srv)

        self.btn_import = QPushButton("Récupérer une station du serveur…")
        self.btn_import.setToolTip(
            "Amener une station GeoNature dans votre base locale pour l'éditer."
        )
        import_menu = QMenu(self.btn_import)
        import_menu.addAction("Depuis la carte (sélection)…", self.import_server_stations)
        import_menu.addAction("Chercher une station…", self.open_server_picker)
        self.btn_import.setMenu(import_menu)
        layout.addWidget(self.btn_import)

        # Footer : où sont stockées les données locales + sauvegarde/export
        footer = QHBoxLayout()
        db_path = str(self.db.db_path)
        self.label_db = QLabel("Base locale : %s" % os.path.basename(db_path))
        self.label_db.setToolTip(db_path)
        footer.addWidget(self.label_db)
        footer.addStretch(1)
        btn_storage = QPushButton("Base locale…")
        menu = QMenu(btn_storage)
        menu.addAction("Ouvrir le dossier", self._open_db_folder)
        menu.addAction("Sauvegarder (copie .db)…", self._backup_db)
        menu.addAction("Exporter en GeoPackage…", self._export_geopackage)
        menu.addAction(
            "Exporter la cartographie du JDD (serveur)…", self.export_jdd_cartography
        )
        btn_storage.setMenu(menu)
        footer.addWidget(btn_storage)
        layout.addLayout(footer)

        # Ascenseur : le panneau peut être plus haut que le dock ; sans scroll, le
        # bas (section Serveur, pied) se ferait couper sur un dock court.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(container)
        self.setWidget(scroll)
        self._update_conn_summary()
        self._on_selection_changed()

    def _toggle_conn_details(self):
        """Afficher / masquer les détails de connexion (divulgation progressive)."""
        visible = not self.conn_details.isVisible()
        self.conn_details.setVisible(visible)
        self.btn_conn_toggle.setText("replier" if visible else "changer")

    def _collapse_conn_details(self):
        """Replier le bloc connexion (une fois le JDD choisi)."""
        self.conn_details.setVisible(False)
        self.btn_conn_toggle.setText("changer")

    def _update_conn_summary(self):
        """Résumé compact connexion + JDD."""
        if self.client is not None and self.client.is_authenticated:
            jdd = self.combo_jdd.currentText() if self.combo_jdd.count() else "—"
            self.label_conn.setText("✓ %s  ·  %s" % (self._user_label or "Connecté", jdd))
            self.btn_conn_toggle.setVisible(True)
        else:
            self.label_conn.setText("● Non connecté")
            self.conn_details.setVisible(True)
            self.btn_conn_toggle.setVisible(False)

    def _on_selection_changed(self):
        """Activer la barre d'action seulement quand une station est sélectionnée."""
        has = self._selected_station_id() is not None
        for btn in (self.btn_edit, self.btn_geom, self.btn_delete):
            btn.setEnabled(has)

    def _action_button(self, text, icon_name, tooltip):
        """Bouton d'action icône + texte (icône du thème QGIS, repli sur le texte)."""
        from qgis.core import QgsApplication

        button = QToolButton()
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setText(text)
        button.setToolTip(tooltip)
        icon = QgsApplication.getThemeIcon(icon_name)
        if icon is not None and not icon.isNull():
            button.setIcon(icon)
        return button

    def _table_context_menu(self, pos):
        """Menu clic-droit sur une station (mêmes actions que la barre)."""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        self.table.selectRow(index.row())
        menu = QMenu(self.table)
        menu.addAction("Éditer", self.edit_station)
        geom = menu.addMenu("Modifier la géométrie")
        geom.addAction("Redessiner / éditer sur la carte", self.edit_geometry)
        geom.addAction(
            "Copier l'entité sélectionnée d'une autre couche", self._assign_selection_to_station
        )
        geom.addSeparator()
        geom.addAction("Rétablir la géométrie précédente", self.restore_previous_geometry)
        menu.addAction("Zoom", self.zoom_to_stations)
        menu.addSeparator()
        menu.addAction("Supprimer", self.delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # (glyphe, libellé, texte, fond OPAQUE, bordure). Fond opaque : le chip reste
    # lisible même quand la ligne est sélectionnée (surlignage bleu par-dessous).
    _PILL_STYLES = {
        "synced": ("✓", "Synchronisée", "#12579f", "#e6effb", "#bcdcf5"),
        "pending": ("↑", "À synchroniser", "#8a4d02", "#fbeedb", "#f0d6ac"),
        "conflict": ("▲", "Conflit", "#b23125", "#fbe4e0", "#f2c4bc"),
        "to_delete": ("✕", "À supprimer", "#566070", "#eceef1", "#d5d9df"),
    }

    def _status_pill(self, sync_status, id_station):
        """Pastille d'état « couleur + icône + texte » (chip opaque)."""
        glyph, label, fg, bg, border = self._PILL_STYLES.get(
            sync_status, self._PILL_STYLES["pending"]
        )
        widget = QLabel("%s %s" % (glyph, label))
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        widget.setStyleSheet(
            "QLabel { color: %s; background-color: %s; border: 1px solid %s;"
            " border-radius: 9px; padding: 1px 8px; margin: 2px 4px; font-weight: 600; }"
            % (fg, bg, border)
        )
        return widget

    # ------------------------------------------------------- connexion
    def open_connection(self):
        dialog = ConnectionDialog(self.config, parent=self)
        if not dialog.exec():
            return
        self.client = dialog.client
        self._user_label = dialog.user_label()
        self.logger.info(
            "Connecté à %s en tant que %s",
            self.config.get("geonature.api_url"),
            dialog.user_label(),
        )
        self._load_datasets()
        self._load_reference_data()
        # On laisse le bloc OUVERT : l'utilisateur choisit d'abord son JDD ; le bloc
        # se replie ensuite de lui-même à la sélection (voir combo_jdd.activated).
        self._update_conn_summary()

    def _load_datasets(self):
        """Charger les JDD actifs rattachés au module OccHab.

        On demande les modules de chaque JDD (fields=modules) et on filtre sur
        l'association OccHab. Repli sur le filtre par permission (create=<module>)
        si l'instance ne renvoie pas la liste des modules.
        """
        if self.client is None:
            return
        module_code = (
            self.config.get("geonature.occhab_module_code", "OCCHAB") or "OCCHAB"
        ).upper()

        raw = self._fetch_datasets({"active": "true", "fields": "modules"})
        if raw and any("modules" in ds for ds in raw):
            datasets = [ds for ds in raw if self._has_module(ds, module_code)]
        else:
            # 'modules' non fourni : repli sur les JDD actifs créables en OccHab
            datasets = self._fetch_datasets({"active": "true", "create": module_code})
            if not datasets:
                datasets = self._fetch_datasets({"active": "true"})

        self.combo_jdd.blockSignals(True)
        self.combo_jdd.clear()
        self.combo_jdd.addItem("— Tous les JDD —", None)  # vue sans filtre
        for dataset in datasets:
            id_dataset = dataset.get("id_dataset")
            name = dataset.get("dataset_name") or dataset.get("dataset_shortname") or id_dataset
            if id_dataset is not None:
                self.combo_jdd.addItem(str(name), id_dataset)
        if self.combo_jdd.count() > 1:
            self.combo_jdd.setCurrentIndex(1)  # premier JDD réel par défaut
        self.combo_jdd.blockSignals(False)
        self.combo_jdd.setEnabled(self.combo_jdd.count() > 1)
        self.check_only_mine.setEnabled(self.combo_jdd.count() > 1)
        self._fit_jdd_popup_width()
        self._on_jdd_changed()
        self.logger.info("%d jeu(x) de données chargé(s)", self.combo_jdd.count() - 1)

    def _fit_jdd_popup_width(self):
        """Élargir le popup d'autocomplétion pour afficher les noms de JDD complets."""
        popup = self.combo_jdd.completer().popup()
        metrics = popup.fontMetrics()
        longest = 0
        for i in range(self.combo_jdd.count()):
            try:
                width = metrics.horizontalAdvance(self.combo_jdd.itemText(i))
            except AttributeError:  # Qt < 5.11
                width = metrics.width(self.combo_jdd.itemText(i))
            longest = max(longest, width)
        # marge pour le padding des lignes + un éventuel ascenseur
        popup.setMinimumWidth(min(max(longest + 60, self.combo_jdd.width()), 640))

    def _fetch_datasets(self, params):
        """Appel bas-niveau à /meta/datasets, tolérant au format (liste ou {data:[...]})."""
        try:
            response = self.client.get_datasets(params=params)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("JDD non chargés (params=%s) : %s", params, exc)
            return []
        if isinstance(response, dict):
            response = response.get("data", [])
        return response if isinstance(response, list) else []

    @staticmethod
    def _has_module(dataset, module_code):
        """Vrai si le JDD est rattaché au module donné (insensible à la casse)."""
        modules = dataset.get("modules") or []
        return any(
            str(m.get("module_code", "")).upper() == module_code for m in modules
        )

    # --------------------------------------------------- données de référence
    def _load_reference_data(self):
        """Précharger toutes les nomenclatures des formulaires (station + habitat)."""
        self.nomenclatures = {}
        codes = set(STATION_NOMENCLATURES.values()) | set(HABITAT_NOMENCLATURES.values())
        for code in sorted(codes):
            try:
                self.nomenclatures[code] = self.client.get_nomenclature_values(code)
            except Exception as exc:  # noqa: BLE001
                self.nomenclatures[code] = []
                # 404 = type de nomenclature absent de cette instance (ex. TYPE_SOL
                # sur une version antérieure) : attendu, le champ sera juste masqué.
                if "404" in str(exc):
                    self.logger.info(
                        "Nomenclature %s absente de cette instance (champ masqué).", code
                    )
                else:
                    self.logger.warning("Nomenclature %s non chargée : %s", code, exc)
        self.logger.info(
            "Nomenclatures chargées : %s",
            {k: len(v) for k, v in self.nomenclatures.items()},
        )
        try:
            defaults = self.client.get_default_nomenclatures()
            self.default_nomenclatures = defaults if isinstance(defaults, dict) else {}
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Nomenclatures par défaut non chargées : %s", exc)
            self.default_nomenclatures = {}
        try:
            self.typologies = self.client.get_habref_typologies()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Typologies HABREF non chargées : %s", exc)
            self.typologies = []
        self.logger.info("Typologies HABREF chargées : %d", len(self.typologies))
        list_id = self.config.get("geonature.observer_list_id", 1) or 1
        try:
            self.observers = self.client.get_observers(list_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Observateurs non chargés : %s", exc)
            self.observers = []
        self.logger.info("Observateurs chargés : %d", len(self.observers))

    def _observers_items(self):
        """Liste (id_role, nom_complet) des observateurs de la liste OccHab."""
        items = []
        for user in self.observers:
            id_role = user.get("id_role")
            name = user.get("nom_complet") or (
                "%s %s" % (user.get("prenom_role") or "", user.get("nom_role") or "")
            ).strip()
            if id_role is not None:
                items.append((id_role, name or str(id_role)))
        return items

    def _user_names(self):
        """Noms d'utilisateurs proposés pour le champ déterminateur."""
        return [name for _, name in self._observers_items()]

    def _current_user_name(self):
        """Nom de l'utilisateur connecté (déterminateur par défaut)."""
        obs = self._current_user_observer()
        return obs.get("observer_name") if obs else None

    def _current_user_observer(self):
        """L'utilisateur connecté sous forme d'observateur (pour pré-sélection)."""
        user = self.client.user if self.client else None
        if isinstance(user, dict) and user.get("id_role"):
            name = user.get("nom_complet") or (
                "%s %s" % (user.get("prenom_role") or "", user.get("nom_role") or "")
            ).strip()
            return {"id_role": user["id_role"], "observer_name": name or str(user["id_role"])}
        return None

    def _habref_typologies(self):
        """Liste (cd_typo, nom) des typologies HABREF (Corine, EUNIS…)."""
        items = []
        for typo in self.typologies:
            cd_typo = typo.get("cd_typo")
            name = typo.get("lb_nom_typo") or str(cd_typo)
            if cd_typo is not None:
                items.append((cd_typo, name))
        return items

    def _nomenclature_items(self, mnemonique):
        """Liste (id_nomenclature, libellé) des valeurs actives d'une nomenclature."""
        items = []
        for value in self.nomenclatures.get(mnemonique, []):
            if value.get("active", True) is False:
                continue
            id_nom = value.get("id_nomenclature")
            label = (
                value.get("label_default")
                or value.get("label_fr")
                or value.get("mnemonique")
                or str(id_nom)
            )
            if id_nom is not None:
                items.append((id_nom, label))
        return items

    def _station_nomenclatures(self):
        return {
            key: self._nomenclature_items(mnem)
            for key, mnem in STATION_NOMENCLATURES.items()
        }

    def _habitat_nomenclatures(self):
        return {
            key: self._nomenclature_items(mnem)
            for key, mnem in HABITAT_NOMENCLATURES.items()
        }

    def _default_ids(self, mapping):
        """{clé de formulaire: id_nomenclature par défaut} d'après l'instance."""
        out = {}
        for key, mnem in mapping.items():
            default = self.default_nomenclatures.get(mnem)
            if isinstance(default, dict) and default.get("id_nomenclature") is not None:
                out[key] = default["id_nomenclature"]
        return out

    def _nomenclature_id_by_cd(self, mnemonique, cd):
        """id de la valeur d'un type de nomenclature par son cd_nomenclature, ou None."""
        for value in self.nomenclatures.get(mnemonique, []):
            if str(value.get("cd_nomenclature")) == str(cd):
                return value.get("id_nomenclature")
        return None

    def _station_defaults(self):
        defaults = self._default_ids(STATION_NOMENCLATURES)
        # Champs laissés « non renseigné » par défaut (placeholder).
        for key in ("geo_object", "type_sol", "mosaique"):
            defaults.pop(key, None)
        return defaults

    def _habitat_defaults(self):
        defaults = self._default_ids(HABITAT_NOMENCLATURES)
        # Technique de collecte (NOT NULL côté serveur) : défaut = « In situ » (cd 1)
        # si cette valeur existe, sinon le défaut d'instance.
        in_situ = self._nomenclature_id_by_cd("TECHNIQUE_COLLECT_HAB", "1")
        if in_situ is not None:
            defaults["technique"] = in_situ
        # Sensibilité : « Non sensible » (cd 0) par défaut, sinon défaut d'instance.
        non_sensible = self._nomenclature_id_by_cd("SENSIBILITE", "0")
        if non_sensible is not None:
            defaults["sensitivity"] = non_sensible
        return defaults

    def _abundance_cover_map(self):
        """{classe de recouvrement (cd 1..5): id_nomenclature} pour ABONDANCE_HAB."""
        out = {}
        for value in self.nomenclatures.get("ABONDANCE_HAB", []):
            try:
                cd = int(value.get("cd_nomenclature"))
            except (TypeError, ValueError):
                continue
            if value.get("id_nomenclature") is not None:
                out[cd] = value["id_nomenclature"]
        return out

    def _habref_search_fn(self):
        """Callable de recherche HABREF (avec filtre typologie) si connecté, sinon None."""
        if self.client is None or not self.client.is_authenticated:
            return None
        return lambda text, cd_typo=None: self.client.search_habref(text, cd_typo=cd_typo)

    def _dataset_items(self):
        """Liste (id_dataset, nom) des JDD (depuis la combo, hors « Tous »)."""
        items = []
        for i in range(self.combo_jdd.count()):
            data = self.combo_jdd.itemData(i)
            if data is not None:
                items.append((data, self.combo_jdd.itemText(i)))
        return items

    def _on_jdd_changed(self):
        data = self.combo_jdd.currentData()
        if data is not None:
            self.config.set("id_dataset", data)
        self.refresh()  # filtrer la vue (table + carte) sur le JDD sélectionné
        # Contexte serveur du JDD + zoom sur ses géométries (choix explicite d'un JDD).
        self._load_server_stations(zoom=True)
        self._update_conn_summary()

    def _load_server_stations(self, zoom=False):
        """Charger en contexte les stations serveur du JDD sélectionné (lecture seule).

        Si `zoom` et qu'il existe des géométries, cadrer le canevas dessus (serveur
        en priorité, sinon les stations locales du JDD).
        """
        if self.client is None or not self.client.is_authenticated:
            self.server_layers.clear()
            self.label_server.setText("")
            return
        jdd = self.combo_jdd.currentData() if self.combo_jdd.isEnabled() else None
        if jdd is None:  # « Tous les JDD » → pas de contexte serveur (trop volumineux)
            self.server_layers.clear()
            self.label_server.setText("")
            return
        try:
            fc = self.client.get_stations(params={"id_dataset": jdd}, geojson=True)
            fc = self._filter_own_stations(fc)
            count = self.server_layers.show(fc)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Stations serveur non chargées : %s", exc)
            self.server_layers.clear()
            self.label_server.setText("")
            return
        suffix = " (les miennes)" if self.check_only_mine.isChecked() else ""
        self.label_server.setText("Serveur : %d station(s)%s" % (count, suffix))
        if zoom:
            self._zoom_canvas_to_4326(self.server_layers.extent() or self.layers.extent())

    def _filter_own_stations(self, fc):
        """Ne garder que les stations numérisées par l'utilisateur si le filtre est actif."""
        if not self.check_only_mine.isChecked() or not isinstance(fc, dict):
            return fc
        my_id = (self.client.user or {}).get("id_role") if self.client else None
        if not my_id:
            return fc
        features = [
            f for f in fc.get("features", [])
            if (f.get("properties") or {}).get("id_digitiser") == my_id
        ]
        return dict(fc, features=features)

    def import_server_stations(self):
        """Récupérer des stations depuis la carte (couche serveur).

        Si des stations sont déjà sélectionnées, on les importe. Sinon, au lieu
        d'un message d'erreur, on prépare la sélection (couche + outil actifs) et on
        propose un bouton « Récupérer la sélection » : l'utilisateur sélectionne
        APRÈS avoir cliqué.
        """
        if self.client is None or not self.client.is_authenticated:
            QMessageBox.information(self, "OccHab", "Connectez-vous à GeoNature d'abord.")
            return
        ids = self.server_layers.selected_id_stations()
        if ids:
            self._import_by_ids(ids)
        else:
            self._prompt_server_selection()

    def _prompt_server_selection(self):
        """Activer la sélection sur la couche serveur + bouton « Récupérer »."""
        layer = self.server_layers.layer()
        if layer is None:
            QMessageBox.information(
                self, "OccHab",
                "Aucune couche serveur chargée. Choisissez un JDD précis, puis "
                "« Rafraîchir », avant de récupérer depuis la carte.",
            )
            return
        self.iface.setActiveLayer(layer)
        self._activate_select_tool()
        self._clear_server_prompt()
        bar = self.iface.messageBar()
        try:
            from qgis.PyQt.QtWidgets import QPushButton

            widget = bar.createMessage(
                "OccHab",
                "Sélectionnez une ou plusieurs stations sur « %s », puis :"
                % layer.name(),
            )
            button = QPushButton("Récupérer la sélection")
            button.clicked.connect(self._finish_server_selection)
            widget.layout().addWidget(button)
            self._server_prompt = bar.pushWidget(widget)
        except Exception as exc:  # noqa: BLE001 - repli si l'API barre de message diffère
            self.logger.warning("Barre de message serveur indisponible : %s", exc)
            bar.pushInfo(
                "OccHab",
                "Sélectionnez des stations sur la couche serveur, puis relancez "
                "« Récupérer → Depuis la carte ».",
            )

    def _finish_server_selection(self):
        self._clear_server_prompt()
        ids = self.server_layers.selected_id_stations()
        if not ids:
            self.iface.messageBar().pushInfo(
                "OccHab", "Aucune station sélectionnée sur la couche serveur."
            )
            return
        self._import_by_ids(ids)

    def _clear_server_prompt(self):
        if self._server_prompt is not None:
            try:
                self.iface.messageBar().popWidget(self._server_prompt)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("popWidget message serveur : %s", exc)
            self._server_prompt = None

    def _activate_select_tool(self):
        """Activer l'outil de sélection de QGIS (best-effort, selon la version)."""
        for name in ("actionSelect", "actionSelectRectangle"):
            action = getattr(self.iface, name, None)
            if not callable(action):
                continue
            try:
                act = action()
                if act is not None:
                    act.trigger()
                    return True
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Activation outil sélection (%s) : %s", name, exc)
        return False

    def open_server_picker(self):
        """Récupérer une station serveur via une recherche texte (sans la carte)."""
        if self.client is None or not self.client.is_authenticated:
            QMessageBox.information(self, "OccHab", "Connectez-vous à GeoNature d'abord.")
            return
        jdd = self.combo_jdd.currentData() if self.combo_jdd.isEnabled() else None
        if jdd is None:
            QMessageBox.information(
                self, "OccHab", "Choisissez d'abord un JDD précis (pas « Tous »)."
            )
            return
        try:
            fc = self.client.get_stations(params={"id_dataset": jdd}, geojson=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "OccHab", "Stations serveur non chargées : %s" % exc)
            return
        rows = []
        for feature in (fc.get("features") if isinstance(fc, dict) else None) or []:
            props = feature.get("properties") or {}
            id_station = props.get("id_station") or feature.get("id")
            if not id_station:
                continue
            habitats = props.get("habitats") or []
            if habitats:
                first = habitats[0]
                habitat = first.get("nom_cite") or ("cd_hab %s" % first.get("cd_hab"))
            else:
                habitat = props.get("station_name") or ("station %s" % id_station)
            rows.append({
                "id_station": id_station,
                "habitat": habitat,
                "date": (props.get("date_min") or "").split("T")[0],
                "observer": props.get("observers_txt") or "",
            })
        if not rows:
            QMessageBox.information(self, "OccHab", "Aucune station serveur pour ce JDD.")
            return
        from .server_picker_dialog import ServerStationPicker

        dialog = ServerStationPicker(rows, parent=self)
        if not dialog.exec():
            return
        ids = dialog.selected_ids()
        if ids:
            self._import_by_ids(ids)

    def _import_by_ids(self, ids):
        """Importer en local les stations serveur d'id_station donnés (pour édition).

        Permet d'éditer/re-synchroniser une station déjà sur GeoNature, y compris si
        la base locale a été perdue ou depuis une autre machine. Mémorise l'empreinte
        serveur pour la détection de conflit ultérieure.
        """
        from ..api.payload import parse_server_station, server_fingerprint

        # Stations déjà présentes en local : proposer d'écraser par la version serveur
        # (permet de restaurer une station dont les données locales ont été perdues).
        already_local = [i for i in ids if self.db.find_by_id_station(i)]
        overwrite = False
        if already_local:
            overwrite = self._ask(
                "Récupérer du serveur",
                "%d station(s) sélectionnée(s) sont déjà dans la base locale.\n\n"
                "Remplacer la copie locale par la version du serveur ?\n"
                "⚠ Les modifications locales NON synchronisées de ces stations seront "
                "écrasées." % len(already_local),
            )

        imported, restored, skipped, failed = 0, 0, 0, 0
        for id_station in ids:
            existing = self.db.find_by_id_station(id_station)
            if existing and not overwrite:
                skipped += 1
                continue
            try:
                detail = self.client.get_station(id_station)
                station, habitats, observers = parse_server_station(detail)
                snapshot = server_fingerprint(station, habitats, observers)
                props = detail.get("properties", {}) if isinstance(detail, dict) else {}
                my_id = (self.client.user or {}).get("id_role")
                mine = 1 if my_id and props.get("id_digitiser") == my_id else 0
                if existing:  # repartir proprement de la version serveur
                    self.db.delete_station(existing["id"])
                local_id = self.db.create_station(
                    sync_status="synced", mine=mine, server_snapshot=snapshot, **station
                )
                for habitat in habitats:
                    self.db.add_habitat(local_id, sync_status="synced", **habitat)
                for observer in observers:
                    self.db.add_observer(
                        local_id,
                        observer_name=observer.get("observer_name"),
                        id_role=observer.get("id_role"),
                    )
                if existing:
                    restored += 1
                else:
                    imported += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.logger.error("Récupération station %s échouée : %s", id_station, exc)
        self.refresh()
        parts = ["%d importée(s)" % imported]
        if restored:
            parts.append("%d restaurée(s)" % restored)
        if skipped:
            parts.append("%d ignorée(s) (déjà locale)" % skipped)
        if failed:
            parts.append("%d échec(s)" % failed)
        self.iface.messageBar().pushInfo("OccHab", "Récupération : %s." % ", ".join(parts))

    # -------------------------------------------------- saisie + géométrie
    def _new_station_draw(self, geom_type):
        """Créer une station en dessinant sa géométrie sur la carte."""
        self._capture_target = "new"
        self._start_capture(geom_type)

    def _new_station_no_geom(self):
        """Créer une station sans géométrie (à tracer plus tard)."""
        self._capture_target = "new"
        self._open_station_dialog(None, None)

    # ------------------------------------------ reprise de géométrie (couche)
    def _new_station_from_selection(self):
        """Créer une station à partir de la géométrie de l'entité sélectionnée."""
        wkt, geom_type, error = self._reprise_geometry()
        if error:
            QMessageBox.information(self, "OccHab", error)
            return
        self._capture_target = None
        self._open_station_dialog(wkt, geom_type, self._geo_metrics(wkt, geom_type))

    def _assign_selection_to_station(self):
        """Affecter la géométrie de l'entité sélectionnée à la station choisie."""
        station_id = self._selected_station_id()
        if station_id is None:
            QMessageBox.information(
                self, "OccHab",
                "Sélectionnez d'abord une station dans « Mes stations », puis "
                "relancez « Affecter à la station sélectionnée ».",
            )
            return
        wkt, geom_type, error = self._reprise_geometry()
        if error:
            QMessageBox.information(self, "OccHab", error)
            return
        self._update_geometry(station_id, wkt, geom_type, self._geo_metrics(wkt, geom_type))

    def _reprise_geometry(self):
        """(WKT EPSG:4326, geom_type, erreur) de l'entité sélectionnée active.

        Reprend la PREMIÈRE entité sélectionnée de la couche vectorielle active et
        la reprojette en EPSG:4326. Renvoie (None, None, message) si rien d'exploitable.
        """
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsGeometry,
            QgsProject,
            QgsVectorLayer,
            QgsWkbTypes,
        )

        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            return None, None, (
                "Activez d'abord une couche vectorielle contenant l'entité voulue."
            )
        features = layer.selectedFeatures()
        if not features:
            return None, None, (
                "Aucune entité sélectionnée dans la couche « %s »." % layer.name()
            )
        geom = QgsGeometry(features[0].geometry())
        if geom is None or geom.isEmpty():
            return None, None, "L'entité sélectionnée n'a pas de géométrie."
        # Type géré (point / ligne / polygone) ; enum QGIS scopé ou non.
        types = getattr(QgsWkbTypes, "GeometryType", QgsWkbTypes)
        geom_type = {
            types.PointGeometry: "point",
            types.LineGeometry: "line",
            types.PolygonGeometry: "polygon",
        }.get(geom.type())
        if geom_type is None:
            return None, None, (
                "Type de géométrie non géré (ni point, ni ligne, ni polygone)."
            )
        try:
            src_crs = layer.crs()
            if src_crs.isValid() and src_crs.authid() != "EPSG:4326":
                transform = QgsCoordinateTransform(
                    src_crs,
                    QgsCoordinateReferenceSystem("EPSG:4326"),
                    QgsProject.instance(),
                )
                geom.transform(transform)
            wkt = geom.asWkt()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Reprise de géométrie : reprojection échouée : %s", exc)
            return None, None, "Reprojection impossible : %s" % exc
        if not wkt:
            return None, None, "Géométrie vide après conversion."
        return wkt, geom_type, None

    def edit_geometry(self):
        """Éditer la géométrie enregistrée de la station (ou la numériser si absente)."""
        station_id = self._selected_station_id()
        if station_id is None:
            QMessageBox.information(self, "OccHab", "Sélectionnez une station.")
            return
        full = self.db.get_station(station_id)
        if full is None:
            return
        wkt, geom_type = full.get("geom"), full.get("geom_type")
        if wkt and geom_type:  # géométrie existante → édition des sommets
            self._edit_geom_station_id = station_id
            self._ensure_geom_editor().start(wkt, geom_type)
        else:  # pas de géométrie → numérisation d'une nouvelle (polygone par défaut)
            self._capture_target = station_id
            self._start_capture("polygon")

    def _ensure_geom_editor(self):
        if self._geom_editor is None:
            from .map_tools import GeometryEditController

            self._geom_editor = GeometryEditController(self.iface, self)
            self._geom_editor.edited.connect(self._on_geometry_edited)
            self._geom_editor.cancelled.connect(self._on_geometry_edit_cancelled)
        return self._geom_editor

    def _on_geometry_edited(self, wkt, geom_type):
        station_id = self._edit_geom_station_id
        self._edit_geom_station_id = None
        if station_id is not None:
            metrics = self._geo_metrics(wkt or None, geom_type)
            self._update_geometry(station_id, wkt or None, geom_type, metrics)

    def _on_geometry_edit_cancelled(self):
        self._edit_geom_station_id = None
        self.iface.messageBar().pushInfo("OccHab", "Édition de géométrie annulée.")

    def _ensure_capture(self):
        if self._capture is None:
            from .map_tools import GeometryCaptureController

            self._capture = GeometryCaptureController(self.iface, self)
            self._capture.captured.connect(self._on_geometry_captured)
            self._capture.cancelled.connect(self._on_capture_cancelled)
        return self._capture

    def _start_capture(self, geom_type):
        self._ensure_capture().start(geom_type)
        self.iface.messageBar().pushInfo(
            "OccHab",
            "Numérisez la station (accrochage QGIS actif, clic droit pour "
            "terminer, Échap pour annuler).",
        )

    def _on_geometry_captured(self, wkt, geom_type):
        target = self._capture_target
        self._capture_target = None
        metrics = self._geo_metrics(wkt or None, geom_type)
        if isinstance(target, int):
            self._update_geometry(target, wkt or None, geom_type, metrics)
        else:
            self._open_station_dialog(wkt or None, geom_type, metrics)

    def _on_capture_cancelled(self):
        self._capture_target = None
        self.iface.messageBar().pushInfo("OccHab", "Numérisation annulée.")

    def _update_geometry(self, station_id, wkt, geom_type, metrics=None):
        if not wkt:
            self.iface.messageBar().pushInfo("OccHab", "Géométrie vide, station inchangée.")
            return
        current = self.db.get_station(station_id)  # mémoriser l'ancienne géométrie
        fields = {
            "geom": wkt, "geom_type": geom_type, "sync_status": "pending",
            "prev_geom": current.get("geom") if current else None,
            "prev_geom_type": current.get("geom_type") if current else None,
        }
        for key in ("area", "altitude_min", "altitude_max"):
            if (metrics or {}).get(key) is not None:
                fields[key] = metrics[key]
        self.db.update_station(station_id, **fields)
        self.logger.info("Géométrie de la station %s mise à jour", station_id)
        self.refresh()

    def restore_previous_geometry(self):
        """Rétablir la géométrie précédente (échange courante ↔ précédente → réversible)."""
        station_id = self._selected_station_id()
        if station_id is None:
            QMessageBox.information(self, "OccHab", "Sélectionnez une station.")
            return
        full = self.db.get_station(station_id)
        if full is None:
            return
        prev = full.get("prev_geom")
        if not prev:
            self.iface.messageBar().pushInfo(
                "OccHab", "Aucune géométrie précédente à rétablir pour cette station."
            )
            return
        prev_type = full.get("prev_geom_type")
        metrics = self._geo_metrics(prev, prev_type)
        fields = {
            "geom": prev, "geom_type": prev_type, "sync_status": "pending",
            "prev_geom": full.get("geom"), "prev_geom_type": full.get("geom_type"),
        }
        for key in ("area", "altitude_min", "altitude_max"):
            if (metrics or {}).get(key) is not None:
                fields[key] = metrics[key]
        self.db.update_station(station_id, **fields)
        self.logger.info("Géométrie précédente rétablie (station %s)", station_id)
        self.refresh()
        self.iface.messageBar().pushInfo("OccHab", "Géométrie précédente rétablie.")

    def _geo_metrics(self, wkt, geom_type):
        """Surface (m², polygone) et altitude min/max (MNT serveur si connecté)."""
        metrics = {"area": None, "altitude_min": None, "altitude_max": None}
        if not wkt:
            return metrics
        if geom_type == "polygon":
            try:
                from qgis.core import (
                    QgsCoordinateReferenceSystem,
                    QgsDistanceArea,
                    QgsGeometry,
                    QgsProject,
                    QgsUnitTypes,
                )

                calc = QgsDistanceArea()
                calc.setSourceCrs(
                    QgsCoordinateReferenceSystem("EPSG:4326"),
                    QgsProject.instance().transformContext(),
                )
                calc.setEllipsoid(QgsProject.instance().ellipsoid() or "WGS84")
                area = calc.convertAreaMeasurement(
                    calc.measureArea(QgsGeometry.fromWkt(wkt)),
                    QgsUnitTypes.AreaUnit.AreaSquareMeters,
                )
                metrics["area"] = int(round(area))
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Surface non calculée : %s", exc)
        if self.client is not None and self.client.is_authenticated:
            try:
                from ..processing.geometry import wkt_to_geojson

                geojson = wkt_to_geojson(wkt)
                altitude = self.client.get_altitude(geojson) if geojson else None
                if isinstance(altitude, dict):
                    metrics["altitude_min"] = altitude.get("altitude_min")
                    metrics["altitude_max"] = altitude.get("altitude_max")
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Altitude non calculée : %s", exc)
        return metrics

    def shutdown(self):
        """Nettoyer au déchargement du plugin : capture/édition en cours + couches carte."""
        if self._map_filter_installed:
            try:
                self.iface.mapCanvas().viewport().removeEventFilter(self)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("removeEventFilter ignoré : %s", exc)
            self._map_filter_installed = False
        self._clear_server_prompt()
        if self._capture is not None:
            self._capture.cancel()
        if self._geom_editor is not None:
            self._geom_editor.cancel()
        self.layers.cleanup()
        self.server_layers.cleanup()

    def _open_station_dialog(self, geom_wkt, geom_type, metrics=None):
        dialog = StationDialog(
            self.config,
            geom_wkt=geom_wkt,
            geom_type=geom_type,
            geo_metrics=metrics,
            datasets=self._dataset_items(),
            station_nomenclatures=self._station_nomenclatures(),
            habitat_nomenclatures=self._habitat_nomenclatures(),
            station_defaults=self._station_defaults(),
            habitat_defaults=self._habitat_defaults(),
            abundance_cover_map=self._abundance_cover_map(),
            habref_search=self._habref_search_fn(),
            habref_typologies=self._habref_typologies(),
            observers=self._observers_items(),
            current_observer=self._current_user_observer(),
            user_names=self._user_names(),
            default_determiner=self._current_user_name(),
            parent=self,
        )
        if not dialog.exec():
            return
        station, habitats = dialog.get_result()
        observers = station.pop("_observers", [])
        try:
            station_id = self.db.create_station(**station)
            for habitat in habitats:
                self.db.add_habitat(id_station_local=station_id, **habitat)
            for obs in observers:
                self.db.add_observer(
                    station_id,
                    observer_name=obs.get("observer_name"),
                    id_role=obs.get("id_role"),
                )
            self.logger.info("Station %s créée (%d habitat(s))", station_id, len(habitats))
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Échec création station : %s", exc)
            QMessageBox.critical(self, "Erreur", "Création impossible : %s" % exc)
            return
        self.refresh()

    def edit_station(self):
        """Éditer la station sélectionnée dans le tableau (attributs + habitats)."""
        station_id = self._selected_station_id()
        if station_id is None:
            QMessageBox.information(self, "OccHab", "Sélectionnez une station.")
            return
        self._edit_station_by_id(station_id)

    def _edit_station_by_id(self, station_id):
        """Ouvrir le formulaire d'édition d'une station par son id local."""
        self._select_table_row(station_id)
        full = self.db.get_station(station_id)
        if full is None:
            return
        was_conflict = full.get("sync_status") == "conflict"
        dialog = StationDialog(
            self.config,
            station=full,
            datasets=self._dataset_items(),
            station_nomenclatures=self._station_nomenclatures(),
            habitat_nomenclatures=self._habitat_nomenclatures(),
            station_defaults=self._station_defaults(),
            habitat_defaults=self._habitat_defaults(),
            abundance_cover_map=self._abundance_cover_map(),
            habref_search=self._habref_search_fn(),
            habref_typologies=self._habref_typologies(),
            observers=self._observers_items(),
            current_observer=self._current_user_observer(),
            user_names=self._user_names(),
            default_determiner=self._current_user_name(),
            parent=self,
        )
        if not dialog.exec():
            return
        station, habitats = dialog.get_result()
        observers = station.pop("_observers", [])
        # L'éditeur devient updated_by ; created_by (créateur d'origine) reste inchangé.
        station["updated_by"] = station.pop("created_by", None)
        try:
            self.db.update_station(station_id, sync_status="pending", **station)
            self.db.replace_habitats(station_id, habitats)
            self.db.replace_observers(station_id, observers)
            self.logger.info(
                "Station %s modifiée (%d habitat(s))", station_id, len(habitats)
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Échec modification station %s : %s", station_id, exc)
            QMessageBox.critical(self, "Erreur", "Modification impossible : %s" % exc)
            return
        if was_conflict:
            # Conflit résolu « côté local » : oublier l'empreinte pour que la prochaine
            # synchro impose la version locale (sans re-détecter le conflit).
            self.db.set_server_snapshot(station_id, None)
        self.refresh()

    # --------------------------------------------------------- tableau
    def refresh(self):
        jdd = self.combo_jdd.currentData() if self.combo_jdd.isEnabled() else None
        all_stations = self.db.get_all_stations()
        stations = (
            [s for s in all_stations if s.get("id_dataset") == jdd]
            if jdd is not None else all_stations
        )
        # « Synchroniser » agit sur TOUTES les stations (tous JDD confondus).
        n_sync = sum(
            1 for s in all_stations if s.get("sync_status") in ("pending", "to_delete")
        )
        self.table.setRowCount(0)
        n_conflict = 0
        for station in stations:
            full = self.db.get_station(station["id"])
            habitats = full["habitats"] if full else []
            station["_nb_habitats"] = len(habitats)
            status = station.get("sync_status")
            if status == "conflict":
                n_conflict += 1
            row = self.table.rowCount()
            self.table.insertRow(row)
            item_hab = QTableWidgetItem(self._station_label(station, habitats))
            item_hab.setData(Qt.ItemDataRole.UserRole, station["id"])  # id local caché
            observers = station.get("observers_txt") or ""
            if observers:
                item_hab.setToolTip("Observateur(s) : %s" % observers)
            self.table.setItem(row, 0, item_hab)
            self.table.setItem(row, 1, QTableWidgetItem(station.get("date_min") or ""))
            self.table.setCellWidget(
                row, 2, self._status_pill(status, station.get("id_station"))
            )
        try:
            self.layers.refresh(stations)
        except Exception as exc:  # noqa: BLE001 - la carte ne doit pas casser la liste
            self.logger.warning("Couches carte non mises à jour : %s", exc)
        parts = ["%d locale(s)" % len(stations)]
        if n_conflict:
            parts.append("%d conflit(s)" % n_conflict)
        self.label_count.setText(" · ".join(parts))
        self.btn_sync.setText("Synchroniser (%d)" % n_sync if n_sync else "Synchroniser")
        self._on_selection_changed()
        self.logger.info("Liste rafraîchie : %d station(s)", len(stations))

    def zoom_to_stations(self):
        """Zoom adaptatif : station locale sélectionnée, sinon emprise du JDD.

        Avec une ligne sélectionnée dans « Mes stations (local) » → zoom sur sa
        géométrie. Sans sélection → emprise du JDD (stations serveur en priorité,
        sinon les stations locales).
        """
        station_id = self._selected_station_id()
        if station_id is not None:
            extent = self._station_extent_4326(station_id)
            if extent is not None and self._zoom_canvas_to_4326(extent):
                return
        extent = self.server_layers.extent() or self.layers.extent()
        if not self._zoom_canvas_to_4326(extent):
            self.iface.messageBar().pushInfo("OccHab", "Aucune géométrie à afficher.")

    def _station_extent_4326(self, station_id):
        """Emprise EPSG:4326 de la géométrie d'une station locale, ou None."""
        full = self.db.get_station(station_id)
        wkt = full.get("geom") if full else None
        if not wkt:
            return None
        from qgis.core import QgsGeometry

        geom = QgsGeometry.fromWkt(wkt)
        if geom is None or geom.isEmpty():
            return None
        rect = geom.boundingBox()
        if rect.width() == 0 and rect.height() == 0:  # point → petite marge (~50 m)
            rect.grow(0.0005)
        return rect

    def _zoom_canvas_to_4326(self, extent):
        """Zoomer le canevas sur une emprise EPSG:4326. False si emprise vide."""
        if extent is None or extent.isEmpty():
            return False
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsProject,
        )

        canvas = self.iface.mapCanvas()
        dest = canvas.mapSettings().destinationCrs()
        source = QgsCoordinateReferenceSystem("EPSG:4326")
        if dest.isValid() and dest.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(source, dest, QgsProject.instance())
            extent = transform.transformBoundingBox(extent)
        canvas.setExtent(extent)
        canvas.zoomByFactor(1.1)  # petite marge
        canvas.refresh()
        return True

    @staticmethod
    def _station_label(station, habitats):
        """Libellé lisible d'une station : son (premier) habitat + nombre."""
        if habitats:
            first = habitats[0].get("nom_cite") or (
                "cd_hab %s" % habitats[0].get("cd_hab")
            )
            extra = len(habitats) - 1
            return "%s (+%d)" % (first, extra) if extra > 0 else first
        return station.get("station_name") or "(station sans habitat)"

    def _selected_station_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _select_table_row(self, local_id):
        """Sélectionner dans le tableau la ligne d'une station (sync carte → dock)."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == local_id:
                self.table.selectRow(row)
                return

    # -------------------------------------------------- interaction carte
    def _install_map_interaction(self):
        """Ouvrir le formulaire d'une station cliquée sur la carte.

        Double-clic (n'importe quel outil, ex. « Sélectionner ») ou simple clic
        avec l'outil « Identifier des entités » : filtre d'événements sur le
        canevas. Tout est protégé pour ne jamais faire planter QGIS.
        """
        try:
            self.iface.mapCanvas().viewport().installEventFilter(self)
            self._map_filter_installed = True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Interaction carte non installée : %s", exc)

    def eventFilter(self, obj, event):
        try:
            from qgis.PyQt.QtCore import QEvent, QTimer

            etype = event.type()
            if etype in (
                QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease
            ) and event.button() == Qt.MouseButton.LeftButton:
                tool = self.iface.mapCanvas().mapTool()
                is_identify = bool(tool) and "identify" in type(tool).__name__.lower()
                # Identifier → simple clic ; autres outils (Sélectionner…) → double-clic.
                if (etype == QEvent.Type.MouseButtonRelease and is_identify) or (
                    etype == QEvent.Type.MouseButtonDblClick and not is_identify
                ):
                    pos = event.position() if hasattr(event, "position") else event.pos()
                    x, y = int(pos.x()), int(pos.y())
                    QTimer.singleShot(0, lambda: self._open_station_at(x, y))
        except Exception as exc:  # noqa: BLE001 - un filtre ne doit jamais planter QGIS
            self.logger.debug("Filtre carte : %s", exc)
        return super().eventFilter(obj, event)

    def _open_station_at(self, px, py):
        """Ouvrir la station locale située sous le pixel (px, py) du canevas."""
        try:
            from qgis.core import (
                QgsCoordinateReferenceSystem,
                QgsCoordinateTransform,
                QgsFeatureRequest,
                QgsProject,
                QgsRectangle,
            )

            canvas = self.iface.mapCanvas()
            point = canvas.getCoordinateTransform().toMapCoordinates(px, py)
            tol = canvas.mapUnitsPerPixel() * 6  # ~6 px de tolérance
            rect = QgsRectangle(
                point.x() - tol, point.y() - tol, point.x() + tol, point.y() + tol
            )
            canvas_crs = canvas.mapSettings().destinationCrs()
            if canvas_crs.isValid() and canvas_crs.authid() != "EPSG:4326":
                transform = QgsCoordinateTransform(
                    canvas_crs,
                    QgsCoordinateReferenceSystem("EPSG:4326"),
                    QgsProject.instance(),
                )
                rect = transform.transformBoundingBox(rect)
            for layer in self.layers.existing_layers():
                if layer.fields().indexOf("id") < 0:
                    continue
                for feature in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
                    value = feature["id"]
                    if value is not None:
                        self._edit_station_by_id(int(value))
                        return
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Ouverture depuis la carte échouée : %s", exc)

    # --------------------------------------------------------- stockage
    def _open_db_folder(self):
        folder = os.path.dirname(str(self.db.db_path))
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _backup_db(self):
        import shutil

        target, _ = QFileDialog.getSaveFileName(
            self, "Sauvegarder la base locale", "occhab_local_backup.db",
            "Base SQLite (*.db)",
        )
        if not target:
            return
        try:
            shutil.copy2(str(self.db.db_path), target)
        except OSError as exc:
            QMessageBox.critical(self, "Sauvegarde", "Échec : %s" % exc)
            return
        self.iface.messageBar().pushSuccess("OccHab", "Sauvegarde : %s" % target)

    def _export_geopackage(self):
        target, _ = QFileDialog.getSaveFileName(
            self, "Exporter en GeoPackage", "occhab_stations.gpkg",
            "GeoPackage (*.gpkg)",
        )
        if not target:
            return
        try:
            count = self.layers.export_geopackage(target)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Export GeoPackage échoué : %s", exc)
            QMessageBox.critical(self, "Export", "Échec : %s" % exc)
            return
        self.iface.messageBar().pushSuccess(
            "OccHab", "Export : %d station(s) → %s" % (count, target)
        )

    def _nomenclature_id_label_map(self):
        """{id_nomenclature: libellé} sur toutes les nomenclatures chargées."""
        mapping = {}
        for values in self.nomenclatures.values():
            for value in values:
                id_nom = value.get("id_nomenclature")
                if id_nom is not None:
                    mapping[id_nom] = (
                        value.get("label_default") or value.get("label_fr")
                        or value.get("mnemonique") or str(id_nom)
                    )
        return mapping

    def export_jdd_cartography(self):
        """Exporter la cartographie d'habitats du JDD (serveur) : 1 ligne / habitat."""
        if self.client is None or not self.client.is_authenticated:
            QMessageBox.information(self, "OccHab", "Connectez-vous à GeoNature d'abord.")
            return
        jdd = self.combo_jdd.currentData() if self.combo_jdd.isEnabled() else None
        if jdd is None:
            QMessageBox.information(
                self, "OccHab", "Choisissez d'abord un JDD précis (pas « Tous »)."
            )
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Exporter la cartographie du JDD", "cartographie_habitats.gpkg",
            "GeoPackage (*.gpkg)",
        )
        if not target:
            return
        try:
            fc = self.client.get_stations(params={"id_dataset": jdd}, geojson=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "OccHab", "Stations serveur non chargées : %s" % exc)
            return
        features = (fc.get("features") if isinstance(fc, dict) else None) or []
        ids = []
        for feature in features:
            props = feature.get("properties") or {}
            id_station = props.get("id_station") or feature.get("id")
            if id_station:
                ids.append(id_station)
        if not ids:
            QMessageBox.information(self, "OccHab", "Aucune station serveur pour ce JDD.")
            return

        from ..api.payload import parse_server_station
        from ..processing.export import flatten_cartography

        parsed, failed = [], 0
        for id_station in ids:
            try:
                parsed.append(parse_server_station(self.client.get_station(id_station)))
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.logger.warning("Station %s non exportée : %s", id_station, exc)
        if not parsed:
            QMessageBox.warning(self, "OccHab", "Aucune station récupérée pour l'export.")
            return

        nomenclature_map = self._nomenclature_id_label_map()
        role_map = dict(self._observers_items())
        habref_cache = {}

        def habref_label(cd_hab):
            if cd_hab is None:
                return None
            if cd_hab not in habref_cache:
                try:
                    data = self.client.get_habref(cd_hab)
                    habref_cache[cd_hab] = {
                        "nom": data.get("lb_hab_fr") or data.get("lb_hab_fr_complet"),
                        "code": data.get("lb_code"),
                    } if isinstance(data, dict) else None
                except Exception as exc:  # noqa: BLE001 - cd_hab absent → repli sur nom_cite
                    self.logger.warning("Libellé HABREF %s non résolu : %s", cd_hab, exc)
                    habref_cache[cd_hab] = None
            return habref_cache[cd_hab]

        rows = flatten_cartography(
            parsed,
            nomenclature_label=nomenclature_map.get,
            jdd_name=self.combo_jdd.currentText(),
            role_label=role_map.get,
            habref_label=habref_label,
        )
        try:
            written = self._write_cartography(target, rows)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Export cartographie échoué : %s", exc)
            QMessageBox.critical(self, "Export", "Échec : %s" % exc)
            return
        suffix = " (%d station(s) ignorée(s))" % failed if failed else ""
        self.iface.messageBar().pushSuccess(
            "OccHab",
            "Cartographie exportée : %d ligne(s) → %s%s" % (len(rows), written, suffix),
        )

    def _write_cartography(self, gpkg_path, rows):
        """Écrire les lignes en GeoPackage (+ Shapefile), une couche par type géom."""
        import os

        from qgis.PyQt.QtCore import QVariant
        from qgis.core import (
            QgsFeature,
            QgsField,
            QgsFields,
            QgsGeometry,
            QgsProject,
            QgsVectorFileWriter,
            QgsVectorLayer,
        )

        from ..processing.export import FIELDS, NUMERIC_FIELDS

        wkb = {"point": "Point", "line": "LineString", "polygon": "Polygon"}
        groups = {}
        for row in rows:
            geom_type = (row.get("_geom_type") or "").lower()
            if geom_type in wkb and row.get("_geom"):
                groups.setdefault(geom_type, []).append(row)
        if not groups:
            raise ValueError("Aucune géométrie exploitable à exporter.")

        def build_fields():
            fields = QgsFields()
            for name in FIELDS:
                qtype = QVariant.Double if name in NUMERIC_FIELDS else QVariant.String
                fields.append(QgsField(name, qtype))
            return fields

        context = QgsProject.instance().transformContext()
        base = os.path.splitext(gpkg_path)[0]
        outputs = []
        first = True
        for geom_type, group in groups.items():
            layer = QgsVectorLayer(
                "%s?crs=EPSG:4326" % wkb[geom_type],
                "cartographie_%s" % geom_type, "memory",
            )
            layer.dataProvider().addAttributes(list(build_fields()))
            layer.updateFields()
            features = []
            for row in group:
                feature = QgsFeature(layer.fields())
                feature.setGeometry(QgsGeometry.fromWkt(row["_geom"]))
                feature.setAttributes([row.get(name) for name in FIELDS])
                features.append(feature)
            layer.dataProvider().addFeatures(features)

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = "cartographie_%s" % geom_type
            options.actionOnExistingFile = (
                QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
                if first
                else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            )
            result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, gpkg_path, context, options
            )
            if result[0] != QgsVectorFileWriter.WriterError.NoError:
                raise RuntimeError(result[1])
            first = False
            outputs.append("%s:%s" % (os.path.basename(gpkg_path), geom_type))

            shp_path = "%s_%s.shp" % (base, geom_type)
            shp_options = QgsVectorFileWriter.SaveVectorOptions()
            shp_options.driverName = "ESRI Shapefile"
            shp_options.actionOnExistingFile = (
                QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
            )
            shp_result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, shp_path, context, shp_options
            )
            if shp_result[0] != QgsVectorFileWriter.WriterError.NoError:
                self.logger.warning(
                    "Shapefile %s non écrit : %s", shp_path, shp_result[1]
                )
            else:
                outputs.append(os.path.basename(shp_path))
        return ", ".join(outputs)

    def delete_selected(self):
        station_id = self._selected_station_id()
        if station_id is None:
            QMessageBox.information(self, "OccHab", "Sélectionnez une station.")
            return
        full = self.db.get_station(station_id)
        if full is None:
            return
        label = self._station_label(full, full.get("habitats", []))

        # Déjà marquée « à supprimer » → proposer d'annuler (réversible avant synchro).
        if full.get("sync_status") == "to_delete":
            if self._ask("Annuler la suppression", "Annuler la suppression de « %s » ?" % label):
                self.db.update_station(station_id, sync_status="synced")
                self.refresh()
            return

        if not full.get("id_station"):
            # Jamais synchronisée → suppression locale immédiate (c'est forcément à vous).
            if self._ask("Supprimer",
                         "Supprimer définitivement « %s » (non synchronisée) ?" % label):
                self.db.delete_station(station_id)
                self.refresh()
            return

        # Déjà sur le serveur : DEUX gestes distincts à ne pas confondre.
        #   • Retirer de la base LOCALE : n'affecte pas GeoNature (toujours possible,
        #     y compris pour une station d'un autre utilisateur).
        #   • Supprimer sur GeoNature : marque « à supprimer » (uniquement vos données).
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Supprimer")
        box.setText("« %s » est déjà enregistrée sur GeoNature." % label)
        info = (
            "« Retirer de ma base locale » enlève seulement la copie locale ; "
            "GeoNature n'est pas touché (vous pourrez la re-récupérer)."
        )
        if full.get("sync_status") == "pending":
            info += " ⚠ Vos modifications locales non synchronisées seront perdues."
        btn_local = box.addButton("Retirer de ma base locale", QMessageBox.ButtonRole.AcceptRole)
        btn_server = None
        if full.get("mine", 1):
            info += (
                "\n« Supprimer sur GeoNature » la marquera pour suppression à la "
                "prochaine synchronisation (réversible d'ici là)."
            )
            btn_server = box.addButton("Supprimer sur GeoNature", QMessageBox.ButtonRole.DestructiveRole)
        else:
            info += (
                "\nCette station n'a pas été créée par vous : vous ne pouvez pas la "
                "supprimer de GeoNature."
            )
        btn_cancel = box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        box.setInformativeText(info)
        box.setDefaultButton(btn_cancel)  # éviter un geste destructeur par inadvertance
        box.setEscapeButton(btn_cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_local:
            self.db.delete_station(station_id)
            self.refresh()
        elif btn_server is not None and clicked is btn_server:
            self.db.update_station(station_id, sync_status="to_delete")
            self.refresh()

    def _ask(self, title, message):
        """Confirmation Oui/Non (défaut Non, pour éviter une validation par inadvertance)."""
        return (
            QMessageBox.question(self, title, message,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            == QMessageBox.StandardButton.Yes
        )

    # ----------------------------------------------------- synchronisation
    _DELETE_THRESHOLD = 3  # au-delà : confirmation renforcée

    def synchronize(self):
        if self.client is None or not self.client.is_authenticated:
            QMessageBox.information(
                self, "OccHab", "Connectez-vous à GeoNature avant de synchroniser."
            )
            return

        from ..api.payload import (
            build_station_payload,
            extract_id_station,
            parse_server_station,
            server_fingerprint,
        )
        from ..processing.geometry import wkt_to_geojson

        to_delete = self.db.get_all_stations(sync_status="to_delete")
        pending = self.db.get_pending_stations()
        if not to_delete and not pending:
            self.iface.messageBar().pushInfo("OccHab", "Rien à synchroniser.")
            return

        # --- Suppressions (avec garde-fous) ---
        deleted = del_failed = 0
        if to_delete and self._confirm_deletions(to_delete):
            for station in to_delete:
                try:
                    if station.get("id_station"):
                        self.client.delete_station(station["id_station"])
                    self.db.delete_station(station["id"])
                    deleted += 1
                except Exception as exc:  # noqa: BLE001
                    del_failed += 1
                    self.logger.error(
                        "Suppression station %s échouée : %s",
                        station.get("id_station"), exc,
                    )

        # --- Créations / mises à jour ---
        ok = failed = conflicts = 0
        tech_default = self._habitat_defaults().get("technique")  # « In situ » (cd 1)
        for station in pending:
            full = self.db.get_station(station["id"])
            if full is None:
                continue
            # Habitats saisis hors-ligne : technique restée None → défaut « In situ ».
            if tech_default:
                for hab in full["habitats"]:
                    if not hab.get("id_nomenclature_collection_technique"):
                        hab["id_nomenclature_collection_technique"] = tech_default
            # Conflit : le serveur a-t-il changé depuis notre dernière synchro de CETTE
            # station ? (empreinte mémorisée ≠ empreinte serveur actuelle). Fail-open :
            # si le contrôle échoue (réseau…), on synchronise quand même.
            if full.get("id_station") and full.get("server_snapshot"):
                try:
                    current = self.client.get_station(full["id_station"])
                    if server_fingerprint(*parse_server_station(current)) != full[
                        "server_snapshot"
                    ]:
                        self.db.update_station(station["id"], sync_status="conflict")
                        conflicts += 1
                        continue  # ne pas écraser la version serveur
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning(
                        "Contrôle de conflit ignoré (station %s) : %s",
                        full["id_station"], exc,
                    )
            geojson = wkt_to_geojson(full.get("geom")) if full.get("geom") else None
            payload = build_station_payload(
                full, full["habitats"], full["observers"], geojson
            )
            try:
                if full.get("id_station"):  # déjà synchronisée → mise à jour
                    self.client.update_station(full["id_station"], payload)
                    id_station = full["id_station"]
                else:  # première synchro → création
                    response = self.client.create_station(payload)
                    id_station = extract_id_station(response)
                # Rafraîchir l'empreinte serveur (best-effort) pour les conflits futurs.
                snapshot = None
                try:
                    snapshot = server_fingerprint(
                        *parse_server_station(self.client.get_station(id_station))
                    )
                except Exception:  # noqa: BLE001
                    snapshot = None
                self.db.mark_station_synced(
                    station["id"], id_station, server_snapshot=snapshot
                )
                ok += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.logger.error("Station %s non synchronisée : %s", station["id"], exc)

        parts = []
        if ok or failed:
            parts.append("%d envoyée(s), %d échec(s)" % (ok, failed))
        if deleted or del_failed:
            parts.append("%d supprimée(s), %d échec(s)" % (deleted, del_failed))
        if conflicts:
            parts.append("%d conflit(s)" % conflicts)
        message = " | ".join(parts) or "rien à faire"
        status = "success" if failed == 0 and del_failed == 0 else "partial"
        self.db.log_sync("upload", status, message, ok + deleted)
        self.logger.info("Synchronisation : %s", message)
        if conflicts:
            self.iface.messageBar().pushWarning(
                "OccHab",
                "Synchronisation : %s. %d station(s) modifiée(s) aussi sur GeoNature : "
                "ré-éditez-la puis resynchronisez pour imposer votre version, ou "
                "« Récupérer du serveur » pour prendre la version serveur."
                % (message, conflicts),
            )
        else:
            self.iface.messageBar().pushInfo("OccHab", "Synchronisation : %s." % message)
        self.refresh()
        self._load_server_stations()  # recharger le contexte serveur (données à jour)

    def _confirm_deletions(self, to_delete):
        """Confirmer la suppression serveur : nombre + libellés, puis seuil renforcé."""
        labels = []
        for station in to_delete:
            full = self.db.get_station(station["id"])
            labels.append(self._station_label(station, full["habitats"] if full else []))
        count = len(labels)
        listing = "\n".join("• %s" % lbl for lbl in labels[:15])
        if count > 15:
            listing += "\n… (+%d)" % (count - 15)
        if not self._ask(
            "Suppression sur GeoNature",
            "%d station(s) vont être définitivement supprimées de GeoNature :\n\n"
            "%s\n\nConfirmer ?" % (count, listing),
        ):
            return False
        if count > self._DELETE_THRESHOLD:
            text, ok = QInputDialog.getText(
                self,
                "Confirmation renforcée",
                "Suppression de %d stations. Tapez SUPPRIMER (en majuscules) "
                "pour confirmer :" % count,
            )
            if not ok or text.strip() != "SUPPRIMER":
                self.iface.messageBar().pushInfo("OccHab", "Suppression annulée.")
                return False
        return True
