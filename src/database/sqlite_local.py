# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Base de données SQLite locale (mode hors-ligne) — miroir du modèle OccHab.

Modèle : station (spatiale) 1→N habitats (non-spatiaux) ; observateurs en
relation N-N ; files d'attente et journal de synchronisation.

**Deux états, à ne pas confondre** :

- `sync_status` — état **technique** vis-à-vis du serveur (`pending`, `synced`,
  `conflict`, `to_delete`).
- `validation_status` — état **métier** du travail du botaniste (`brouillon`,
  `valide`). Les deux sont orthogonaux : une station peut être un brouillon déjà
  synchronisé (la synchro sert aussi de sauvegarde en fin de journée), ou validée
  et en attente d'envoi.

Note : `id_nomenclature_collection_technique` est NOT NULL côté GeoNature. En
local, on stocke ce que l'utilisateur a saisi ; la conformité est (re)vérifiée
au moment de la synchronisation.
"""
import calendar
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
    validation_status TEXT DEFAULT 'brouillon',
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

-- Libellés HABREF déjà obtenus du serveur, par `cd_hab`. C'est un CACHE de
-- données, pas un réglage : sa place est ici, dans la base, et non dans le
-- fichier de configuration — on ne va pas éditer un fichier de préférences à la
-- main pour rafraîchir un nom d'habitat. Il se vide et se recharge (cf.
-- `oublier_libelles_habref`).
CREATE TABLE IF NOT EXISTS habref_libelles (
    cd_hab INTEGER PRIMARY KEY,
    libelle TEXT NOT NULL,
    date_maj TIMESTAMP
);

-- Index des colonnes présentes depuis l'origine. Ceux qui portent sur une
-- colonne ajoutée après coup sont créés dans `_migrate()`, APRÈS l'ALTER TABLE :
-- ici, `CREATE TABLE IF NOT EXISTS` ne touche pas une table existante, donc la
-- colonne n'existerait pas encore et l'ouverture de toute base antérieure
-- échouerait.
CREATE INDEX IF NOT EXISTS idx_stations_sync ON t_stations(sync_status);
CREATE INDEX IF NOT EXISTS idx_habitats_station ON t_habitats(id_station_local);
CREATE INDEX IF NOT EXISTS idx_observers_station ON cor_station_observer(id_station_local);
"""


