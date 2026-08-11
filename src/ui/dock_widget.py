# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dock principal du plugin OccHab : connexion, saisie et synchronisation."""
import os
import re

from qgis.PyQt.QtCore import QItemSelection, QItemSelectionModel, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QApplication,
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
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..database.sqlite_local import BROUILLON, VALIDE, OccHabDatabase
from ..processing import correspondances as corresp
from ..processing.duplicate import habitat_reprise, paste_fields, station_template
from ..processing.geometry import CrsIndetermine, wkt_en_degres_plausibles
from .connection_dialog import ConnectionDialog
from .flow_layout import widget_reflowable
from .station_dialog import StationDialog
from .station_form import current_user
from .export_layers import ExportLayerManager
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


#: Champs portant un NOM d'habitat dans une réponse HABREF, du plus direct au
#: plus détourné. `lb_code` n'y est pas : un code dans une colonne « Habitat »
#: n'apprend rien, et le `cd_hab` est déjà dans la colonne d'à côté. Mieux vaut
#: une case vide, qui se voit et s'explique, qu'un code qui se fait passer pour
#: un nom.
_CHAMPS_LIBELLE_HABREF = ("lb_hab_fr", "lb_hab_fr_complet", "lb_nom")
#: Code HABREF en tête du nom cité, que l'autocomplétion pose sous la forme
#: « 6.0.1.0.2 - Brachypodio rupestris-Centaureion nemoralis ».
_CODE_EN_TETE = re.compile(r"^\s*([A-Za-z0-9][\w.]*)\s+-\s+")
#: Un « libellé » qui n'est qu'un code : chiffres, lettres et points, sans espace.
_CODE_SEUL = re.compile(r"^[A-Za-z0-9][\w.]*$")


def _libelle_de_fiche(fiche):
    """Nom d'habitat dans une réponse HABREF, quelle que soit sa forme.

    L'autocomplétion ne rend pas les mêmes champs que la fiche : elle donne
    `search_name`, qui vaut « code - nom ». On en retire le code plutôt que de
    se rabattre sur `lb_code`, qui ferait afficher « 6.0.1.0.2 » dans une
    colonne intitulée « Habitat ».
    """
    if isinstance(fiche, dict) and isinstance(fiche.get("data"), dict):
        fiche = fiche["data"]  # certaines instances enveloppent la réponse
    if not isinstance(fiche, dict):
        return ""
    for champ in _CHAMPS_LIBELLE_HABREF:
        valeur = fiche.get(champ)
        if isinstance(valeur, str) and valeur.strip():
            return valeur.strip()
    # `nom_habref` et non `_sans_code` : l'autocomplétion répète le nom avant
    # les auteurs (« Cynosurion cristati Cynosurion cristati Tüxen 1947 »), et
    # c'est ce doublon qui s'afficherait dans la colonne.
    return corresp.nom_habref(fiche.get("search_name"))


