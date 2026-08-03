# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de la base SQLite locale (CRUD + machine à états de synchro)."""
import os
from datetime import datetime

import pytest

import sqlite_local as db_mod


def _make_db(tmp_path):
    return db_mod.OccHabDatabase(os.path.join(str(tmp_path), "occhab_test.db"))


def test_create_and_get_station(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(
        id_dataset=3, station_name="S", geom="POINT (1 2)", geom_type="point"
    )
    assert station_id is not None
    full = db.get_station(station_id)
    assert full["station_name"] == "S"
    assert full["sync_status"] == "pending"  # défaut
    assert full["habitats"] == []
    assert full["observers"] == []


def test_create_requires_dataset(tmp_path):
    db = _make_db(tmp_path)
    with pytest.raises(ValueError):
        db.create_station(station_name="sans jdd")


def test_habitats_and_observers(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3)
    db.add_habitat(station_id, cd_hab=10, nom_cite="h1")
    db.add_observer(station_id, observer_name="Roy", id_role=5)
    full = db.get_station(station_id)
    assert len(full["habitats"]) == 1
    assert full["habitats"][0]["nom_cite"] == "h1"
    assert full["observers"][0]["id_role"] == 5


def test_add_habitat_requires_fields(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3)
    with pytest.raises(ValueError):
        db.add_habitat(station_id, nom_cite="sans cd_hab")


def test_replace_habitats_atomic(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3)
    db.add_habitat(station_id, cd_hab=10, nom_cite="h1")
    db.replace_habitats(
        station_id,
        [{"cd_hab": 20, "nom_cite": "h2"}, {"cd_hab": 30, "nom_cite": "h3"}],
    )
    full = db.get_station(station_id)
    assert sorted(h["nom_cite"] for h in full["habitats"]) == ["h2", "h3"]


def test_update_station(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3)
    db.update_station(station_id, station_name="renommée", sync_status="synced")
    full = db.get_station(station_id)
    assert full["station_name"] == "renommée"
    assert full["sync_status"] == "synced"


def test_pending_and_mark_synced(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3)
    assert [s["id"] for s in db.get_pending_stations()] == [station_id]

    db.mark_station_synced(station_id, id_station=99, server_snapshot="abc")

    assert db.get_pending_stations() == []
    full = db.get_station(station_id)
    assert full["id_station"] == 99
    assert full["sync_status"] == "synced"
    assert full["server_snapshot"] == "abc"
    assert full["sync_date"] is not None


def test_detach_from_server(tmp_path):
    # Station supprimée sur GeoNature : on oublie les identifiants serveur pour
    # que la prochaine synchro la recrée au lieu de tenter une mise à jour vaine.
    db = _make_db(tmp_path)
    station_id = db.create_station(
        id_dataset=3, id_station=79, unique_id_sinp_station="uuid-station",
        server_snapshot="empreinte",
    )
    db.add_habitat(
        station_id, cd_hab=10, nom_cite="h1", id_habitat=42,
        unique_id_sinp_hab="uuid-hab",
    )

    db.detach_from_server(station_id)

    full = db.get_station(station_id)
    assert full["id_station"] is None
    assert full["unique_id_sinp_station"] is None
    assert full["server_snapshot"] is None
    assert full["sync_status"] == "pending"  # toujours à envoyer
    assert full["habitats"][0]["id_habitat"] is None
    assert full["habitats"][0]["unique_id_sinp_hab"] is None
    assert full["habitats"][0]["nom_cite"] == "h1"  # données locales intactes


def test_find_by_id_station(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3, id_station=77)
    found = db.find_by_id_station(77)
    assert found["id"] == station_id
    assert db.find_by_id_station(12345) is None
    assert db.find_by_id_station(None) is None


def test_delete_cascade(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3)
    db.add_habitat(station_id, cd_hab=10, nom_cite="h")
    db.add_observer(station_id, observer_name="R", id_role=1)
    db.delete_station(station_id)
    assert db.get_station(station_id) is None


def test_prev_geom_roundtrip(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(
        id_dataset=3, geom="POINT (1 2)", geom_type="point"
    )
    db.update_station(station_id, prev_geom="POINT (9 9)", prev_geom_type="point")
    full = db.get_station(station_id)
    assert full["prev_geom"] == "POINT (9 9)"
    assert full["prev_geom_type"] == "point"


def test_set_server_snapshot(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3)
    db.set_server_snapshot(station_id, "fp123")
    assert db.get_station(station_id)["server_snapshot"] == "fp123"
    db.set_server_snapshot(station_id, None)
    assert db.get_station(station_id)["server_snapshot"] is None


def test_mark_synced_clears_prev_geom(tmp_path):
    # La synchro libère le tampon d'annulation de géométrie (copie conservée à vie sinon).
    db = _make_db(tmp_path)
    station_id = db.create_station(
        id_dataset=3, geom="POINT (1 2)", geom_type="point",
        prev_geom="POINT (9 9)", prev_geom_type="point",
    )
    db.mark_station_synced(station_id, id_station=55)
    full = db.get_station(station_id)
    assert full["sync_status"] == "synced"
    assert full["id_station"] == 55
    assert full["prev_geom"] is None
    assert full["prev_geom_type"] is None
    assert full["geom"] == "POINT (1 2)"  # géométrie courante intacte


def test_sync_log_capped(tmp_path):
    # Le journal est borné : seules les N entrées les plus récentes sont conservées.
    db = _make_db(tmp_path)
    db.SYNC_LOG_KEEP = 5  # borne réduite pour le test
    for i in range(8):
        db.log_sync("upload", "success", "run %d" % i, i)
    db.connect()
    messages = [
        r[0] for r in db.connection.execute(
            "SELECT message FROM t_sync_log ORDER BY id"
        ).fetchall()
    ]
    db.disconnect()
    assert messages == ["run 3", "run 4", "run 5", "run 6", "run 7"]


def test_date_months_ago():
    from datetime import datetime
    assert db_mod._date_months_ago(6, now=datetime(2026, 7, 24)) == "2026-01-24"
    assert db_mod._date_months_ago(6, now=datetime(2026, 1, 15)) == "2025-07-15"
    # jour ramené au dernier jour du mois cible (31 mars − 1 mois → 28 fév.)
    assert db_mod._date_months_ago(1, now=datetime(2026, 3, 31)) == "2026-02-28"


def _set_row(db, station_id, **cols):
    """Forcer des colonnes internes (date_update, sync_status…) pour les tests."""
    db.connect()
    assignments = ", ".join("%s = ?" % k for k in cols)
    db.connection.execute(
        "UPDATE t_stations SET %s WHERE id = ?" % assignments,
        list(cols.values()) + [station_id],
    )
    db.connection.commit()
    db.disconnect()


def test_purge_synced_stations_policy(tmp_path):
    db = _make_db(tmp_path)
    old = "2020-01-01T00:00:00"
    recent = datetime.now().isoformat()

    old_synced = db.create_station(id_dataset=3, station_name="vieille synced")
    _set_row(db, old_synced, sync_status="synced", date_update=old)
    recent_synced = db.create_station(id_dataset=3, station_name="récente synced")
    _set_row(db, recent_synced, sync_status="synced", date_update=recent)
    old_pending = db.create_station(id_dataset=3, station_name="vieille pending")
    _set_row(db, old_pending, sync_status="pending", date_update=old)
    old_conflict = db.create_station(id_dataset=3, station_name="vieille conflict")
    _set_row(db, old_conflict, sync_status="conflict", date_update=old)

    assert db.count_purgeable_stations(months=6) == 1  # seule la vieille synced
    removed = db.purge_synced_stations(months=6)
    assert removed == 1

    remaining = {s["id"] for s in db.get_all_stations()}
    assert old_synced not in remaining          # purgée
    assert recent_synced in remaining           # trop récente
    assert old_pending in remaining             # jamais : non synchronisée
    assert old_conflict in remaining            # jamais : en conflit


def test_purge_cascades_and_reports_zero(tmp_path):
    db = _make_db(tmp_path)
    sid = db.create_station(id_dataset=3)
    db.add_habitat(sid, cd_hab=10, nom_cite="h")
    db.add_observer(sid, observer_name="R", id_role=1)
    _set_row(db, sid, sync_status="synced", date_update="2019-06-01T00:00:00")

    assert db.purge_synced_stations(months=6) == 1
    assert db.get_station(sid) is None                 # station + cascade partis
    assert db.purge_synced_stations(months=6) == 0     # rien à purger → no-op


# --------------------------------------------- chargement en lot + état métier
def test_get_stations_full_charge_enfants(tmp_path):
    db = _make_db(tmp_path)
    s1 = db.create_station(id_dataset=3, station_name="A")
    s2 = db.create_station(id_dataset=3, station_name="B")
    db.create_station(id_dataset=9, station_name="autre JDD")
    db.add_habitat(s1, cd_hab=10, nom_cite="h1")
    db.add_habitat(s1, cd_hab=11, nom_cite="h2")
    db.add_observer(s1, observer_name="Roy", id_role=5)

    stations = db.get_stations_full()

    assert len(stations) == 3
    by_name = {s["station_name"]: s for s in stations}
    assert len(by_name["A"]["habitats"]) == 2
    assert len(by_name["A"]["observers"]) == 1
    assert by_name["B"]["habitats"] == []      # station sans enfant : listes vides
    assert by_name["B"]["observers"] == []
    assert s2 in (s["id"] for s in stations)


def test_get_stations_full_identique_a_get_station(tmp_path):
    """Le chargement en lot doit rendre exactement ce que rendait le N+1."""
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3, station_name="A", comment="c")
    db.add_habitat(station_id, cd_hab=10, nom_cite="h1", recovery_percentage=60)
    db.add_observer(station_id, observer_name="Roy", id_role=5)

    un_par_un = db.get_station(station_id)
    en_lot = db.get_stations_full()[0]

    assert en_lot == un_par_un


def test_get_stations_full_filtre_par_jdd(tmp_path):
    """Un JDD restreint ne doit pas rapatrier les enfants des autres JDD."""
    db = _make_db(tmp_path)
    s1 = db.create_station(id_dataset=3)
    s2 = db.create_station(id_dataset=9)
    db.add_habitat(s1, cd_hab=10, nom_cite="dans le JDD 3")
    db.add_habitat(s2, cd_hab=11, nom_cite="dans le JDD 9")

    stations = db.get_stations_full(id_dataset=3)

    assert len(stations) == 1
    assert [h["nom_cite"] for h in stations[0]["habitats"]] == ["dans le JDD 3"]


def test_nouvelle_station_est_un_brouillon(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3)
    assert db.get_station(station_id)["validation_status"] == db_mod.BROUILLON


def test_validation_status_modifiable(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3)
    db.update_station(station_id, validation_status=db_mod.VALIDE)
    assert db.get_station(station_id)["validation_status"] == db_mod.VALIDE


def test_migration_base_anterieure(tmp_path):
    """Base créée sans la colonne : ce qui était synchronisé devient « validé »."""
    import sqlite3

    path = os.path.join(str(tmp_path), "ancienne.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE t_stations (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " id_dataset INTEGER NOT NULL, station_name TEXT, sync_status TEXT);"
        "CREATE TABLE t_habitats (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " id_station_local INTEGER NOT NULL, cd_hab INTEGER, nom_cite TEXT);"
        "CREATE TABLE cor_station_observer (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " id_station_local INTEGER NOT NULL, id_role INTEGER, observer_name TEXT);"
    )
    conn.execute("INSERT INTO t_stations (id_dataset, station_name, sync_status)"
                 " VALUES (3, 'deja envoyee', 'synced')")
    conn.execute("INSERT INTO t_stations (id_dataset, station_name, sync_status)"
                 " VALUES (3, 'en cours', 'pending')")
    conn.commit()
    conn.close()

    db = db_mod.OccHabDatabase(path)  # déclenche la migration

    statuts = {s["station_name"]: s["validation_status"] for s in db.get_all_stations()}
    assert statuts == {"deja envoyee": db_mod.VALIDE, "en cours": db_mod.BROUILLON}