def _date_months_ago(months, now=None):
    """Date 'YYYY-MM-DD' située `months` mois avant maintenant (jour ramené au mois).

    Comparaison sur la date seule (pas l'heure) : robuste face aux formats et fuseaux
    des timestamps stockés, ce qui suffit largement pour un seuil de rétention.
    """
    ref = now or datetime.now()
    total = ref.year * 12 + (ref.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    day = min(ref.day, calendar.monthrange(year, month)[1])
    return "%04d-%02d-%02d" % (year, month, day)


# État métier d'une station (cf. docstring du module). BROUILLON par défaut :
# une station qui vient d'être créée n'est jamais un travail figé.
BROUILLON = "brouillon"
VALIDE = "valide"
VALIDATION_STATUSES = (BROUILLON, VALIDE)


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
        "created_by", "updated_by", "sync_status", "validation_status",
        "mine", "server_snapshot",
    }
    HABITAT_COLS = {
        "id_habitat", "unique_id_sinp_hab", "cd_hab", "nom_cite", "determiner",
        "recovery_percentage", "technical_precision",
        "id_nomenclature_determination_type", "id_nomenclature_collection_technique",
        "id_nomenclature_abundance", "id_nomenclature_sensitivity",
        "id_nomenclature_community_interest", "sync_status",
    }
    # Journal de synchro : nombre d'entrées conservées (journal, pas archive).
    SYNC_LOG_KEEP = 500
    # Rétention : purge des stations synchronisées non touchées depuis N mois.
    RETENTION_MONTHS = 6

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
        if "validation_status" not in cols:
            # SQLite n'accepte pas de paramètre dans un DEFAULT d'ALTER TABLE :
            # il lui faut un littéral. `BROUILLON` est une constante du module,
            # jamais une saisie utilisateur.
            self.connection.execute(
                "ALTER TABLE t_stations ADD COLUMN validation_status TEXT"
                " DEFAULT '%s'" % BROUILLON  # nosec B608
            )
            # Reprise des données existantes, une seule fois (à l'ajout de la
            # colonne) : ce qui est déjà parti sur GeoNature était considéré
            # comme abouti ; tout le reste est du travail en cours.
            self.connection.execute(
                "UPDATE t_stations SET validation_status = ? WHERE sync_status = 'synced'",
                (VALIDE,),
            )
        # Après l'ALTER : la colonne est garantie, l'index peut être posé.
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_stations_validation"
            " ON t_stations(validation_status)"
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

    def get_all_stations(self, sync_status=None, id_dataset=None):
        self.connect()
        cursor = self.connection.cursor()
        conditions, valeurs = [], []
        if sync_status:
            conditions.append("sync_status = ?")
            valeurs.append(sync_status)
        if id_dataset is not None:
            conditions.append("id_dataset = ?")
            valeurs.append(id_dataset)
        # Colonnes issues d'une liste figée, valeurs paramétrées.
        cursor.execute(
            "SELECT * FROM t_stations%s ORDER BY id DESC"  # nosec B608
            % (" WHERE " + " AND ".join(conditions) if conditions else ""),
            valeurs,
        )
        rows = [dict(r) for r in cursor.fetchall()]
        self.disconnect()
        return rows

    def station_exists(self, station_id):
        """La station existe-t-elle encore ? (une requête, sans ses dépendances)

        L'écriture en lot de la table attributaire porte sur une copie mémoire :
        une station peut avoir été supprimée entre-temps depuis la liste du dock.
        `get_station()` répondrait aussi, mais en trois requêtes et en
        reconstruisant habitats et observateurs pour rien.
        """
        self.connect()
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1 FROM t_stations WHERE id = ?", (station_id,))
            return cursor.fetchone() is not None
        finally:
            self.disconnect()

    def get_stations_full(self, id_dataset=None):
        """Toutes les stations AVEC leurs habitats et observateurs, en 3 requêtes.

        Équivaut à `get_station()` appliqué à chaque station, mais sans le N+1 :
        l'appel par station coûtait 3 requêtes ET 3 ouvertures de connexion, soit
        plusieurs milliers d'allers-retours dès quelques centaines de stations.
        C'est le chargement utilisé par la liste du dock et par la table
        attributaire.

        Args:
            id_dataset: restreindre à un jeu de données (None = tous).

        Returns:
            liste de dicts station, chacun avec ses clés `habitats` et
            `observers` (listes, éventuellement vides), triés comme
            `get_all_stations` (plus récentes d'abord).
        """
        self.connect()
        try:
            cursor = self.connection.cursor()
            if id_dataset is not None:
                cursor.execute(
                    "SELECT * FROM t_stations WHERE id_dataset = ? ORDER BY id DESC",
                    (id_dataset,),
                )
            else:
                cursor.execute("SELECT * FROM t_stations ORDER BY id DESC")
            stations = [dict(row) for row in cursor.fetchall()]
            by_id = {}
            for station in stations:
                station["habitats"] = []
                station["observers"] = []
                by_id[station["id"]] = station
            if not by_id:
                return stations

            # Enfants filtrés côté SQL : un JDD restreint ne doit pas rapatrier
            # les habitats de toute la base.
            for table, key in (("t_habitats", "habitats"),
                               ("cor_station_observer", "observers")):
                if id_dataset is not None:
                    # Nom de table issu d'un littéral du code, jamais d'une saisie.
                    cursor.execute(
                        "SELECT c.* FROM %s c JOIN t_stations s"  # nosec B608
                        " ON s.id = c.id_station_local WHERE s.id_dataset = ?" % table,
                        (id_dataset,),
                    )
                else:
                    cursor.execute("SELECT * FROM %s" % table)  # nosec B608
                for row in cursor.fetchall():
                    station = by_id.get(row["id_station_local"])
                    if station is not None:  # orphelin éventuel : ignoré
                        station[key].append(dict(row))
            return stations
        finally:
            self.disconnect()

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

    # -------------------------------------------------- libellés HABREF
    def libelles_habref(self, cd_habs=None):
        """{cd_hab: libellé} déjà connus, pour ces codes ou pour tous."""
        self.connect()
        cursor = self.connection.cursor()
        if cd_habs:
            codes = [int(c) for c in cd_habs if str(c).lstrip("-").isdigit()]
            if not codes:
                self.disconnect()
                return {}
            # Marqueurs générés d'après le NOMBRE de codes, valeurs paramétrées.
            cursor.execute(
                "SELECT cd_hab, libelle FROM habref_libelles WHERE cd_hab IN (%s)"
                % ",".join("?" * len(codes)),  # nosec B608
                codes,
            )
        else:
            cursor.execute("SELECT cd_hab, libelle FROM habref_libelles")
        libelles = {row["cd_hab"]: row["libelle"] for row in cursor.fetchall()}
        self.disconnect()
        return libelles

    def enregistrer_libelles_habref(self, libelles):
        """Mémoriser {cd_hab: libellé}. Les valeurs vides ne sont pas retenues.

        Ne rien écrire d'incomplet est la règle : un libellé absent sera
        redemandé à la prochaine ouverture, alors qu'une valeur bancale y
        resterait pour toujours.
        """
        propres = {int(k): v.strip() for k, v in (libelles or {}).items()
                   if isinstance(v, str) and v.strip()}
        if not propres:
            return 0
        self.connect()
        self.connection.executemany(
            "INSERT INTO habref_libelles (cd_hab, libelle, date_maj)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT(cd_hab) DO UPDATE SET libelle = excluded.libelle,"
            " date_maj = excluded.date_maj",
            [(cd, libelle, datetime.now().isoformat())
             for cd, libelle in propres.items()],
        )
        self.connection.commit()
        self.disconnect()
        return len(propres)

    def oublier_libelles_habref(self, cd_habs=None):
        """Oublier ces libellés, ou tous : ils seront redemandés au référentiel."""
        self.connect()
        if cd_habs:
            codes = [int(c) for c in cd_habs if str(c).lstrip("-").isdigit()]
            self.connection.executemany(
                "DELETE FROM habref_libelles WHERE cd_hab = ?",
                [(c,) for c in codes],
            )
        else:
            self.connection.execute("DELETE FROM habref_libelles")
        self.connection.commit()
        self.disconnect()

    # ------------------------------------------------------- synchro
    def get_pending_stations(self, id_dataset=None):
        """Stations en attente d'envoi, éventuellement d'un seul jeu de données."""
        return self.get_all_stations(sync_status="pending", id_dataset=id_dataset)

    def set_server_snapshot(self, station_id, snapshot):
        """Mémoriser l'empreinte serveur connue d'une station (détection de conflit)."""
        self.update_station(station_id, server_snapshot=snapshot)

    def detach_from_server(self, station_id):
        """Oublier les identifiants serveur d'une station (et de ses habitats).

        Utilisé quand la station a disparu de GeoNature (supprimée côté serveur) :
        les id_station/id_habitat mémorisés ne pointent plus sur rien et une mise
        à jour échouerait. Après appel, la prochaine synchronisation la CRÉE.
        Les uuid SINP sont eux aussi oubliés : le serveur en attribuera de
        nouveaux à la re-création.
        """
        self.connect()
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE t_stations SET id_station = NULL, unique_id_sinp_station = NULL,"
            " server_snapshot = NULL WHERE id = ?",
            (station_id,),
        )
        cursor.execute(
            "UPDATE t_habitats SET id_habitat = NULL, unique_id_sinp_hab = NULL"
            " WHERE id_station_local = ?",
            (station_id,),
        )
        self.connection.commit()
        self.disconnect()

    def mark_station_synced(self, station_id, id_station, status="synced",
                            server_snapshot=None):
        fields = {
            "id_station": id_station,
            "sync_status": status,
            # Station envoyée : le tampon d'annulation de géométrie (« Rétablir la
            # géométrie précédente ») devient caduc. On le libère pour ne pas garder
            # à vie une copie de géométrie par station synchronisée.
            "prev_geom": None,
            "prev_geom_type": None,
        }
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
        # Ne conserver que les SYNC_LOG_KEEP entrées les plus récentes (id auto-incrémenté)
        # pour borner la croissance du journal.
        cursor.execute(
            "DELETE FROM t_sync_log WHERE id NOT IN ("
            "SELECT id FROM t_sync_log ORDER BY id DESC LIMIT ?)",
            (self.SYNC_LOG_KEEP,),
        )
        self.connection.commit()
        self.disconnect()

    # ------------------------------------------------------- rétention / purge
    def _purgeable_station_ids(self, months):
        """Ids des stations synchronisées non touchées depuis `months` mois.

        Uniquement `sync_status = 'synced'` : toute édition locale (attributs ou
        géométrie) repasse une station en 'pending', donc 'synced' = non modifiée
        depuis la synchro. Ancienneté mesurée sur `date_update` (dernière écriture
        locale), comparée sur la date seule.
        """
        cutoff = _date_months_ago(months)
        self.connect()
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT id FROM t_stations WHERE sync_status = 'synced' "
            "AND substr(COALESCE(date_update, date_creation), 1, 10) <= ?",
            (cutoff,),
        )
        ids = [row[0] for row in cursor.fetchall()]
        self.disconnect()
        return ids

    def count_purgeable_stations(self, months=None):
        """Nombre de stations purgeables (cf. `_purgeable_station_ids`)."""
        if months is None:
            months = self.RETENTION_MONTHS
        return len(self._purgeable_station_ids(months))

    def purge_synced_stations(self, months=None):
        """Retirer du local les stations synchronisées non touchées depuis `months`
        mois (cascade habitats + observateurs), puis VACUUM. Retourne le nombre retiré.

        Ne touche JAMAIS aux stations 'pending' / 'conflict' / 'to_delete' : seules
        les copies déjà synchronisées — re-récupérables via « Récupérer du serveur » —
        sont concernées.
        """
        if months is None:
            months = self.RETENTION_MONTHS
        ids = self._purgeable_station_ids(months)
        for station_id in ids:
            self.delete_station(station_id)  # cascade habitats + observateurs
        if ids:
            self.connect()
            self.connection.execute("VACUUM")  # rendre l'espace libéré au système
            self.disconnect()
        return len(ids)
