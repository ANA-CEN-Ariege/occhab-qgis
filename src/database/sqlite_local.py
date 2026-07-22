# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Base de données SQLite locale (mode hors-ligne) — miroir du modèle OccHab.

Modèle : station (spatiale) 1→N habitats (non-spatiaux) ; observateurs en
relation N-N ; files d'attente et journal de synchronisation.

Note : `id_nomenclature_collection_technique` est NOT NULL côté GeoNature. En
local, on stocke ce que l'utilisateur a saisi ; la conformité est (re)vérifiée
au moment de la synchronisation.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS t_stations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_station INTEGER,
    unique_id_sinp_station TEXT,
    id_dataset INTEGER NOT NULL,
    station_name TEXT,
    date_min TEXT,
    date_max TEXT,
    observers_txt TEXT,
    altitude_min INTEGER,
    altitude_max INTEGER,
    depth_min INTEGER,
    depth_max INTEGER,
    area INTEGER,
    comment TEXT,
    geom TEXT,
    geom_type TEXT,
    prev_geom TEXT,
    prev_geom_type TEXT,
    id_nomenclature_geographic_object INTEGER,
    id_nomenclature_exposure INTEGER,
    id_nomenclature_type_sol INTEGER,
    id_nomenclature_area_surface_calculation INTEGER,
    id_nomenclature_type_mosaique_habitat INTEGER,
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    date_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sync_status TEXT DEFAULT 'pending',
    sync_date TIMESTAMP,
    created_by TEXT,
    updated_by TEXT,
    mine INTEGER DEFAULT 1,
    server_snapshot TEXT,
    UNIQUE(unique_id_sinp_station)
);

CREATE TABLE IF NOT EXISTS t_habitats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_habitat INTEGER,
    id_station_local INTEGER NOT NULL,
    unique_id_sinp_hab TEXT,
    cd_hab INTEGER NOT NULL,
    nom_cite TEXT NOT NULL,
    determiner TEXT,
    recovery_percentage REAL,
    technical_precision TEXT,
    id_nomenclature_determination_type INTEGER,
    id_nomenclature_collection_technique INTEGER,
    id_nomenclature_abundance INTEGER,
    id_nomenclature_sensitivity INTEGER,
    id_nomenclature_community_interest INTEGER,
    sync_status TEXT DEFAULT 'pending',
    FOREIGN KEY(id_station_local) REFERENCES t_stations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cor_station_observer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_station_local INTEGER NOT NULL,
    id_role INTEGER,
    observer_name TEXT,
    FOREIGN KEY(id_station_local) REFERENCES t_stations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS t_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_sync TIMESTAMP,
    direction TEXT,
    status TEXT,
    message TEXT,
    records_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_stations_sync ON t_stations(sync_status);
