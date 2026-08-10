# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialogues de saisie : une station et ses habitats (création et édition)."""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..processing.duplicate import habitat_reprise, paste_fields, station_template
from .dialog_size import ajuster_a_l_ecran, rendre_defilant
from .habitat_form import HabitatForm
from .station_form import StationForm

# Identifiants serveur à préserver quand on rééedite un habitat déjà synchronisé
# (pour une synchro en mise à jour et non en re-création).
_HAB_KEEP_KEYS = ("id_habitat", "unique_id_sinp_hab")


class _FormDialog(QDialog):
    """Enveloppe un formulaire (`.validate()` / `.get_data()`) dans un OK / Annuler."""

    #: Taille d'ouverture SOUHAITÉE, bornée ensuite à l'écran. Sans elle, la
    #: fenêtre s'ouvre à son `sizeHint()` — lequel a fondu quand on a borné la
    #: largeur des listes déroulantes, au point d'imposer un double défilement.
    TAILLE_VOULUE = (720, 780)

    def __init__(self, form, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.form = form
        layout = QVBoxLayout(self)
        # Le formulaire défile ; les boutons restent hors de la zone défilante,
        # donc toujours atteignables même sur un petit écran.
        layout.addWidget(rendre_defilant(form), 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def showEvent(self, event):
        super().showEvent(event)
        ajuster_a_l_ecran(self, *self.TAILLE_VOULUE)

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
                 habref_detail=None, habref_typologies=None, observers=None, current_observer=None,
                 user_names=None, default_determiner=None, datasets=None,
                 geo_metrics=None, station_defaults=None, habitat_defaults=None,
                 abundance_cover_map=None, batch_count=0, template=None,
                 last_observers=None, last_dates=None, habref_cd_typo=None,
                 last_habitat=None, station_picker=None, parent=None):
        super().__init__(parent)
        # Habitat de la saisie précédente : pré-remplit chaque NOUVEL habitat
        # (cf. `HabitatForm`), jamais l'édition d'un habitat existant.
        self.last_habitat = last_habitat or None
        # Callable() -> station complète choisie par l'utilisateur, ou None.
        # Fourni par le dock (il seul a la base) ; absent → bouton masqué.
        self._station_picker = station_picker
        # Typologie HABREF de la dernière saisie, reprise puis renvoyée à
        # l'appelant qui la persiste (même principe que les observateurs).
        self.habref_cd_typo = habref_cd_typo
        self.config = config
        self.station = station  # dict existant → mode édition
        # dict SANS identifiants (cf. processing.duplicate) → mode duplication :
        # on pré-remplit comme en édition mais on CRÉE une nouvelle station.
        self.template = template if station is None else None
        # Reprise de la saisie précédente : création vierge uniquement.
        pure_creation = station is None and self.template is None
        self.last_observers = last_observers if pure_creation else None
        self.last_dates = last_dates if pure_creation else None
        # >0 → création en lot : ce formulaire fournit les métadonnées COMMUNES à
        # `batch_count` stations (une par géométrie sélectionnée). Nom laissé vide,
        # géométrie/surface/altitude propres à chacune (renseignées par l'appelant).
        self.batch_count = batch_count or 0
        self.datasets = datasets or []
        self.geo_metrics = geo_metrics
        self.station_defaults = station_defaults or {}
        self.habitat_defaults = habitat_defaults or {}
        self.abundance_cover_map = abundance_cover_map or {}
        self.station_nomenclatures = station_nomenclatures or {}
        self.habitat_nomenclatures = habitat_nomenclatures or {}
        self.habref_search = habref_search
        self.habref_detail = habref_detail
        self.habref_typologies = habref_typologies or []
        self.observers = observers or []
        self.current_observer = current_observer
        self.user_names = user_names or []
        self.default_determiner = default_determiner

        # En édition, la géométrie et les habitats viennent de la station existante.
        # En duplication, les habitats sont copiés mais la géométrie est la nouvelle.
        if station is not None:
            self.geom_wkt = geom_wkt if geom_wkt is not None else station.get("geom")
            self.geom_type = geom_type if geom_type is not None else station.get("geom_type")
            self.habitats = [dict(h) for h in station.get("habitats", [])]
        else:
            self.geom_wkt = geom_wkt
            self.geom_type = geom_type
            self.habitats = [dict(h) for h in (self.template or {}).get("habitats", [])]

        if station is not None:
            title = "Modifier la station"
        elif self.template is not None:
            title = "Nouvelle station OccHab (copie)"
        elif self.batch_count:
            title = "Nouvelles stations OccHab (lot)"
        else:
            title = "Nouvelle station OccHab"
        self.setWindowTitle(title)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        # Tout le contenu va dans une zone défilante ; seuls les boutons de
        # validation restent ancrés en bas (cf. `dialog_size`).
        contenu = QWidget()
        corps = QVBoxLayout(contenu)
        corps.setContentsMargins(0, 0, 0, 0)

        if self.batch_count:
            banner = QLabel(
                "%d stations seront créées depuis la sélection.\n"
                "Ces métadonnées sont communes à toutes ; chaque station conserve "
                "sa propre géométrie (surface et altitude calculées automatiquement) "
                "et son nom reste vide — à renseigner ensuite si besoin.\n"
                "L'habitat est facultatif : un habitat ajouté ici est appliqué à "
                "toutes les stations du lot." % self.batch_count
            )
            banner.setWordWrap(True)
            banner.setStyleSheet(
                "QLabel { background: #fff8e1; padding: 6px; "
                "border: 1px solid #ffe082; border-radius: 3px; }"
            )
            corps.addWidget(banner)

        # Recopier une station déjà renseignée SANS quitter le formulaire :
        # le cas courant est « ce polygone-ci est comme celui d'à côté », et il
        # se présente aussi bien en création qu'en édition d'une station déjà
        # tracée, que la duplication (qui exige de redessiner) ne couvre pas.
        if self._station_picker is not None:
            ligne_copie = QHBoxLayout()
            self.btn_reprendre = QPushButton("Reprendre une station renseignée…")
            self.btn_reprendre.setToolTip(
                "Recopier ici les renseignements et les habitats d'une autre "
                "station. La géométrie, le nom et le statut de CETTE station ne "
                "changent pas. Rien n'est enregistré avant « OK »."
            )
            self.btn_reprendre.clicked.connect(self._reprendre_station)
            ligne_copie.addWidget(self.btn_reprendre)
            ligne_copie.addStretch(1)
            corps.addLayout(ligne_copie)

        self.station_form = StationForm(
            self.config,
            self.station_nomenclatures,
            observers=self.observers,
            current_observer=self.current_observer,
            datasets=self.datasets,
            defaults=self.station_defaults,
            last_observers=self.last_observers,
            last_dates=self.last_dates,
        )
        if self.station is not None:
            self.station_form.set_data(self.station)
        elif self.template is not None:
            self.station_form.set_data(self.template, repris=True)
        self.station_form.set_geometry(self.geom_wkt, self.geom_type, self.geo_metrics)
        if self.batch_count:  # nom propre à chaque station → laissé vide en lot
            self.station_form.edit_name.setEnabled(False)
            self.station_form.edit_name.setPlaceholderText("Laissé vide (création en lot)")
        corps.addWidget(self.station_form)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        corps.addWidget(separator)

        # Libellé long : sans retour à la ligne il imposait sa largeur entière
        # à la fenêtre, qui devait alors défiler horizontalement.
        legende = QLabel(
            "Habitats de la station (double-clic pour éditer ; "
            "Ctrl/Maj pour en sélectionner plusieurs) :"
        )
        legende.setWordWrap(True)
        corps.addWidget(legende)
        # Deux colonnes : le nom cité à gauche, le recouvrement aligné à droite.
        # Le cd_hab n'y figure plus — il est déjà dans le formulaire de l'habitat
        # et n'aide pas à relire une station d'un coup d'œil.
        self.list_habitats = QTreeWidget()
        self.list_habitats.setColumnCount(2)
        self.list_habitats.setHeaderLabels(["Habitat (nom cité)", "Recouvrement"])
        self.list_habitats.setRootIsDecorated(False)
        self.list_habitats.setUniformRowHeights(True)
        entete = self.list_habitats.header()
        # Sans cela, la DERNIÈRE colonne s'étire par défaut et avale la place :
        # « Recouvrement » occupait 374 px pendant que le nom cité était rogné.
        entete.setStretchLastSection(False)
        entete.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        entete.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        # Multi-sélection (Ctrl/Maj) pour retirer plusieurs habitats d'un coup.
        self.list_habitats.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.list_habitats.itemDoubleClicked.connect(
            lambda item, _c: self._edit_habitat(
                self.list_habitats.indexOfTopLevelItem(item)
            )
        )
        corps.addWidget(self.list_habitats)

        # Somme des recouvrements : l'exigence N2000 est 100 % par polygone, et
        # jusqu'ici il fallait additionner de tête habitat par habitat.
        self.label_recouvrement = QLabel()
        self.label_recouvrement.setWordWrap(True)
        corps.addWidget(self.label_recouvrement)
        self._rafraichir_habitats()

        row = QHBoxLayout()
        btn_add = QPushButton("Ajouter un habitat")
        btn_add.clicked.connect(self.add_habitat)
        btn_remove = QPushButton("Retirer")
        btn_remove.clicked.connect(self.remove_habitat)
        row.addWidget(btn_add)
        row.addWidget(btn_remove)
        row.addStretch(1)
        corps.addLayout(row)

        layout.addWidget(rendre_defilant(contenu), 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    #: Cf. `_FormDialog.TAILLE_VOULUE` : la station porte en plus la liste des
    #: habitats, d'où une fenêtre un peu plus haute.
    TAILLE_VOULUE = (780, 860)

    def showEvent(self, event):
        super().showEvent(event)
        ajuster_a_l_ecran(self, *self.TAILLE_VOULUE)

    # --------------------------------------------- reprendre une autre station
    def _reprendre_station(self):
        """Recopier dans ce formulaire les renseignements d'une autre station.

        Ce qui appartient à CETTE station n'est pas touché : sa géométrie (le
        formulaire ne la relit pas), son nom et son statut de validation, qu'on
        repose explicitement après coup — sans quoi une station validée
        retomberait en brouillon pour avoir copié son voisin.
        """
        source = self._station_picker()
        if not source:
            return
        template = station_template(source)
        habitats = [dict(h) for h in template.get("habitats") or []]
        if self.habitats and not self._confirmer_remplacement_habitats(habitats):
            return
        donnees = paste_fields(template)
        donnees["observers"] = template.get("observers") or []
        donnees["station_name"] = self.station_form.edit_name.text()
        donnees["validation_status"] = self.station_form.combo_statut.currentData()
        self.station_form.set_data(
            donnees,
            repris=True,
            message=(
                "↺ Renseignements repris de « %s » — vérifiez les dates. Le nom, "
                "la géométrie et le statut de cette station sont inchangés."
                % (source.get("station_name") or "station sans nom")
            ),
        )
        self.habitats = habitats
        self._rafraichir_habitats()

    def _confirmer_remplacement_habitats(self, nouveaux):
        """Prévenir avant d'écraser les habitats déjà saisis. True si on continue."""
        reponse = QMessageBox.question(
            self,
            "Reprendre une station",
            "Cette station porte déjà %d habitat(s).\n\n"
            "Les reprendre depuis l'autre station les REMPLACERA par ses %d "
            "habitat(s). Continuer ?" % (len(self.habitats), len(nouveaux)),
        )
        return reponse == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------ habitats
    #: Au-delà, la liste défile : une station en mosaïque dépasse rarement 10
    #: habitats, et une fenêtre sans fin serait pire que le défilement.
    LIGNES_VISIBLES_MAX = 10
    RECOUVREMENT_TOTAL = 100

    @staticmethod
    def _habitat_label(habitat):
        """Nom cité seul — utilisé aussi par les messages de confirmation."""
        return habitat.get("nom_cite") or "habitat sans nom"

    @staticmethod
    def _recouvrement_texte(habitat):
        recouvrement = habitat.get("recovery_percentage")
        if isinstance(recouvrement, (int, float)) and recouvrement:  # 0/None = vide
            return "%g %%" % recouvrement
        return "—"

    def _rafraichir_habitats(self):
        """Reconstruire la liste, ajuster sa hauteur et le total des recouvrements."""
        self.list_habitats.clear()
        for habitat in self.habitats:
            item = QTreeWidgetItem([
                self._habitat_label(habitat), self._recouvrement_texte(habitat)
            ])
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            self.list_habitats.addTopLevelItem(item)
        self._ajuster_hauteur_habitats()
        self._maj_total_recouvrement()

    def _ajuster_hauteur_habitats(self):
        """Montrer tous les habitats sans défilement, dans la limite fixée."""
        lignes = max(1, min(len(self.habitats) or 1, self.LIGNES_VISIBLES_MAX))
        hauteur_ligne = self.list_habitats.sizeHintForRow(0) if self.habitats else 22
        if hauteur_ligne <= 0:
            hauteur_ligne = 22
        entete = self.list_habitats.header().height()
        hauteur = lignes * hauteur_ligne + entete + 2 * self.list_habitats.frameWidth()
        self.list_habitats.setMinimumHeight(hauteur)
        self.list_habitats.setMaximumHeight(hauteur)

    def _maj_total_recouvrement(self):
        """Afficher la somme des recouvrements, colorée selon l'exigence N2000."""
        valeurs = [
            h.get("recovery_percentage") for h in self.habitats
            if isinstance(h.get("recovery_percentage"), (int, float))
            and h.get("recovery_percentage")
        ]
        if not valeurs:
            # Ne rien renseigner n'est pas une erreur : une saisie peut être en
            # cours. On le dit sans alarmer.
            self.label_recouvrement.setText("Recouvrement non renseigné.")
            self.label_recouvrement.setStyleSheet("color: palette(mid);")
            return
        total = sum(valeurs)
        if abs(total - self.RECOUVREMENT_TOTAL) < 0.01:
            self.label_recouvrement.setText("Total : 100 %  ✓")
            self.label_recouvrement.setStyleSheet("color: #1b5e20; font-weight: 600;")
            return
        ecart = self.RECOUVREMENT_TOTAL - total
        manque = ("il manque %g %%" % ecart if ecart > 0
                  else "dépassement de %g %%" % -ecart)
        self.label_recouvrement.setText("Total : %g %%  —  %s" % (total, manque))
        self.label_recouvrement.setStyleSheet("color: #b26a00; font-weight: 600;")

    def _new_habitat_form(self, reprise=False):
        """Formulaire d'habitat. `reprise` : pré-remplir avec la saisie précédente.

        Réservé à l'AJOUT d'un habitat : à l'édition, les valeurs de l'habitat
        font autorité et une reprise viendrait les écraser.
        """
        form = HabitatForm(
            self.habitat_nomenclatures,
            self.habref_search,
            habref_detail=self.habref_detail,
            typologies=self.habref_typologies,
            user_names=self.user_names,
            default_determiner=self.default_determiner,
            defaults=self.habitat_defaults,
            abundance_cover_map=self.abundance_cover_map,
            cd_typo=self.habref_cd_typo,
            last_habitat=self.last_habitat if reprise else None,
        )
        # Le prochain habitat de CETTE station reprend la typologie qu'on vient
        # de choisir, sans attendre l'enregistrement.
        form.habref.combo_typo.currentIndexChanged.connect(
            lambda _i, f=form: setattr(self, "habref_cd_typo", f.habref.typologie())
        )
        return form

    def add_habitat(self):
        # Le dernier habitat SAISI ici fait autorité sur celui de la station
        # précédente : dans une mosaïque, les habitats d'un même polygone se
        # ressemblent davantage encore.
        if self.habitats:
            self.last_habitat = habitat_reprise(self.habitats[-1])
        dialog = _FormDialog(
            self._new_habitat_form(reprise=True), "Nouvel habitat", self
        )
        if dialog.exec():
            data = dialog.get_data()
            self.habitats.append(data)
            self._rafraichir_habitats()

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
            self._rafraichir_habitats()

    def remove_habitat(self):
        rows = sorted(
            {self.list_habitats.indexOfTopLevelItem(item)
             for item in self.list_habitats.selectedItems()},
            reverse=True,  # décroissant → les indices restent valides pendant la suppression
        )
        if not rows:
            QMessageBox.information(
                self, "OccHab", "Sélectionnez un ou plusieurs habitats à retirer."
            )
            return
        if len(rows) == 1:
            question = ("Retirer l'habitat « %s » de la station ?"
                        % self._habitat_label(self.habitats[rows[0]]))
        else:
            question = "Retirer les %d habitats sélectionnés de la station ?" % len(rows)
        if QMessageBox.question(self, "Retirer l'habitat", question) != QMessageBox.StandardButton.Yes:
            return
        for row in rows:
            del self.habitats[row]
        self._rafraichir_habitats()

    # --------------------------------------------------------------- OK
    def _on_ok(self):
        ok, msg = self.station_form.validate()
        if not ok:
            QMessageBox.warning(self, "Validation", msg)
            return
        # L'habitat est facultatif : on peut créer une station (géométrie d'abord),
        # puis la qualifier plus tard. Voir README §création sans habitat.
        self.accept()

    def get_result(self):
        """Retourne (données_station, [données_habitats])."""
        return self.station_form.get_data(), list(self.habitats)
