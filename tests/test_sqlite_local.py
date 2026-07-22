# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de la base SQLite locale (CRUD + machine à états de synchro)."""
import os

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