CREATE INDEX IF NOT EXISTS idx_habitats_station ON t_habitats(id_station_local);
"""


class OccHabDatabase:
    """Accès CRUD à la base SQLite locale."""

    STATION_COLS = {
        "id_station", "unique_id_sinp_station", "id_dataset", "station_name",
        "date_min", "date_max", "observers_txt", "altitude_min", "altitude_max",
        "depth_min", "depth_max", "area", "comment", "geom", "geom_type",
        "prev_geom", "prev_geom_type",
        "id_nomenclature_geographic_object", "id_nomenclature_exposure",
        "id_nomenclature_type_sol", "id_nomenclature_area_surface_calculation",
        "id_nomenclature_type_mosaique_habitat",
        "created_by", "updated_by", "sync_status", "mine", "server_snapshot",
    }
    HABITAT_COLS = {
        "id_habitat", "unique_id_sinp_hab", "cd_hab", "nom_cite", "determiner",
        "recovery_percentage", "technical_precision",
        "id_nomenclature_determination_type", "id_nomenclature_collection_technique",
        "id_nomenclature_abundance", "id_nomenclature_sensitivity",
        "id_nomenclature_community_interest", "sync_status",
    }

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = None
        self.init_database()

    # ---------------------------------------------------------- connexion
    def connect(self):
        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        return self.connection

    def disconnect(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def init_database(self):
        self.connect()
        self.connection.executescript(_SCHEMA)
        self._migrate()
        self.connection.commit()
        self.disconnect()

    def _migrate(self):
        """Migrations légères pour les bases créées avant certaines colonnes."""
        cols = [r[1] for r in self.connection.execute("PRAGMA table_info(t_stations)")]
        if "mine" not in cols:
            self.connection.execute(
                "ALTER TABLE t_stations ADD COLUMN mine INTEGER DEFAULT 1"
            )
        if "server_snapshot" not in cols:
            self.connection.execute(
                "ALTER TABLE t_stations ADD COLUMN server_snapshot TEXT"
            )
        if "prev_geom" not in cols:
            self.connection.execute("ALTER TABLE t_stations ADD COLUMN prev_geom TEXT")
        if "prev_geom_type" not in cols:
            self.connection.execute(
                "ALTER TABLE t_stations ADD COLUMN prev_geom_type TEXT"
            )

    # --------------------------------------------------------- stations
    def create_station(self, **fields):
        """Créer une station. `id_dataset` est obligatoire. Retourne l'id local."""
        data = {k: v for k, v in fields.items() if k in self.STATION_COLS}
        if not data.get("id_dataset"):
            raise ValueError("id_dataset (JDD) est obligatoire")
        data.setdefault("sync_status", "pending")

        self.connect()
        cursor = self.connection.cursor()
        cols = list(data.keys())
        # Noms de colonnes issus d'une whitelist figée (STATION_COLS) ; valeurs
        # toujours paramétrées (?). Aucune donnée utilisateur dans le SQL.
        cursor.execute(
            "INSERT INTO t_stations (%s) VALUES (%s)"  # nosec B608
            % (", ".join(cols), ", ".join(["?"] * len(cols))),
            [data[c] for c in cols],
        )
        self.connection.commit()
        station_id = cursor.lastrowid
        self.disconnect()
        return station_id

    def get_station(self, station_id):
        """Récupérer une station avec ses habitats et observateurs."""
        self.connect()
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM t_stations WHERE id = ?", (station_id,))
        row = cursor.fetchone()
        if row is None:
            self.disconnect()
            return None
        station = dict(row)
        cursor.execute(
            "SELECT * FROM t_habitats WHERE id_station_local = ?", (station_id,)
        )
        station["habitats"] = [dict(r) for r in cursor.fetchall()]
        cursor.execute(
            "SELECT * FROM cor_station_observer WHERE id_station_local = ?",
            (station_id,),
        )
        station["observers"] = [dict(r) for r in cursor.fetchall()]
        self.disconnect()
        return station

    def find_by_id_station(self, id_station):
        """Station locale ayant cet id_station GeoNature, ou None."""
        if not id_station:
            return None
        self.connect()
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM t_stations WHERE id_station = ?", (id_station,))
        row = cursor.fetchone()
        self.disconnect()
        return dict(row) if row else None

    def get_all_stations(self, sync_status=None):
        self.connect()
        cursor = self.connection.cursor()
        if sync_status:
            cursor.execute(
                "SELECT * FROM t_stations WHERE sync_status = ? ORDER BY id DESC",
                (sync_status,),
            )
        else:
            cursor.execute("SELECT * FROM t_stations ORDER BY id DESC")
        rows = [dict(r) for r in cursor.fetchall()]
        self.disconnect()
        return rows

    def update_station(self, station_id, **fields):
        data = {k: v for k, v in fields.items() if k in self.STATION_COLS}
        data["date_update"] = datetime.now().isoformat()
        self.connect()
        cursor = self.connection.cursor()
        assignments = ", ".join("%s = ?" % k for k in data)
        # Colonnes (assignments) issues d'une whitelist figée (STATION_COLS) ;
        # valeurs paramétrées (?). Aucune donnée utilisateur dans le SQL.
        cursor.execute(
            "UPDATE t_stations SET %s WHERE id = ?" % assignments,  # nosec B608
            list(data.values()) + [station_id],
        )
        self.connection.commit()
        self.disconnect()

    def delete_station(self, station_id):
        """Supprimer une station et, en cascade, ses habitats et observateurs."""
        self.connect()
        cursor = self.connection.cursor()
        # Cascade explicite (au cas où les FK ne seraient pas actives).
        cursor.execute(
            "DELETE FROM t_habitats WHERE id_station_local = ?", (station_id,)
        )
        cursor.execute(
            "DELETE FROM cor_station_observer WHERE id_station_local = ?",
            (station_id,),
        )
        cursor.execute("DELETE FROM t_stations WHERE id = ?", (station_id,))
        self.connection.commit()
        self.disconnect()

    # --------------------------------------------------------- habitats
    def _insert_habitat(self, cursor, id_station_local, fields):
        """Insérer un habitat via un curseur existant, SANS commit. Retourne l'id.

        Ne conserve que les colonnes habitat valides (HABITAT_COLS) : cela écarte
        automatiquement id_station_local et id éventuellement présents dans `fields`
        (ex. dicts issus de get_station), qui sinon entreraient en conflit.
        """
        data = {k: v for k, v in fields.items() if k in self.HABITAT_COLS}
        if not data.get("cd_hab"):
            raise ValueError("cd_hab est obligatoire")
        if not data.get("nom_cite"):
            raise ValueError("nom_cite est obligatoire")
        data["id_station_local"] = id_station_local
        data.setdefault("sync_status", "pending")
        cols = list(data.keys())
        # Noms de colonnes issus d'une whitelist figée (HABITAT_COLS) ; valeurs
        # toujours paramétrées (?). Aucune donnée utilisateur dans le SQL.
        cursor.execute(
            "INSERT INTO t_habitats (%s) VALUES (%s)"  # nosec B608
            % (", ".join(cols), ", ".join(["?"] * len(cols))),
            [data[c] for c in cols],
        )
        return cursor.lastrowid

    def add_habitat(self, id_station_local, **fields):
        """Ajouter un habitat à une station. cd_hab et nom_cite obligatoires."""
        self.connect()
        try:
            cursor = self.connection.cursor()
            habitat_id = self._insert_habitat(cursor, id_station_local, fields)
            self.connection.commit()
        finally:
            self.disconnect()
        return habitat_id

    def replace_habitats(self, id_station_local, habitats):
        """Remplacer atomiquement tous les habitats d'une station.

        DELETE + ré-insertions dans UNE SEULE transaction : si une insertion
        échoue, tout est annulé (rollback) et les habitats existants ne sont PAS
        perdus. `sync_status` est retiré pour que la ré-insertion repasse en
        'pending'.
        """
        self.connect()
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "DELETE FROM t_habitats WHERE id_station_local = ?", (id_station_local,)
            )
            for habitat in habitats:
                clean = {k: v for k, v in habitat.items() if k != "sync_status"}
                self._insert_habitat(cursor, id_station_local, clean)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            self.disconnect()

    # ------------------------------------------------------- observateurs
    def replace_observers(self, id_station_local, observers):
        """Remplacer les observateurs d'une station (suppression puis ré-insertion)."""
        self.connect()
        self.connection.execute(
            "DELETE FROM cor_station_observer WHERE id_station_local = ?",
            (id_station_local,),
        )
        self.connection.commit()
        self.disconnect()
        for obs in observers:
            self.add_observer(
                id_station_local,
                observer_name=obs.get("observer_name"),
                id_role=obs.get("id_role"),
            )

    def add_observer(self, id_station_local, observer_name=None, id_role=None):
        self.connect()
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO cor_station_observer (id_station_local, id_role, observer_name)"
            " VALUES (?, ?, ?)",
            (id_station_local, id_role, observer_name),
        )
        self.connection.commit()
        self.disconnect()

    # ------------------------------------------------------- synchro
    def get_pending_stations(self):
        return self.get_all_stations(sync_status="pending")

    def set_server_snapshot(self, station_id, snapshot):
        """Mémoriser l'empreinte serveur connue d'une station (détection de conflit)."""
        self.update_station(station_id, server_snapshot=snapshot)

    def mark_station_synced(self, station_id, id_station, status="synced",
                            server_snapshot=None):
        fields = {"id_station": id_station, "sync_status": status}
        if server_snapshot is not None:
            fields["server_snapshot"] = server_snapshot
        self.update_station(station_id, **fields)
        self.connect()
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE t_stations SET sync_date = ? WHERE id = ?",
            (datetime.now().isoformat(), station_id),
        )
        self.connection.commit()
        self.disconnect()

    def log_sync(self, direction, status, message="", records_count=0):
        self.connect()
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO t_sync_log (date_sync, direction, status, message, records_count)"
            " VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), direction, status, message, records_count),
        )
        self.connection.commit()
        self.disconnect()