def test_migration_idempotente(tmp_path):
    """Rouvrir la base ne doit pas re-basculer les statuts choisis par l'utilisateur."""
    path = os.path.join(str(tmp_path), "occhab_test.db")
    db = db_mod.OccHabDatabase(path)
    station_id = db.create_station(id_dataset=3, sync_status="synced")
    db.update_station(station_id, validation_status=db_mod.BROUILLON)

    rouverte = db_mod.OccHabDatabase(path)

    assert rouverte.get_station(station_id)["validation_status"] == db_mod.BROUILLON


def test_constantes_de_statut_alignees_avec_le_referentiel():
    """`sqlite_local` reste sans dépendance : ses constantes sont dupliquées.

    Ce test est le garde-fou de cette duplication assumée.
    """
    import referentiels

    assert db_mod.VALIDATION_STATUSES == tuple(
        code for code, _ in referentiels.STATUTS_VALIDATION
    )
    assert db_mod.BROUILLON == referentiels.BROUILLON
    assert db_mod.VALIDE == referentiels.VALIDE


def test_station_exists(tmp_path):
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3, station_name="S")

    assert db.station_exists(station_id) is True
    assert db.station_exists(999999) is False

    db.delete_station(station_id)
    assert db.station_exists(station_id) is False


def test_ecriture_ciblee_preserve_le_lien_serveur(tmp_path):
    """Régression : la table réécrivait la ligne entière depuis une copie périmée.

    Elle remettait alors `id_station` à NULL après une synchro faite pendant
    qu'elle était ouverte, et la station repartait en création — donc en doublon
    sur GeoNature.
    """
    db = _make_db(tmp_path)
    station_id = db.create_station(id_dataset=3, station_name="S")
    db.mark_station_synced(station_id, 61, server_snapshot="empreinte")

    # Ce que fait désormais l'enregistrement en lot : les seules colonnes modifiées.
    db.update_station(station_id, station_name="S modifiée", sync_status="pending")

    full = db.get_station(station_id)
    assert full["id_station"] == 61
    assert full["server_snapshot"] == "empreinte"
    assert full["station_name"] == "S modifiée"
    assert full["sync_status"] == "pending"