def _code_habref(nom_cite):
    """Code lu en tête du nom cité (« 6.0.1.0.2 - … »), ou None."""
    trouve = _CODE_EN_TETE.match(nom_cite or "")
    return trouve.group(1) if trouve else None


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
        # Créée avec le menu « Nouvelle station », donc après le branchement du
        # signal de sélection du tableau : déclarée ici pour rester interrogeable.
        self.action_duplicate = None
        # Action « nouvelle station avec les renseignements copiés », créée avec
        # le menu : elle reste grisée tant que rien n'a été copié. Le collage,
        # lui, est proposé par le menu contextuel, reconstruit à chaque clic.
        self.action_new_from_clipboard = None
        # Renseignements copiés depuis une station (modèle sans identité ni
        # géométrie, cf. `processing.duplicate`). Session QGIS seulement : coller
        # sur des stations d'une campagne terminée n'aurait aucun sens.
        self._clipboard = None
        self._clipboard_label = ""
        self.nomenclatures = {}
        self.default_nomenclatures = {}
        self.typologies = []
        self.observers = []
        self.layers = StationLayerManager(self.logger)
        self.layers.add_selection_listener(self._on_map_selection_changed)
        self._table_dialog = None  # table attributaire ouverte (non modale)
        self.server_layers = ServerStationLayerManager(
            str(config.user_config_dir / "server_stations.geojson"), self.logger
        )
        # Couches d'export : un fichier par export chargé, dans le dossier de
        # configuration — plusieurs périodes doivent pouvoir coexister.
        self.export_layers = ExportLayerManager(config.user_config_dir, self.logger)
        self._capture = None
        self._capture_target = None  # None/"new" = nouvelle station ; int = id station à re-géométrer
        self._duplicate_source = None  # station à copier pour la création en cours
        # Dates de la dernière saisie, mémorisées pour la session QGIS seulement
        # (les observateurs, eux, sont persistés dans la configuration).
        self._session_dates = None
        self._geom_editor = None
        self._edit_geom_station_id = None
        self._map_filter_installed = False
        self._server_prompt = None
        self._occhab_layers_notice_shown = False
        self._build_ui()
        self._install_map_interaction()
        self._oublier_ancien_cache_habref()
        self.refresh()
        self._reconnecter()

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
        # Libellé long : sans cela il impose sa largeur au panneau entier.
        self.check_only_mine.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
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
        self.action_restore_geom = geom_menu.addAction(
            "Rétablir la géométrie précédente", self.restore_previous_geometry
        )
        self.btn_geom.setMenu(geom_menu)
        self.btn_geom.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_zoom = self._action_button(
            "Zoom", "/mActionZoomToSelected.svg",
            "Zoomer sur la station sélectionnée ; sans sélection, sur l'emprise du JDD.",
        )
        self.btn_zoom.clicked.connect(self.zoom_to_stations)
        # Toujours actif : la table ne porte pas sur la sélection du tableau.
        self.btn_table = self._action_button(
            "Tableau", "/mActionOpenTable.svg",
            "Voir et modifier stations et habitats en nombre (une ligne par habitat).",
        )
        self.btn_table.clicked.connect(self.open_attribute_table)
        self.btn_delete = self._action_button(
            "Supprimer", "/mActionDeleteSelected.svg",
            "Supprimer la station sélectionnée.",
        )
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_delete.setStyleSheet("QToolButton { color: #b23125; }")
        # Disposition qui replie : une QHBoxLayout aurait imposé sa largeur
        # (547 px mesurés) au panneau entier et fait couper le contenu dès que
        # le dock est rétréci. Les boutons gardent ici leurs libellés et passent
        # à la ligne. « Supprimer » perd sa mise à l'écart par un ressort — sa
        # couleur rouge reste sa marque distinctive.
        layout.addWidget(widget_reflowable(
            [self.btn_edit, self.btn_geom, self.btn_zoom, self.btn_table,
             self.btn_delete],
            spacing=3,
        ))

        self.table = QTableWidget(0, 4)
        # « Statut » = où en est le travail ; « synchro » = où en est l'envoi.
        # Deux questions distinctes, nommées toutes les deux dans l'en-tête.
        self.table.setHorizontalHeaderLabels(
            ["id_station", "Habitat(s)", "Date", "Statut · synchro"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Multi-sélection (Ctrl/Maj) pour supprimer plusieurs stations d'un coup.
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
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
            "Copier la ou les entités sélectionnées d'une autre couche",
            self._new_station_from_selection,
        )
        act_reuse_new.setToolTip(
            "Sélectionnez une ou plusieurs entités dans une autre couche, puis "
            "choisissez ceci. Plusieurs entités → une station par entité, "
            "métadonnées communes saisies une seule fois."
        )
        new_menu.addSeparator()
        self.action_duplicate = new_menu.addAction(
            "Dupliquer la station sélectionnée", self.duplicate_station
        )
        self.action_duplicate.setToolTip(
            "Reprend le JDD, les dates, les observateurs, les attributs et les "
            "habitats de la station sélectionnée ; la géométrie est à dessiner."
        )
        self.action_new_from_clipboard = new_menu.addAction(
            "Dessiner un polygone avec les renseignements copiés",
            self._new_station_from_clipboard,
        )
        self.action_new_from_clipboard.setToolTip(
            "Utilise les renseignements mis de côté par « Copier les "
            "renseignements » (clic droit sur une station) : ils restent "
            "disponibles pour autant de nouvelles stations que voulu."
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
        import_menu.setToolTipsVisible(True)
        import_menu.addAction("Depuis la carte (sélection)…", self.import_server_stations)
        import_menu.addAction("Chercher une station…", self.open_server_picker)
        self.btn_import.setMenu(import_menu)
        layout.addWidget(self.btn_import)

        # Footer : où sont stockées les données locales + sauvegarde/export
        footer = QHBoxLayout()
        db_path = str(self.db.db_path)
        self.label_db = QLabel("Base locale : %s" % os.path.basename(db_path))
        self.label_db.setToolTip(db_path)
        # Sans cela ce libellé impose sa largeur entière au panneau (400 px) et
        # fait couper le pied dès qu'on rétrécit le dock. Le chemin complet reste
        # dans l'infobulle.
        self.label_db.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
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
        menu.addSeparator()
        menu.addAction(
            "Nettoyer les stations synchronisées anciennes…",
            self._purge_old_synced_stations,
        )
        action_libelles = menu.addAction(
            "Compléter les libellés de correspondance…",
            self._completer_libelles_correspondance,
        )
        action_libelles.setToolTip(
            "Les correspondances arbitrées avant la 0.9.1 n'ont que leur code : "
            "une carte chargée dans cette typologie affiche « C1.32 » au lieu du "
            "nom de l'habitat. Cette action demande les libellés manquants au "
            "référentiel et les inscrit dans les habitats concernés."
        )
        action_habref = menu.addAction(
            "Recharger les libellés HABREF", self._recharger_libelles_habref
        )
        action_habref.setToolTip(
            "Oublier les libellés déjà obtenus du référentiel. Ils seront "
            "redemandés à la prochaine ouverture du tableau — utile si un "
            "habitat a changé de nom dans HABREF."
        )
        btn_storage.setMenu(menu)
        footer.addWidget(btn_storage)

        # Faire une carte, en deux temps : charger la couche, puis composer la
        # planche. Ces deux actions se suivent et n'ont rien à voir avec
        # « Récupérer une station », qui rapatrie des données ÉDITABLES dans la
        # base locale — un export est une couche de consultation, en lecture
        # seule, et une planche n'est même plus de la donnée.
        btn_carte = QPushButton("Cartographier…")
        btn_carte.setToolTip(
            "Charger une couche d'habitats depuis le serveur, puis en tirer une "
            "planche imprimable."
        )
        menu_carte = QMenu(btn_carte)
        menu_carte.setToolTipsVisible(True)
        act_export = menu_carte.addAction(
            "Charger un export du serveur (couche)…", self.load_server_export
        )
        act_export.setToolTip(
            "Charge un export du module Exports de GeoNature (données "
            "consolidées, libellés résolus) en couche QGIS lecture seule, "
            "filtrable par jeu de données et par période, avec une couleur par "
            "habitat."
        )
        act_planche = menu_carte.addAction(
            "Créer une mise en page…", self.create_print_layout
        )
        act_planche.setToolTip(
            "Composer une planche dans QGIS à partir d'un gabarit de l'ANA : "
            "bandeau, logo, légende et échelle déjà en place."
        )
        btn_carte.setMenu(menu_carte)
        footer.addWidget(btn_carte)
        layout.addLayout(footer)

        # Ascenseur : le panneau peut être plus haut que le dock ; sans scroll, le
        # bas (section Serveur, pied) se ferait couper sur un dock court.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Filet de sécurité : sous cette largeur, un ascenseur horizontal apparaît
        # au lieu de couper le contenu. Au-dessus, tout doit tenir de lui-même —
        # c'est le rôle de la barre d'actions repliable et des libellés élidables.
        container.setMinimumWidth(220)
        scroll.setWidget(container)
        self.setWidget(scroll)
        self._update_conn_summary()
        self._on_selection_changed()

    #: Mémorise l'état précédent pour ne replier le bloc qu'à la TRANSITION vers
    #: « connecté » : sans cela, un simple rafraîchissement refermerait le bloc
    #: sous les doigts de qui vient de l'ouvrir pour changer de serveur.
    _etait_connecte = False

    def _maj_bouton_conn(self):
        """Le libellé décrit l'ACTION du clic, jamais l'état courant.

        Il était posé à trois endroits différents ; `_update_conn_summary`, lui,
        rouvrait le bloc sans y toucher. À la reconnexion on se retrouvait donc
        avec un bloc ouvert et un bouton « changer », soit l'inverse de ce que le
        clic allait faire. Il se déduit désormais de la visibilité réelle.
        """
        self.btn_conn_toggle.setText(
            "replier" if self.conn_details.isVisible() else "changer"
        )

    def _toggle_conn_details(self):
        """Afficher / masquer les détails de connexion (divulgation progressive)."""
        self.conn_details.setVisible(not self.conn_details.isVisible())
        self._maj_bouton_conn()

    def _collapse_conn_details(self):
        """Replier le bloc connexion (une fois le JDD choisi)."""
        self.conn_details.setVisible(False)
        self._maj_bouton_conn()

    def _update_conn_summary(self):
        """Résumé compact connexion + JDD, et repli du bloc devenu inutile."""
        connecte = self.client is not None and self.client.is_authenticated
        if connecte:
            jdd = self.combo_jdd.currentText() if self.combo_jdd.count() else "—"
            self.label_conn.setText("✓ %s  ·  %s" % (self._user_label or "Connecté", jdd))
            self.btn_conn_toggle.setVisible(True)
            # Replier à la connexion, mais SEULEMENT si un JDD est déterminé :
            # sans JDD il n'y a rien à faire d'autre que d'en choisir un, et le
            # sélecteur doit rester sous les yeux. Depuis que le JDD mémorisé est
            # restauré, le cas courant est justement « déjà déterminé » — d'où un
            # bloc qui restait ouvert alors qu'il n'avait plus lieu d'être.
            if not self._etait_connecte and self.combo_jdd.currentData() is not None:
                self.conn_details.setVisible(False)
        else:
            self.label_conn.setText("● Non connecté")
            self.conn_details.setVisible(True)
            self.btn_conn_toggle.setVisible(False)
        self._etait_connecte = connecte
        self._maj_bouton_conn()

    def _on_selection_changed(self):
        """Activer la barre d'action seulement quand une station est sélectionnée."""
        self._maj_barre_action()
        # Tableau → carte. Le verrou côté couches empêche le retour en boucle.
        try:
            self.layers.select_stations(self._selected_station_ids())
        except Exception as exc:  # noqa: BLE001 - la carte ne doit pas casser la liste
            self.logger.debug("Sélection carte non appliquée : %s", exc)

    def _maj_barre_action(self):
        """Activer/désactiver les actions selon la sélection, sans toucher la carte."""
        station_id = self._selected_station_id()
        has = station_id is not None
        for btn in (self.btn_edit, self.btn_geom, self.btn_delete):
            btn.setEnabled(has)
        if self.action_duplicate is not None:
            self.action_duplicate.setEnabled(has)
        if self.action_new_from_clipboard is not None:
            self.action_new_from_clipboard.setEnabled(self._clipboard is not None)
        # « Rétablir la géométrie précédente » : grisé s'il n'y a rien à rétablir.
        has_prev = False
        if has:
            full = self.db.get_station(station_id)
            has_prev = bool(full and full.get("prev_geom"))
        self.action_restore_geom.setEnabled(has_prev)

    def _on_map_selection_changed(self):
        """Carte → tableau : refléter dans la liste ce qui est sélectionné sur la carte."""
        ids = set(self.layers.selected_station_ids())
        modele = self.table.selectionModel()
        if modele is None:
            return
        selection = QItemSelection()
        derniere_colonne = self.table.columnCount() - 1
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) in ids:
                selection.select(
                    self.table.model().index(row, 0),
                    self.table.model().index(row, derniere_colonne),
                )
        # `blockSignals` : sans lui, la sélection reposée relancerait
        # `_on_selection_changed`, qui réécrirait la sélection carte.
        self.table.blockSignals(True)
        try:
            modele.select(
                selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )
        finally:
            self.table.blockSignals(False)
        self._maj_barre_action()

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
        # Ne ramener la sélection à une seule ligne que si l'on clique HORS de
        # la sélection courante : sans cela, un clic droit sur un lot choisi au
        # Ctrl/Maj le défaisait, et « coller sur N stations » ne visait plus
        # qu'une ligne.
        if index.row() not in {i.row() for i in self.table.selectedIndexes()}:
            self.table.selectRow(index.row())
        menu = QMenu(self.table)
        menu.setToolTipsVisible(True)
        menu.addAction("Éditer", self.edit_station)
        menu.addAction("Dupliquer", self.duplicate_station)
        menu.addSeparator()
        copier = menu.addAction("Copier les renseignements", self.copy_station_fields)
        copier.setToolTip(
            "Met de côté JDD, dates, observateurs, attributs et habitats de "
            "cette station, pour les coller sur d'autres."
        )
        selection = self._selected_station_ids()
        libelle = "Coller les renseignements"
        if len(selection) > 1:
            libelle += " sur %d stations" % len(selection)
        coller = menu.addAction(libelle, self.paste_station_fields)
        coller.setEnabled(self._clipboard is not None)
        coller.setToolTip(
            "Écrase les renseignements des stations sélectionnées par ceux de "
            "« %s ». Géométries, noms et statuts conservés." % self._clipboard_label
            if self._clipboard is not None
            else "Copiez d'abord les renseignements d'une station."
        )
        menu.addSeparator()
        geom = menu.addMenu("Modifier la géométrie")
        geom.addAction("Redessiner / éditer sur la carte", self.edit_geometry)
        geom.addAction(
            "Copier l'entité sélectionnée d'une autre couche", self._assign_selection_to_station
        )
        geom.addSeparator()
        restore_act = geom.addAction(
            "Rétablir la géométrie précédente", self.restore_previous_geometry
        )
        full = self.db.get_station(self._selected_station_id())
        restore_act.setEnabled(bool(full and full.get("prev_geom")))
        menu.addAction("Zoom", self.zoom_to_stations)
        menu.addSeparator()
        menu.addAction("Supprimer", self.delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # (glyphe, libellé, couleur du texte, fond, bordure) — état de SYNCHRO.
    _PILL_STYLES = {
        # Vocabulaire aligné sur le bouton « Synchroniser » : « envoyée » aurait
        # introduit un second mot pour la même chose.
        "synced": ("✓", "Synchronisée", "#12579f", "#e6effb", "#bcdcf5"),
        "pending": ("↑", "À synchroniser", "#8a4d02", "#fbeedb", "#f0d6ac"),
        "conflict": ("▲", "Conflit", "#b23125", "#fbe4e0", "#f2c4bc"),
        "to_delete": ("✕", "À supprimer", "#566070", "#eceef1", "#d5d9df"),
    }
    # État MÉTIER (brouillon / validé), distinct de l'état de synchro. Teintes
    # volontairement éloignées de celles de la synchro : deux familles de couleurs
    # pour deux questions différentes.
    _PILL_VALIDATION = {
        BROUILLON: ("✎", "Brouillon", "#455a64", "#eceff1", "#cfd8dc"),
        VALIDE: ("✔", "Validée", "#1b5e20", "#e7f3e8", "#c3e0c6"),
    }

    def _status_pill(self, station):
        """Deux pastilles EMPILÉES : état métier, puis état de synchronisation.

        Les deux tenaient sur une seule ligne, la synchro réduite à un glyphe de
        la couleur du statut — donc illisible. Chacune retrouve ici sa couleur et
        son libellé. On empile plutôt qu'on juxtapose : dans un dock ancré, la
        largeur est la ressource rare, la hauteur ne l'est pas.
        """
        conteneur = QWidget()
        conteneur.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        boite = QVBoxLayout(conteneur)
        boite.setContentsMargins(4, 2, 4, 2)
        boite.setSpacing(2)
        validation = station.get("validation_status") or BROUILLON
        boite.addWidget(self._chip(
            *self._PILL_VALIDATION.get(validation, self._PILL_VALIDATION[BROUILLON])
        ))
        boite.addWidget(self._chip(
            *self._PILL_STYLES.get(
                station.get("sync_status"), self._PILL_STYLES["pending"]
            ),
            leger=True,
        ))
        return conteneur

    @staticmethod
    def _chip(glyph, label, fg, bg, border, leger=False):
        """Pastille « couleur + icône + texte » (chip au fond OPAQUE).

        Fond opaque : le chip reste lisible même quand la ligne est sélectionnée
        (surlignage bleu par-dessous). `leger` distingue la synchro, secondaire,
        de l'état métier.
        """
        widget = QLabel("%s %s" % (glyph, label))
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        widget.setStyleSheet(
            "QLabel { color: %s; background-color: %s; border: 1px solid %s;"
            " border-radius: 8px; padding: 0px 7px; font-weight: %s; }"
            % (fg, bg, border, "500" if leger else "700")
        )
        return widget

    # ------------------------------------------------------- connexion
    #: Reconnexion silencieuse à l'ouverture. Le mot de passe n'est nulle part
    #: dans le plugin : il vit dans le gestionnaire d'authentification de QGIS,
    #: qui le chiffre. Seuls l'URL et l'identifiant de configuration sont
    #: mémorisés (cf. `connection_dialog`). Rouvrir QGIS ne perdait donc que le
    #: JETON de session — et obligeait à refaire le tour du dialogue pour
    #: retrouver des identifiants que la machine avait déjà.
    CLE_RECONNEXION = "geonature.reconnexion_auto"

    def _reconnecter(self):
        """Reprendre la session GeoNature si QGIS peut relire les identifiants.

        Trois garde-fous, parce qu'un plugin qui parle au réseau à l'ouverture
        de QGIS se fait vite détester :

        - **rien sans mot de passe principal déjà donné.** Lire une
          configuration d'authentification le réclame ; le demander de nous-même
          au démarrage ferait surgir une fenêtre que personne n'a appelée. S'il
          n'est pas encore saisi, on ne tente rien : le bouton « Connexion »
          reste là, et c'est lui qui le demandera, au moment choisi ;
        - **aucun message en cas d'échec.** Hors ligne — le cas d'usage même de
          cette extension — la tentative échoue, et c'est normal : le plugin
          démarre déconnecté, comme avant ;
        - **désactivable** par `geonature.reconnexion_auto = false`.
        """
        if self.client is not None:
            return
        if not self.config.get(self.CLE_RECONNEXION, True):
            return
        api_url = self.config.get("geonature.api_url")
        authcfg = self.config.get("geonature.authcfg")
        if not api_url or not authcfg:
            return
        if not self._mot_de_passe_principal_disponible():
            self.logger.debug(
                "Reconnexion différée : mot de passe principal QGIS non saisi."
            )
            return

        from .connection_dialog import ConnectionDialog, libelle_utilisateur

        login, password = ConnectionDialog.credentials_from_authcfg(authcfg)
        if not login:
            return
        try:
            from ..api.geonature_client import GeoNatureAPIClient

            client = GeoNatureAPIClient(
                api_url, verify_ssl=bool(self.config.get("geonature.verify_ssl", True))
            )
            client.login(
                login, password,
                id_application=int(self.config.get("geonature.id_application", 0) or 0),
            )
        except Exception as exc:  # noqa: BLE001 - hors ligne : on reste déconnecté
            self.logger.info("Reconnexion automatique impossible : %s", exc)
            return

        self.client = client
        self._user_label = libelle_utilisateur(client.user)
        self.logger.info("Reconnecté à %s en tant que %s", api_url, self._user_label)
        self._load_datasets()
        self._load_reference_data()
        self._update_conn_summary()

    @staticmethod
    def _mot_de_passe_principal_disponible():
        """QGIS peut-il relire ses configurations sans rien demander ?"""
        try:
            from qgis.core import QgsApplication

            manager = QgsApplication.authManager()
            return bool(manager) and manager.masterPasswordIsSet()
        except Exception:  # noqa: BLE001
            return False

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
            # Restaurer le JDD choisi précédemment. Il est enregistré à chaque
            # changement (`_on_jdd_changed`) mais n'était jamais relu : toute
            # reconnexion basculait sur le premier JDD de la liste, et si les
            # stations locales étaient ailleurs, le panneau paraissait VIDE.
            memorise = self.config.get("id_dataset")
            index = self.combo_jdd.findData(memorise) if memorise is not None else -1
            self.combo_jdd.setCurrentIndex(index if index > 0 else 1)
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

    #: Codes interrogés au plus à chaque ouverture de la table. Le référentiel
    #: répond un habitat par requête : sans plafond, une première ouverture sur
    #: un gros jeu de données figerait QGIS le temps de deux cents allers-retours.
    #: Les manquants seront pris à l'ouverture suivante, le cache s'épaississant
    #: à chaque fois.
    LIBELLES_PAR_OUVERTURE = 40

    def _oublier_ancien_cache_habref(self):
        """Reprendre le cache des libellés que la 0.7.1 gardait dans la config.

        Il n'avait rien à y faire — un fichier de préférences n'est pas un cache
        de données — et il a pu retenir des valeurs bancales, un code là où on
        attendait un nom. On le verse dans la base, sans les valeurs douteuses,
        et on retire la clé.
        """
        ancien = self.config.get("habref.libelles")
        if not isinstance(ancien, dict):
            return
        recuperables = {
            cle: valeur for cle, valeur in ancien.items()
            if isinstance(valeur, str) and valeur.strip()
            # Un libellé qui n'est qu'un code — « 6.0.1.0.2 » — vient d'un repli
            # qui n'aurait pas dû exister : mieux vaut le redemander.
            and not _CODE_SEUL.match(valeur.strip())
        }
        try:
            repris = self.db.enregistrer_libelles_habref(recuperables)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Reprise du cache HABREF impossible : %s", exc)
            return
        self.config.set("habref.libelles", None)
        self.logger.info(
            "Cache HABREF déplacé de la configuration vers la base : %d repris, "
            "%d écartés.", repris, len(ancien) - repris,
        )

    def _recharger_libelles_habref(self):
        """Vider le cache des libellés : ils seront redemandés au référentiel."""
        try:
            connus = len(self.db.libelles_habref())
            self.db.oublier_libelles_habref()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "OccHab",
                                "Libellés HABREF non oubliés : %s" % exc)
            return
        self.logger.info("Libellés HABREF oubliés : %d", connus)
        QMessageBox.information(
            self, "OccHab",
            "%d libellé(s) oublié(s). Ils seront redemandés au référentiel à "
            "la prochaine ouverture du tableau." % connus,
        )

    def _completer_libelles_correspondance(self):
        """Inscrire les libellés manquants des correspondances déjà arbitrées.

        Les correspondances enregistrées avant la 0.9.1 ne portent que leur code :
        une carte chargée dans cette typologie affiche « C1.32 » là où une carte
        d'habitats se lit par ses noms. Plutôt que de faire résoudre ce libellé
        par la vue à chaque requête — ce qui avait fait s'effondrer l'export —
        on complète la donnée UNE fois.

        Passe par le chemin normal : les stations touchées repassent « à
        synchroniser », donc la correction remonte au serveur comme une saisie.
        """
        if self.client is None or not self.client.is_authenticated:
            QMessageBox.information(
                self, "OccHab",
                "Connectez-vous d'abord : les libellés viennent du référentiel "
                "HABREF, qui est côté serveur.")
            return

        stations = self.db.get_all_stations() or []
        a_faire = [
            (station, habitat)
            for station in stations
            for habitat in (station.get("habitats") or [])
            if corresp.libelles_manquants(habitat.get("technical_precision"))
        ]
        if not a_faire:
            QMessageBox.information(
                self, "OccHab", "Aucun libellé manquant : rien à compléter.")
            return
        if QMessageBox.question(
            self, "OccHab",
            "%d habitat(s) portent une correspondance sans libellé.\n\n"
            "Les compléter depuis HABREF et marquer leurs stations « à "
            "synchroniser » ?" % len(a_faire),
        ) != QMessageBox.StandardButton.Yes:
            return

        cache = {}

        def libelle_de(cd_hab):
            # Un cd_hab non résolu est laissé tel quel : mieux vaut un code nu
            # qu'un libellé inventé, et l'opération reste rejouable.
            if cd_hab not in cache:
                try:
                    fiche = self.client.get_habref(cd_hab) or {}
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("Libellé HABREF %s non résolu : %s", cd_hab, exc)
                    fiche = {}
                cache[cd_hab] = (fiche.get("lb_hab_fr") or "").strip() or None
            return cache[cd_hab]

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        completes, touchees = 0, set()
        try:
            for station, habitat in a_faire:
                neuf = corresp.completer_libelles(
                    habitat.get("technical_precision"), libelle_de)
                if not neuf:
                    continue
                habitat["technical_precision"] = neuf
                touchees.add(station["id"])
                completes += 1
            for id_station in touchees:
                station = next(s for s in stations if s["id"] == id_station)
                self.db.replace_habitats(id_station, station.get("habitats") or [])
                self.db.update_station(id_station, sync_status="pending")
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            self.logger.error("Complétion des libellés échouée : %s", exc)
            QMessageBox.warning(self, "OccHab", "Complétion interrompue : %s" % exc)
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.logger.info("Libellés de correspondance complétés : %d habitat(s), "
                         "%d station(s)", completes, len(touchees))
        self.refresh_stations()
        QMessageBox.information(
            self, "OccHab",
            "%d habitat(s) complété(s) sur %d, dans %d station(s).\n\n"
            "%sSynchronisez pour que la correction parte sur GeoNature."
            % (completes, len(a_faire), len(touchees),
               "" if completes == len(a_faire) else
               "Les autres n'ont pas été résolus par HABREF et gardent leur "
               "code seul ; l'opération est rejouable.\n\n"),
        )

    def _libelles_habref(self, stations):
        """{cd_hab: libellé HABREF} pour ces stations, complété au besoin.

        Le nom cité est ce que le botaniste a écrit ; le libellé HABREF est ce à
        quoi le `cd_hab` renvoie vraiment. Les voir côte à côte est le seul moyen
        de repérer une détermination dont le code ne correspond plus au nom.

        Les libellés déjà obtenus sont gardés dans la BASE LOCALE, pas dans le
        fichier de configuration : c'est un cache de données, pas un réglage, et
        il doit pouvoir se vider et se recharger sans qu'on aille éditer un
        fichier de préférences à la main.

        Hors ligne, on rend ce qu'on a : une colonne partiellement vide vaut
        mieux qu'une table qui refuse de s'ouvrir.
        """
        codes = {}
        for station in stations or []:
            for habitat in station.get("habitats") or []:
                if habitat.get("cd_hab"):
                    codes.setdefault(habitat["cd_hab"], habitat.get("nom_cite") or "")
        if not codes:
            return {}
        try:
            connus = self.db.libelles_habref(codes)
        except Exception as exc:  # noqa: BLE001 - une colonne ne bloque pas la table
            self.logger.warning("Cache des libellés HABREF illisible : %s", exc)
            connus = {}
        manquants = [c for c in sorted(codes) if c not in connus]
        if not manquants:
            return connus

        if self.client is None or not self.client.is_authenticated:
            self.logger.info(
                "Libellés HABREF : %d code(s) inconnus et pas de connexion — la "
                "colonne restera vide pour eux (%s).",
                len(manquants), ", ".join(str(c) for c in manquants[:8]),
            )
            return connus

        echecs, obtenus = [], {}
        for cd_hab in manquants[: self.LIBELLES_PAR_OUVERTURE]:
            libelle, raison = self._libelle_habref(cd_hab, codes.get(cd_hab))
            if libelle:
                obtenus[cd_hab] = libelle
            else:
                echecs.append("%s (%s)" % (cd_hab, raison))
        if obtenus:
            self.db.enregistrer_libelles_habref(obtenus)
            connus.update(obtenus)
        if echecs:
            # En INFO et non en debug : une case vide dans la colonne HABREF est
            # une question qu'on se pose, et le journal doit pouvoir y répondre.
            self.logger.info("Libellés HABREF non obtenus : %s", " ; ".join(echecs))
        reste = len(manquants) - self.LIBELLES_PAR_OUVERTURE
        if reste > 0:
            self.logger.info(
                "Libellés HABREF : %d code(s) restants, ils seront demandés à la "
                "prochaine ouverture de la table.", reste,
            )
        return connus

    def _libelle_habref(self, cd_hab, nom_cite=None):
        """(libellé, raison de l'échec) pour un cd_hab.

        Deux chemins, parce que le premier ne suffit pas :

        1. `GET habref/habitat/<cd_hab>`, la fiche directe ;
        2. à défaut, l'**autocomplétion** sur le code lu dans le nom cité. Un
           habitat marqué `fg_validite = NR` — non retenu, c'est-à-dire un
           synonyme — existe dans HABREF avec son libellé, mais la fiche directe
           peut le refuser. C'est le cas relevé sur le `Brachypodio
           rupestris-Centaureion nemoralis` (cd_hab 16415), dont la base porte
           bien `lb_hab_fr` alors que la colonne restait vide.

        HABREF ne remplit d'ailleurs pas toujours le même champ selon la
        typologie : on prend le premier renseigné plutôt que d'exiger
        `lb_hab_fr`, faute de quoi la colonne reste vide alors que le
        référentiel a répondu.
        """
        raisons = []
        try:
            libelle = _libelle_de_fiche(self.client.get_habref(cd_hab))
            if libelle:
                return libelle, ""
            raisons.append("fiche sans libellé")
        except Exception as exc:  # noqa: BLE001 - hors ligne, code retiré…
            raisons.append(str(exc)[:60])

        # Le code s'il est là, sinon le nom cité lui-même : une alliance du
        # Prodrome est citée « Cynosurion cristati », sans code en tête. Exiger
        # un code laissait la colonne vide pour toute une classe d'habitats
        # alors que l'autocomplétion, elle, répond.
        terme = _code_habref(nom_cite) or (nom_cite or "").strip()
        if not terme:
            return "", " puis ".join(raisons) or "aucun libellé"
        try:
            for item in self.client.search_habref(terme) or []:
                if item.get("cd_hab") == cd_hab:
                    libelle = _libelle_de_fiche(item)
                    if libelle:
                        return libelle, ""
            raisons.append("absent de la recherche sur « %s »" % terme)
        except Exception as exc:  # noqa: BLE001
            raisons.append("recherche « %s » : %s" % (terme, str(exc)[:40]))
        return "", " puis ".join(raisons)

    def _habref_search_fn(self):
        """Callable de recherche HABREF (avec filtre typologie) si connecté, sinon None."""
        if self.client is None or not self.client.is_authenticated:
            return None
        return lambda text, cd_typo=None: self.client.search_habref(text, cd_typo=cd_typo)

    def _habref_detail_fn(self):
        """Callable rendant la fiche HABREF complète d'un cd_hab, sinon None.

        La fiche porte les **correspondances** que HABREF connaît pour cet
        habitat, avec leurs libellés. C'est ce qui permet de proposer un code
        CORINE ou EUNIS à un botaniste qui a déterminé dans une autre typologie
        et ne connaît pas le code d'arrivée.
        """
        if self.client is None or not self.client.is_authenticated:
            return None
        return self.client.get_habref

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
        self._notify_occhab_layers_once()
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
    def _begin_new_station(self, template=None):
        """Ouvrir une création : `template` = station à copier, None = vierge.

        Toutes les entrées de création passent par ici pour que le modèle de
        duplication ne survive jamais à la création qui l'a demandé.
        """
        self._duplicate_source = template

    def _new_station_draw(self, geom_type):
        """Créer une station en dessinant sa géométrie sur la carte."""
        self._begin_new_station()
        self._capture_target = "new"
        self._start_capture(geom_type)

    def _new_station_no_geom(self):
        """Créer une station sans géométrie (à tracer plus tard)."""
        self._begin_new_station()
        self._capture_target = "new"
        self._open_station_dialog(None, None)

    def duplicate_station(self):
        """Créer une station reprenant attributs, habitats et observateurs d'une autre.

        La géométrie n'est jamais copiée (deux polygones superposés n'auraient pas
        de sens) : elle est redessinée, du même type que l'original.
        """
        station_id = self._selected_station_id()
        if station_id is None:
            QMessageBox.information(self, "OccHab", "Sélectionnez une station à dupliquer.")
            return
        full = self.db.get_station(station_id)
        if full is None:
            return
        self._begin_new_station(station_template(full))
        if full.get("geom"):
            self._capture_target = "new"
            self._start_capture(full.get("geom_type") or "polygon")
        else:  # l'original n'avait pas de géométrie : rien à redessiner
            self._open_station_dialog(None, None)

    # ------------------------------------------------ exports du serveur
    def load_server_export(self):
        """Charger un export GeoNature en couche QGIS (lecture seule).

        Volontairement séparé de « Récupérer une station » : un export est une
        vue préparée côté serveur, à plat et non éditable — la rapatrier dans la
        base locale n'aurait aucun sens, sa structure n'est pas celle d'OccHab.
        """
        from .export_dialog import VUE_EXPORT, ExportPicker, exports_occhab

        if self.client is None or not self.client.is_authenticated:
            QMessageBox.information(
                self, "OccHab", "Connectez-vous à GeoNature pour charger un export."
            )
            return
        try:
            exports = self.client.list_exports()
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Liste des exports indisponible : %s", exc)
            QMessageBox.warning(
                self, "OccHab", "Liste des exports indisponible : %s" % exc
            )
            return
        if not exports:
            QMessageBox.information(
                self, "OccHab",
                "Aucun export disponible.\n\nLe module « Exports » doit être "
                "installé sur l'instance GeoNature, et votre compte doit y avoir "
                "le droit de lecture. Les exports se déclarent dans l'admin "
                "GeoNature (schéma, vue, colonne clé primaire).",
            )
            return
        # Les autres exports de l'instance (synthèse, taxons, métadonnées…) ne
        # sont pas proposés : ni les filtres JDD/période ni la lecture de la
        # couche n'auraient de sens sur une vue de structure inconnue.
        occhab = exports_occhab(exports)
        if not occhab:
            QMessageBox.information(
                self, "OccHab",
                "Aucun export ne s'appuie sur la vue « %s ».\n\n%d export(s) "
                "publié(s) sur cette instance, mais aucun sur cette vue. "
                "Créez-le dans l'admin GeoNature : schéma « gn_exports », vue "
                "« %s », colonne clé primaire « id_ligne », champ géométrie "
                "« geom » (voir le README §6)."
                % (VUE_EXPORT, len(exports), VUE_EXPORT),
            )
            return

        dialog = ExportPicker(
            occhab, datasets=self._dataset_items(),
            id_dataset=self.combo_jdd.currentData() if self.combo_jdd.isEnabled() else None,
            en_attente=self._stations_en_attente,
            parent=self,
        )
        if not dialog.exec():
            return
        self._charger_export(dialog.id_export(), dialog.libelle_export(),
                             dialog.filtres(), dialog.mode(), dialog.libelle_mode(),
                             dialog.typologie(), dialog.libelle_typologie())

    def _charger_export(self, id_export, libelle, filtres, mode=None,
                        libelle_mode=None, typologie=None, libelle_typologie=None):
        """Rapatrier toutes les pages d'un export et le poser en couche."""
        from qgis.PyQt.QtCore import Qt as _Qt
        from qgis.PyQt.QtWidgets import QApplication

        # Le mode figure dans le nom : deux représentations des mêmes données
        # doivent pouvoir cohabiter pour être comparées.
        nom_couche = self._nom_couche_export(libelle, filtres)
        if typologie:
            # La typologie AVANT le mode : c'est elle qui change ce que la carte
            # dit, quand le mode ne change que la façon de le dessiner. Deux
            # cartes du même export dans deux typologies doivent se distinguer
            # au premier coup d'œil dans le panneau des couches.
            nom_couche = "%s [%s]" % (nom_couche, libelle_typologie)
        if libelle_mode:
            nom_couche = "%s [%s]" % (nom_couche, libelle_mode.lower())
        QApplication.setOverrideCursor(_Qt.CursorShape.WaitCursor)
        try:
            features, total_filtre, total = self.client.iter_export_features(
                id_export, filters=filtres,
                on_progress=lambda recus, attendus: self.logger.debug(
                    "Export %s : %s/%s entités", id_export, recus, attendus
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Chargement de l'export %s échoué : %s", id_export, exc)
            QMessageBox.critical(self, "Erreur", "Export non chargé : %s" % exc)
            return
        finally:
            QApplication.restoreOverrideCursor()

        if not features:
            self.iface.messageBar().pushInfo(
                "OccHab",
                "L'export « %s » ne renvoie aucune donnée pour ce jeu de données "
                "et cette période." % libelle,
            )
            return
        layer, count = self.export_layers.show(nom_couche, features, mode=mode,
                                               typologie=typologie)
        if layer is None:
            QMessageBox.warning(
                self, "OccHab",
                "Export récupéré (%d entités) mais la couche n'a pas pu être "
                "créée — voir le journal." % len(features),
            )
            return
        self.logger.info(
            "Export %s chargé : %d entité(s) (annoncées : %s filtrées sur %s au total)",
            id_export, count, total_filtre, total,
        )
        self.iface.messageBar().pushInfo(
            "OccHab", "Export « %s » : %d entité(s) chargée(s)." % (nom_couche, count)
        )
        self._avertir_filtres_ignores(total_filtre, total, filtres)

    def _avertir_filtres_ignores(self, total_filtre, total, filtres):
        """Prévenir quand le filtrage n'a visiblement rien restreint.

        L'API d'export ignore **en silence** un filtre portant sur une colonne
        absente de la vue. Sans ce contrôle, on croirait tenir l'année en cours
        d'un JDD alors qu'on a rapatrié tout l'export. Le doute est signalé, pas
        affirmé : un filtre peut légitimement retenir la totalité des lignes.
        """
        if not filtres or not total or total_filtre != total:
            return
        self.iface.messageBar().pushWarning(
            "OccHab",
            "Le nombre d'entités renvoyées est celui de l'export entier : vos "
            "filtres n'ont peut-être pas été appliqués. Vérifiez que la vue "
            "exportée porte bien les colonnes « id_dataset », « date_min » et "
            "« date_max » (cf. README §6).",
        )

    @staticmethod
    def _nom_couche_export(libelle, filtres):
        """Nom de couche portant la période : deux années doivent coexister."""
        debut = (filtres or {}).get("filter_d_up_date_min")
        fin = (filtres or {}).get("filter_d_lo_date_max")
        if debut and fin:
            return "%s (%s → %s)" % (libelle, debut, fin)
        return libelle

    # ------------------------------------- presse-papiers de renseignements
    def copy_station_fields(self):
        """Mettre de côté les renseignements d'une station, pour les coller ailleurs."""
        station_id = self._selected_station_id()
        if station_id is None:
            QMessageBox.information(self, "OccHab", "Sélectionnez une station à copier.")
            return
        full = self.db.get_station(station_id)
        if full is None:
            return
        self._clipboard = station_template(full)
        self._clipboard_label = full.get("station_name") or "station sans nom"
        self._maj_barre_action()
        self.iface.messageBar().pushInfo(
            "OccHab",
            "Renseignements de « %s » copiés (%d habitat(s)). Sélectionnez une "
            "ou plusieurs stations puis « Coller les renseignements », ou créez "
            "une station avec eux depuis « ＋ Nouvelle station »."
            % (self._clipboard_label, len(self._clipboard.get("habitats") or [])),
        )

    def paste_station_fields(self):
        """Appliquer les renseignements copiés aux stations sélectionnées.

        Géométrie, nom et statut de validation de chaque station cible sont
        conservés : c'est ce qui distingue « coller » de « dupliquer ». Le reste
        — JDD, dates, observateurs, attributs, habitats — est remplacé.
        """
        if self._clipboard is None:
            QMessageBox.information(
                self, "OccHab",
                "Copiez d'abord les renseignements d'une station (clic droit → "
                "« Copier les renseignements »).",
            )
            return
        cibles = self._selected_station_ids()
        if not cibles:
            QMessageBox.information(
                self, "OccHab", "Sélectionnez la ou les stations à renseigner."
            )
            return
        habitats = self._clipboard.get("habitats") or []
        observers = self._clipboard.get("observers") or []
        question = (
            "Remplacer les renseignements de %d station(s) par ceux de « %s » ?\n\n"
            "Sont écrasés : JDD, dates, observateurs, attributs, commentaire et "
            "les habitats (%d repris ; les habitats existants des stations "
            "visées sont supprimés).\n"
            "Sont conservés : la géométrie, le nom et le statut de chaque station."
            % (len(cibles), self._clipboard_label, len(habitats))
        )
        if QMessageBox.question(self, "Coller les renseignements", question) != \
                QMessageBox.StandardButton.Yes:
            return
        fields = paste_fields(self._clipboard)
        # Le créateur d'origine de la station VISÉE reste le sien ; celui qui
        # colle en devient l'éditeur (même règle que l'édition au formulaire).
        fields.pop("created_by", None)
        fields["updated_by"] = current_user()
        colles = echecs = 0
        for station_id in cibles:
            try:
                # `validation_status` n'est pas dans `fields` (écarté par le
                # modèle de duplication) : le statut de la cible reste le sien.
                self.db.update_station(station_id, sync_status="pending", **fields)
                self.db.replace_habitats(station_id, [dict(h) for h in habitats])
                self.db.replace_observers(station_id, observers)
                colles += 1
            except Exception as exc:  # noqa: BLE001
                echecs += 1
                self.logger.error(
                    "Collage des renseignements sur la station %s échoué : %s",
                    station_id, exc,
                )
        self.logger.info(
            "Renseignements collés : %d station(s), %d échec(s)", colles, echecs
        )
        self.refresh()
        message = "%d station(s) renseignée(s) depuis « %s »." % (
            colles, self._clipboard_label
        )
        if echecs:
            self.iface.messageBar().pushWarning(
                "OccHab", message + " %d échec(s) — voir le journal." % echecs
            )
        else:
            self.iface.messageBar().pushInfo("OccHab", message)

    def _new_station_from_clipboard(self):
        """Créer une station en reprenant les renseignements copiés (géométrie à tracer)."""
        if self._clipboard is None:
            QMessageBox.information(
                self, "OccHab",
                "Copiez d'abord les renseignements d'une station (clic droit → "
                "« Copier les renseignements »).",
            )
            return
        # Copie : le presse-papiers doit survivre à cette création, pour en
        # enchaîner plusieurs.
        self._begin_new_station(station_template(self._clipboard))
        self._capture_target = "new"
        self._start_capture("polygon")

    def _pick_local_station(self, exclude_id=None):
        """Faire choisir une station locale et la renvoyer complète (ou None)."""
        from .station_picker_dialog import LocalStationPicker

        jdd = self.combo_jdd.currentData() if self.combo_jdd.isEnabled() else None
        stations = self.db.get_stations_full(id_dataset=jdd)
        if exclude_id is not None:
            stations = [s for s in stations if s.get("id") != exclude_id]
        if not stations:
            QMessageBox.information(
                self, "OccHab",
                "Aucune autre station à reprendre dans ce jeu de données.",
            )
            return None
        dialog = LocalStationPicker(stations, parent=self)
        if not dialog.exec():
            return None
        station_id = dialog.selected_id()
        if station_id is None:
            return None
        return self.db.get_station(station_id)

    # ------------------------------------------ reprise de géométrie (couche)
    def _new_station_from_selection(self):
        """Créer une (ou plusieurs) station(s) depuis la ou les entités sélectionnées.

        Sélection simple → formulaire habituel. Sélection multiple → une station par
        entité, avec des métadonnées communes saisies une seule fois (nom laissé vide,
        habitat facultatif) et surface/altitude calculées pour chaque géométrie.
        """
        geoms, error = self._reprise_geometries()
        if error:
            QMessageBox.information(self, "OccHab", error)
            return
        self._begin_new_station()
        self._capture_target = None
        if len(geoms) == 1:
            wkt, geom_type = geoms[0]
            self._open_station_dialog(wkt, geom_type, self._geo_metrics(wkt, geom_type))
            return
        self._create_stations_from_geometries(geoms)

    def _create_stations_from_geometries(self, geoms):
        """Créer une station par géométrie en partageant les métadonnées d'un formulaire.

        Le nom reste vide (propre à chaque station) ; surface et altitude sont
        recalculées par géométrie ; l'habitat et les observateurs éventuellement saisis
        sont appliqués à chaque station du lot.
        """
        dialog = self._make_station_dialog(batch_count=len(geoms))
        if not dialog.exec():
            return
        shared, habitats = dialog.get_result()
        observers = shared.pop("_observers", [])
        # Champs propres à chaque station : écartés du modèle commun, réaffectés ci-dessous.
        for key in ("geom", "geom_type", "station_name", "area",
                    "altitude_min", "altitude_max"):
            shared.pop(key, None)
        created = failed = 0
        for wkt, geom_type in geoms:
            metrics = self._geo_metrics(wkt, geom_type)
            fields = dict(shared)
            fields.update(
                geom=wkt,
                geom_type=geom_type,
                station_name=None,
                area=metrics.get("area"),
                altitude_min=metrics.get("altitude_min"),
                altitude_max=metrics.get("altitude_max"),
            )
            try:
                station_id = self.db.create_station(**fields)
                for habitat in habitats:
                    self.db.add_habitat(id_station_local=station_id, **habitat)
                for obs in observers:
                    self.db.add_observer(
                        station_id,
                        observer_name=obs.get("observer_name"),
                        id_role=obs.get("id_role"),
                    )
                created += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.logger.error("Échec création station (lot) : %s", exc)
        self.logger.info(
            "Création depuis sélection : %d station(s) créée(s), %d échec(s)",
            created, failed,
        )
        if created:
            self._remember_last_entry(
                shared, observers, dialog.habref_cd_typo, habitats=habitats
            )
        parts = ["%d station(s) créée(s)" % created]
        if habitats:
            parts.append("%d habitat(s) chacune" % len(habitats))
        if failed:
            parts.append("%d échec(s)" % failed)
        self.iface.messageBar().pushInfo("OccHab", "Sélection : %s." % ", ".join(parts))
        self.refresh()

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

    def _layer_transform_to_4326(self, layer):
        """QgsCoordinateTransform de la couche vers EPSG:4326, ou None si déjà en 4326."""
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsProject,
        )

        src_crs = layer.crs()
        if not src_crs.isValid():
            # Supposer EPSG:4326 recopiait des mètres en les présentant comme des
            # degrés : géométrie fausse en base et envoyée telle quelle à
            # GeoNature. Mieux vaut refuser et le dire.
            raise CrsIndetermine(
                "La couche « %s » n'a pas de SCR défini : impossible de savoir "
                "où se trouve sa géométrie. Définissez son SCR, puis "
                "recommencez." % layer.name()
            )
        if src_crs.authid() != "EPSG:4326":
            return QgsCoordinateTransform(
                src_crs,
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsProject.instance(),
            )
        return None

    def _feature_geometry_wkt(self, feature, transform):
        """(WKT EPSG:4326, geom_type) d'une entité, ou None si inexploitable.

        `transform` : QgsCoordinateTransform déjà prêt (ou None si la couche est en
        EPSG:4326). Écarte silencieusement les entités sans géométrie, de type non
        géré (ni point/ligne/polygone) ou dont la reprojection échoue.
        """
        from qgis.core import QgsGeometry, QgsWkbTypes

        geom = QgsGeometry(feature.geometry())
        if geom is None or geom.isEmpty():
            return None
        # Type géré (point / ligne / polygone) ; enum QGIS scopé ou non.
        types = getattr(QgsWkbTypes, "GeometryType", QgsWkbTypes)
        geom_type = {
            types.PointGeometry: "point",
            types.LineGeometry: "line",
            types.PolygonGeometry: "polygon",
        }.get(geom.type())
        if geom_type is None:
            return None
        try:
            if transform is not None:
                geom.transform(transform)
            wkt = geom.asWkt()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Reprise de géométrie : reprojection échouée : %s", exc)
            return None
        return (wkt, geom_type) if wkt else None

    def _reprise_geometry(self):
        """(WKT EPSG:4326, geom_type, erreur) de la PREMIÈRE entité sélectionnée.

        Reprend la première entité sélectionnée de la couche vectorielle active et
        la reprojette en EPSG:4326. Renvoie (None, None, message) si rien d'exploitable.
        """
        from qgis.core import QgsVectorLayer

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
        try:
            transform = self._layer_transform_to_4326(layer)
        except CrsIndetermine as exc:
            return None, None, str(exc)
        result = self._feature_geometry_wkt(features[0], transform)
        if result is None:
            return None, None, (
                "Géométrie inexploitable : entité sans géométrie, de type non géré "
                "(ni point/ligne/polygone) ou reprojection impossible."
            )
        return result[0], result[1], None

    def _reprise_geometries(self):
        """([(WKT EPSG:4326, geom_type), …] de TOUTES les entités sélectionnées, erreur).

        Une entrée par entité sélectionnée exploitable (les autres sont ignorées).
        Renvoie ([], message) si la couche est invalide ou la sélection vide/inutilisable.
        """
        from qgis.core import QgsVectorLayer

        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            return [], (
                "Activez d'abord une couche vectorielle contenant les entités voulues."
            )
        features = layer.selectedFeatures()
        if not features:
            return [], (
                "Aucune entité sélectionnée dans la couche « %s »." % layer.name()
            )
        try:
            transform = self._layer_transform_to_4326(layer)
        except CrsIndetermine as exc:
            return [], str(exc)
        geoms = []
        for feature in features:
            result = self._feature_geometry_wkt(feature, transform)
            if result is not None:
                geoms.append(result)
        if not geoms:
            return [], (
                "Aucune géométrie exploitable dans la sélection (entités vides ou de "
                "type non géré)."
            )
        return geoms, None

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
        # Sans cela, une duplication abandonnée en cours de numérisation
        # contaminerait la prochaine « Nouvelle station ».
        self._duplicate_source = None
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
        if not wkt_en_degres_plausibles(wkt):
            # Des mètres pris pour des degrés : la surface serait aberrante et le
            # serveur refuse le calcul d'altitude (« Invalid coordinate »).
            self.logger.error(
                "Géométrie hors du domaine WGS84, mesures abandonnées : %s",
                wkt[:80],
            )
            self.iface.messageBar().pushWarning(
                "OccHab",
                "Géométrie hors du domaine WGS84 : surface et altitude non "
                "calculées. Vérifiez le SCR de la couche d'origine.",
            )
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
        if self._table_dialog is not None:
            # Non modale : sans cela elle survivrait au plugin, avec une base et
            # des couches disparues sous elle.
            self._table_dialog.close()
            self._table_dialog = None
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
        self.export_layers.cleanup()

    def _last_observers(self):
        """Observateurs de la dernière saisie, pour pré-remplir la suivante."""
        saved = self.config.get("last_entry.observers") or []
        return [obs for obs in saved if isinstance(obs, dict) and obs.get("id_role")]

    def _last_cd_typo(self):
        """Typologie HABREF de la dernière saisie, pour pré-régler le filtre."""
        return self.config.get("last_entry.cd_typo")

    def _last_habitat(self):
        """Habitat de la dernière saisie, pour pré-remplir le prochain."""
        habitat = self.config.get("last_entry.habitat")
        return habitat if isinstance(habitat, dict) and habitat else None

    def _remember_last_entry(self, station, observers, cd_typo=None, habitats=None):
        """Retenir observateurs, typologie, habitat et dates pour la saisie suivante.

        Observateurs, typologie HABREF et habitat : persistés en configuration —
        une équipe, une typologie et une façon de déterminer changent peu au
        cours d'une campagne. Dates : gardées pour la session QGIS seulement,
        pour ne pas traîner une date d'observation périmée d'un jour de terrain
        sur l'autre.
        """
        if cd_typo is not None:
            self.config.set("last_entry.cd_typo", cd_typo)
        if habitats:
            # Le DERNIER habitat saisi : dans une mosaïque, c'est celui qu'on
            # vient de décrire, donc le plus proche de ce qui vient ensuite.
            self.config.set("last_entry.habitat", habitat_reprise(habitats[-1]))
        self.config.set(
            "last_entry.observers",
            [
                {"id_role": o.get("id_role"), "observer_name": o.get("observer_name")}
                for o in (observers or []) if o.get("id_role")
            ],
        )
        if station.get("date_min") and station.get("date_max"):
            self._session_dates = (station["date_min"], station["date_max"])

    def _make_station_dialog(self, *, geom_wkt=None, geom_type=None, metrics=None,
                             station=None, batch_count=0, template=None):
        """Construire un StationDialog en injectant nomenclatures, JDD, observateurs…

        Point unique d'assemblage partagé par la création (simple / lot / copie) et
        l'édition, pour éviter que les appels divergent.
        """
        en_cours = (station or {}).get("id")
        return StationDialog(
            self.config,
            geom_wkt=geom_wkt,
            geom_type=geom_type,
            geo_metrics=metrics,
            station=station,
            batch_count=batch_count,
            template=template,
            last_observers=self._last_observers(),
            habref_cd_typo=self._last_cd_typo(),
            last_dates=self._session_dates,
            last_habitat=self._last_habitat(),
            station_picker=lambda: self._pick_local_station(exclude_id=en_cours),
            datasets=self._dataset_items(),
            station_nomenclatures=self._station_nomenclatures(),
            habitat_nomenclatures=self._habitat_nomenclatures(),
            station_defaults=self._station_defaults(),
            habitat_defaults=self._habitat_defaults(),
            abundance_cover_map=self._abundance_cover_map(),
            habref_search=self._habref_search_fn(),
            habref_detail=self._habref_detail_fn(),
            habref_typologies=self._habref_typologies(),
            observers=self._observers_items(),
            current_observer=self._current_user_observer(),
            user_names=self._user_names(),
            default_determiner=self._current_user_name(),
            parent=self,
        )

    def _open_station_dialog(self, geom_wkt, geom_type, metrics=None):
        # Le modèle de duplication ne vaut que pour CETTE création : consommé ici,
        # qu'on aille au bout ou non.
        template = self._duplicate_source
        self._duplicate_source = None
        dialog = self._make_station_dialog(
            geom_wkt=geom_wkt, geom_type=geom_type, metrics=metrics, template=template
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
        self._remember_last_entry(
            station, observers, dialog.habref_cd_typo, habitats=habitats
        )
        self.refresh()

    def open_attribute_table(self):
        """Ouvrir la table des stations et habitats du JDD courant."""
        from .attribute_table import AttributeTableDialog, Contexte

        jdd = self.combo_jdd.currentData() if self.combo_jdd.isEnabled() else None
        stations = self.db.get_stations_full(id_dataset=jdd)
        if not stations:
            QMessageBox.information(
                self, "OccHab",
                "Aucune station locale à afficher.\n\nLa table porte sur votre base "
                "locale : récupérez d'abord les stations du serveur si besoin.",
            )
            return
        # Les deux jeux de nomenclatures sont fusionnés : le registre de champs
        # les désigne par une clé unique, sans distinguer station et habitat.
        nomenclatures = dict(self._station_nomenclatures())
        nomenclatures.update(self._habitat_nomenclatures())
        if self._table_dialog is not None:
            if self._table_dialog.isVisible():  # déjà ouverte : au premier plan
                self._table_dialog.raise_()
                self._table_dialog.activateWindow()
                return
            # Fermée sans nous prévenir : la référence périmée rendait le bouton
            # inopérant. On la jette et on rouvre une fenêtre neuve.
            self._table_dialog = None
        dialog = AttributeTableDialog(
            self.db,
            stations,
            Contexte(
                nomenclatures=nomenclatures,
                datasets=self._dataset_items(),
                # Le libellé du référentiel à côté du nom cité : on voit à quoi
                # le cd_hab renvoie vraiment.
                habref_labels=self._libelles_habref(stations),
                # Pour choisir un habitat en masse comme dans le formulaire.
                habref_search=self._habref_search_fn(),
                habref_detail=self._habref_detail_fn(),
                typologies=self._habref_typologies(),
                observers=self._observers_items(),
                cd_typo=self._last_cd_typo(),
            ),
            layers=self.layers,
            logger=self.logger,
            parent=self,
        )
        # NON modale : une fenêtre modale bloquerait le canevas, or la sélection
        # doit pouvoir se faire sur la carte pendant que la table est ouverte.
        dialog.setModal(False)
        dialog.finished.connect(self._on_attribute_table_closed)
        # Un lot enregistré doit se voir immédiatement dans la liste et sur la
        # carte : la table peut rester ouverte longtemps après.
        dialog.donnees_enregistrees.connect(self.refresh)
        self._table_dialog = dialog
        dialog.show()

    def _on_attribute_table_closed(self, _result=None):
        self._table_dialog = None
        self.refresh()  # reprendre ce que la table a enregistré

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
        dialog = self._make_station_dialog(station=full)
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
        # Chargement en lot : habitats et observateurs arrivent avec les stations,
        # en 3 requêtes au total (auparavant 3 par station).
        all_stations = self.db.get_stations_full()
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
            habitats = station.get("habitats") or []
            station["_nb_habitats"] = len(habitats)
            status = station.get("sync_status")
            if status == "conflict":
                n_conflict += 1
            row = self.table.rowCount()
            self.table.insertRow(row)
            # L'identifiant LOCAL voyage sur la première colonne, quelle qu'elle
            # soit : c'est là que le reste du panneau va le chercher pour savoir
            # sur quelle station porte une action.
            item_id = self._item_id_station(station)
            item_id.setData(Qt.ItemDataRole.UserRole, station["id"])
            self.table.setItem(row, 0, item_id)
            item_hab = QTableWidgetItem(self._station_label(station, habitats))
            observers = station.get("observers_txt") or ""
            if observers:
                item_hab.setToolTip("Observateur(s) : %s" % observers)
            self.table.setItem(row, 1, item_hab)
            self.table.setItem(row, 2, QTableWidgetItem(station.get("date_min") or ""))
            self.table.setCellWidget(row, 3, self._status_pill(station))
        # Les deux pastilles sont empilées : la hauteur par défaut les tronquerait.
        self.table.resizeRowsToContents()
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
        self._refresh_attribute_table(stations)
        self.logger.info("Liste rafraîchie : %d station(s)", len(stations))
        self._notify_occhab_layers_once()

    @staticmethod
    def _item_id_station(station):
        """Identifiant GeoNature de la station, ou un tiret s'il n'existe pas.

        Un tiret plutôt qu'une case vide : l'identifiant manque tant que la
        station n'est pas partie sur le serveur, et une case vide se lit comme
        un oubli de saisie.
        """
        identifiant = station.get("id_station")
        item = QTableWidgetItem("%s" % identifiant if identifiant else "—")
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                              | Qt.AlignmentFlag.AlignVCenter)
        item.setToolTip(
            "Identifiant de la station sur GeoNature : le même que dans les "
            "exports et l'interface web." if identifiant else
            "Pas encore synchronisée : GeoNature ne lui a pas encore attribué "
            "d'identifiant."
        )
        return item

    def _refresh_attribute_table(self, stations):
        """Répercuter dans la table ouverte ce qui vient d'être écrit ailleurs.

        La table est non modale : sans cela elle travaille indéfiniment sur la
        copie prise à son ouverture, et affiche un état périmé. On ne recharge
        que si elle n'a rien en attente — des modifications non enregistrées ne
        se jettent pas sans que l'utilisateur l'ait demandé.
        """
        dialog = self._table_dialog
        if dialog is None or dialog.a_des_modifications():
            return
        try:
            dialog.recharger(stations)
        except Exception as exc:  # noqa: BLE001 - la table ne doit pas casser la liste
            self.logger.warning("Table attributaire non rechargée : %s", exc)

    def _notify_occhab_layers_once(self):
        """Avertir une seule fois par session que les couches/groupes OccHab
        gérés par le plugin viennent d'apparaître dans le panneau Couches."""
        if self._occhab_layers_notice_shown:
            return
        has_layers = (
            bool(self.layers.existing_layers()) or self.server_layers.layer() is not None
        )
        if not has_layers:
            return
        self._occhab_layers_notice_shown = True
        self.iface.messageBar().pushInfo(
            "OccHab",
            "Les groupes « OccHab (local) » et « OccHab (serveur) » viennent "
            "d'apparaître dans le panneau Couches : ils sont gérés automatiquement "
            "par le plugin (couches en lecture seule, reconstruites à chaque "
            "rafraîchissement) — évitez de les modifier, renommer ou déplacer "
            "manuellement."
        )

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

    def _selected_station_ids(self):
        """Ids locaux de TOUTES les lignes sélectionnées (multi-sélection Ctrl/Maj)."""
        ids = []
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            if item is not None:
                sid = item.data(Qt.ItemDataRole.UserRole)
                if sid is not None:
                    ids.append(sid)
        return ids

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

    def _purge_old_synced_stations(self):
        """Retirer du local les stations synchronisées non touchées depuis N mois.

        Ces stations restent sur GeoNature (re-récupérables) : on ne touche jamais
        aux stations non synchronisées, en conflit ou en attente de suppression.
        Confirmation explicite + compte-rendu.
        """
        months = self.db.RETENTION_MONTHS
        count = self.db.count_purgeable_stations()
        if count == 0:
            QMessageBox.information(
                self, "OccHab",
                "Aucune station synchronisée de plus de %d mois à nettoyer." % months,
            )
            return
        confirm = QMessageBox.question(
            self, "Nettoyer la base locale",
            "%d station(s) synchronisée(s) et non modifiée(s) depuis plus de %d mois "
            "vont être retirées de la base LOCALE.\n\n"
            "Elles restent sur GeoNature et pourront être récupérées via "
            "« Récupérer une station du serveur ». Continuer ?" % (count, months),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        removed = self.db.purge_synced_stations()
        self.logger.info("Purge rétention : %d station(s) retirée(s) du local", removed)
        self.iface.messageBar().pushInfo(
            "OccHab",
            "%d station(s) synchronisée(s) ancienne(s) retirée(s) du local "
            "(toujours sur GeoNature)." % removed,
        )
        self.refresh()

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

    def create_print_layout(self):
        """Composer une planche cartographique à partir d'un gabarit ANA.

        La couche proposée est celle des exports OccHab : c'est elle qui porte la
        symbologie par habitat et la légende à deux niveaux. À défaut, la couche
        active fait l'affaire — on cartographie ce qu'on regarde.
        """
        from qgis.core import QgsProject
        from qgis.PyQt.QtWidgets import QDialog

        from .layout_dialog import CLE_DOSSIER, LayoutPicker
        from .print_layout import GabaritIllisible, GabaritIntrouvable, creer

        dialogue = LayoutPicker(
            self._couches_cartographiables(),
            dossier=self.config.get(CLE_DOSSIER),
            titre_propose=self._titre_de_planche(),
            sous_titre_propose=self._sous_titre_de_planche(),
            parent=self,
        )
        if dialogue.exec() != QDialog.DialogCode.Accepted:
            return
        if dialogue.dossier():
            self.config.set(CLE_DOSSIER, dialogue.dossier())

        choix = dialogue.parametres()
        canevas = self.iface.mapCanvas()
        emprise = canevas.extent() if choix.pop("emprise_vue") else None
        try:
            mise, avertissements = creer(
                choix.pop("chemin_gabarit"),
                choix.pop("titre"),
                # Les couches TELLES QU'À L'ÉCRAN : c'est ce qui garde l'ortho
                # sous les polygones d'habitats.
                couches_carte=canevas.layers(),
                emprise=emprise,
                crs=canevas.mapSettings().destinationCrs(),
                pied=self._pied_de_planche(),
                logger=self.logger,
                **choix
            )
        except (GabaritIntrouvable, GabaritIllisible) as exc:
            QMessageBox.warning(
                self, "Mise en page",
                "Ce gabarit n'a pas pu être ouvert : %s" % exc
            )
            return

        jdd = self.combo_jdd.currentData() if self.combo_jdd.isEnabled() else None
        en_attente = self._stations_en_attente(jdd)
        if en_attente:
            avertissements.insert(0,
                "%d station(s) locale(s) ne sont pas synchronisées : cette carte "
                "est faite sur les données de GeoNature et ne les montre pas."
                % en_attente
            )
        for message in avertissements:
            self.iface.messageBar().pushWarning("OccHab — mise en page", message)
        self.iface.openLayoutDesigner(mise)

    def _stations_en_attente(self, id_dataset=None):
        """Stations locales pas encore parties, dans ce jeu de données.

        La cartographie se fait sur les données de GeoNature, jamais sur la base
        locale : un export est une vue du serveur. Tant qu'une saisie n'est pas
        synchronisée, elle n'existe pas pour la carte — et rien ne le montre.

        Compter TOUS les JDD serait du bruit : les stations d'un autre jeu de
        données n'ont rien à faire dans cet export, et leur absence n'est pas un
        oubli.
        """
        try:
            return len(self.db.get_pending_stations(id_dataset=id_dataset) or [])
        except Exception as exc:  # noqa: BLE001 - un compteur ne doit rien bloquer
            self.logger.debug("Comptage des stations en attente impossible : %s", exc)
            return 0

    def _couches_cartographiables(self):
        """(nom, couche) : les exports OccHab d'abord, puis la couche active."""
        from qgis.core import QgsProject

        from .export_layers import GROUP_NAME

        couches, vues = [], set()
        groupe = QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME)
        for noeud in (groupe.findLayers() if groupe is not None else []):
            couche = noeud.layer()
            if couche is not None:
                couches.append((couche.name(), couche))
                vues.add(couche.id())
        active = self.iface.activeLayer()
        if active is not None and active.id() not in vues:
            couches.append(("%s (couche active)" % active.name(), active))
        return couches

    def _titre_de_planche(self):
        """Titre proposé : le nom du jeu de données, et rien de plus.

        Le bandeau des gabarits est d'une hauteur fixe. Un titre composé
        (« Cartographie des habitats — 242026 - Révision PDG… ») passe à la ligne
        et déborde du bandeau vert. Le nom du JDD dit déjà de quoi il s'agit ;
        « Cartographie des habitats » part en sous-titre, où la place ne manque
        pas.
        """
        combo = getattr(self, "combo_jdd", None)
        nom = combo.currentText().strip() if combo is not None else ""
        return nom or "Cartographie des habitats"

    @staticmethod
    def _sous_titre_de_planche():
        from datetime import date

        return "Cartographie des habitats — %s" % date.today().year

    @staticmethod
    def _pied_de_planche():
        from datetime import date

        return "ANA-CEN Ariège — %s" % date.today().strftime("%d/%m/%Y")

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
        ids = self._selected_station_ids()
        if not ids:
            QMessageBox.information(self, "OccHab", "Sélectionnez une station.")
            return
        if len(ids) > 1:
            self._delete_many_stations(ids)
            return
        self._delete_one_station(ids[0])

    def _delete_one_station(self, station_id):
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

    def _delete_many_stations(self, ids):
        """Suppression groupée (multi-sélection). Deux gestes distincts, non mélangés :
        retirer les copies LOCALES (sûr, n'affecte pas GeoNature) ou marquer « à
        supprimer » sur GeoNature (seulement vos stations déjà synchronisées).
        """
        stations = [s for s in (self.db.get_station(sid) for sid in ids) if s]
        if not stations:
            return
        on_server = [s for s in stations if s.get("id_station")]
        never_synced = [s for s in stations if not s.get("id_station")]
        pending = [s for s in stations if s.get("sync_status") == "pending"]
        server_mine = [s for s in on_server if s.get("mine", 1)]

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Supprimer %d stations" % len(stations))
        box.setText("%d stations sélectionnées." % len(stations))
        lines = []
        if never_synced:
            lines.append(
                "• %d jamais synchronisée(s) → suppression DÉFINITIVE (locale)."
                % len(never_synced)
            )
        if on_server:
            lines.append(
                "• %d déjà sur GeoNature → retirée(s) du local, conservée(s) sur le "
                "serveur (re-récupérables)." % len(on_server)
            )
        if pending:
            lines.append(
                "⚠ %d avec des modifications locales non synchronisées : elles seront "
                "perdues." % len(pending)
            )
        info = "\n".join(lines)
        info += ("\n\n« Retirer de ma base locale » enlève les %d copies locales sans "
                 "toucher GeoNature." % len(stations))
        btn_local = box.addButton(
            "Retirer de ma base locale", QMessageBox.ButtonRole.AcceptRole
        )
        btn_server = None
        if server_mine:
            info += ("\n« Supprimer sur GeoNature » marque pour suppression les %d "
                     "station(s) que vous avez créées et déjà synchronisées (réversible "
                     "jusqu'à la synchro ; les autres de la sélection ne sont pas "
                     "touchées)." % len(server_mine))
            btn_server = box.addButton(
                "Supprimer sur GeoNature (%d)" % len(server_mine),
                QMessageBox.ButtonRole.DestructiveRole,
            )
        btn_cancel = box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        box.setInformativeText(info)
        box.setDefaultButton(btn_cancel)  # éviter un geste destructeur par inadvertance
        box.setEscapeButton(btn_cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_local:
            for station in stations:
                self.db.delete_station(station["id"])
            self.iface.messageBar().pushInfo(
                "OccHab", "%d station(s) retirée(s) de la base locale." % len(stations)
            )
            self.refresh()
        elif btn_server is not None and clicked is btn_server:
            for station in server_mine:
                self.db.update_station(station["id"], sync_status="to_delete")
            self.iface.messageBar().pushInfo(
                "OccHab",
                "%d station(s) marquée(s) « à supprimer » (effectif à la prochaine "
                "synchronisation)." % len(server_mine),
            )
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

        from ..api.geonature_client import GeoNatureAPIError
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
                        try:
                            self.client.delete_station(station["id_station"])
                        except GeoNatureAPIError as exc:
                            if exc.status_code != 404:
                                raise
                            # Déjà supprimée sur GeoNature : l'objectif est atteint,
                            # il reste seulement à nettoyer la base locale.
                            self.logger.info(
                                "Station %s déjà absente du serveur : suppression "
                                "locale seule.", station["id_station"],
                            )
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
        # Stations dont l'id serveur ne correspond plus à rien (supprimées sur
        # GeoNature) : recréées ou laissées en attente selon la réponse de
        # l'utilisateur (None = question pas encore posée pour cette synchro).
        orphans_recreated = orphans_kept = 0
        recreate_orphans = None
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
            # La station existe-t-elle encore côté serveur ? Un id_station mémorisé
            # peut désigner une station supprimée depuis sur GeoNature : la mise à
            # jour part alors dans le vide et le serveur répond HTTP 500. On
            # interroge donc le serveur AVANT d'envoyer quoi que ce soit.
            # Fail-open : si le contrôle échoue (réseau…), on synchronise quand même.
            current = None
            recreated = False  # station orpheline renvoyée comme une création
            if full.get("id_station"):
                try:
                    current = self.client.get_station(full["id_station"])
                except GeoNatureAPIError as exc:
                    if exc.status_code != 404:
                        self.logger.warning(
                            "Contrôle serveur ignoré (station %s) : %s",
                            full["id_station"], exc,
                        )
                    else:
                        # Identifiant serveur périmé : la seule issue est de
                        # recréer la station. Question posée UNE fois par synchro.
                        self.logger.warning(
                            "Station %s absente du serveur (HTTP 404) : identifiant "
                            "serveur périmé.", full["id_station"],
                        )
                        if recreate_orphans is None:
                            recreate_orphans = self._ask(
                                "Station absente de GeoNature",
                                "« %s » n'existe plus sur GeoNature (supprimée côté "
                                "serveur) : sa mise à jour est impossible.\n\n"
                                "La recréer comme une nouvelle station ?\n\n"
                                "(la réponse vaut pour toute cette synchronisation ; "
                                "sinon la station reste « à synchroniser » en local)"
                                % self._station_label(full, full["habitats"]),
                            )
                        if not recreate_orphans:
                            orphans_kept += 1
                            continue
                        self.db.detach_from_server(station["id"])
                        full["id_station"] = None
                        full["server_snapshot"] = None
                        for hab in full["habitats"]:
                            hab["id_habitat"] = None
                            hab["unique_id_sinp_hab"] = None
                        recreated = True
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning(
                        "Contrôle serveur ignoré (station %s) : %s",
                        full["id_station"], exc,
                    )
            # Conflit : le serveur a-t-il changé depuis notre dernière synchro de CETTE
            # station ? (empreinte mémorisée ≠ empreinte serveur actuelle).
            if current is not None and full.get("server_snapshot"):
                try:
                    changed = server_fingerprint(*parse_server_station(current)) != full[
                        "server_snapshot"
                    ]
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning(
                        "Contrôle de conflit ignoré (station %s) : %s",
                        full["id_station"], exc,
                    )
                    changed = False
                if changed:
                    self.db.update_station(station["id"], sync_status="conflict")
                    conflicts += 1
                    continue  # ne pas écraser la version serveur
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
                if recreated:
                    orphans_recreated += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.logger.error("Station %s non synchronisée : %s", station["id"], exc)

        parts = []
        if ok or failed:
            parts.append("%d envoyée(s), %d échec(s)" % (ok, failed))
        if orphans_recreated:
            parts.append(
                "dont %d recréée(s) (absente(s) du serveur)" % orphans_recreated
            )
        if deleted or del_failed:
            parts.append("%d supprimée(s), %d échec(s)" % (deleted, del_failed))
        if orphans_kept:
            parts.append(
                "%d absente(s) du serveur, laissée(s) en attente" % orphans_kept
            )
        if conflicts:
            parts.append("%d conflit(s)" % conflicts)
        message = " | ".join(parts) or "rien à faire"
        status = (
            "success" if failed == 0 and del_failed == 0 and not orphans_kept
            else "partial"
        )
        self.db.log_sync("upload", status, message, ok + deleted)
        self.logger.info("Synchronisation : %s", message)
        # Rappel discret : si beaucoup de stations synchronisées anciennes s'accumulent,
        # suggérer le nettoyage (menu « Base locale… »). Seuil pour ne pas harceler.
        purgeable = self.db.count_purgeable_stations()
        hint = (
            " — %d station(s) synchronisée(s) ancienne(s) nettoyable(s) via "
            "« Base locale… »." % purgeable
            if purgeable >= 20 else ""
        )
        if conflicts:
            self.iface.messageBar().pushWarning(
                "OccHab",
                "Synchronisation : %s. %d station(s) modifiée(s) aussi sur GeoNature : "
                "ré-éditez-la puis resynchronisez pour imposer votre version, ou "
                "« Récupérer du serveur » pour prendre la version serveur."
                % (message, conflicts),
            )
        elif orphans_kept:
            self.iface.messageBar().pushWarning(
                "OccHab",
                "Synchronisation : %s. %d station(s) n'existent plus sur GeoNature : "
                "elles restent en local tant qu'elles n'ont pas été recréées."
                % (message, orphans_kept),
            )
        else:
            self.iface.messageBar().pushInfo(
                "OccHab", "Synchronisation : %s.%s" % (message, hint)
            )
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
