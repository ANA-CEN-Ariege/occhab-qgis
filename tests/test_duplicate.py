# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du modèle de duplication d'une station (module pur `duplicate`)."""
import duplicate


def _station():
    """Station locale complète, déjà synchronisée (donc porteuse d'ids serveur)."""
    return {
        "id": 12,
        "id_station": 4567,
        "unique_id_sinp_station": "0d3e…",
        "id_dataset": 3,
        "station_name": "Soula — pelouse haute",
        "date_min": "2026-06-12",
        "date_max": "2026-06-12",
        "observers_txt": "Roy Cédric",
        "altitude_min": 980,
        "altitude_max": 1120,
        "depth_min": None,
        "area": 15400,
        "comment": "texte libre\n\n[ANA-EVAL] enjeu=fort [/ANA-EVAL]",
        "geom": "POLYGON ((0 0, 1 0, 1 1, 0 0))",
        "geom_type": "polygon",
        "prev_geom": "POLYGON ((0 0, 2 0, 2 2, 0 0))",
        "prev_geom_type": "polygon",
        "id_nomenclature_exposure": 100,
        "sync_status": "synced",
        "sync_date": "2026-06-13T09:00:00",
        "date_creation": "2026-06-12T18:00:00",
        "date_update": "2026-06-12T18:30:00",
        "server_snapshot": "9f2c…",
        "created_by": "Cédric Roy",
        "mine": 1,
        "habitats": [
            {
                "id": 40,
                "id_habitat": 8901,
                "id_station_local": 12,
                "unique_id_sinp_hab": "77aa…",
                "cd_hab": 5130,
                "nom_cite": "Fruticées",
                "recovery_percentage": 60,
                "technical_precision": "[ANA-EVAL] etat_conservation=bon [/ANA-EVAL]",
                "sync_status": "synced",
            }
        ],
        "observers": [
            {"id": 3, "id_station_local": 12, "id_role": 7, "observer_name": "Roy Cédric"},
            {"id": 4, "id_station_local": 12, "id_role": None, "observer_name": "sans id"},
        ],
    }


def test_identifiants_serveur_et_locaux_retires():
    """Le point critique : aucune copie ne doit hériter d'une identité existante."""
    template = duplicate.station_template(_station())

    for key in ("id", "id_station", "unique_id_sinp_station", "server_snapshot",
                "sync_status", "sync_date", "date_creation", "date_update"):
        assert key not in template, key
    habitat = template["habitats"][0]
    for key in ("id", "id_habitat", "id_station_local", "unique_id_sinp_hab",
                "sync_status"):
        assert key not in habitat, key


def test_geometrie_et_grandeurs_derivees_retirees():
    """Surface et altitude seront recalculées depuis la nouvelle géométrie."""
    template = duplicate.station_template(_station())

    for key in ("geom", "geom_type", "prev_geom", "prev_geom_type",
                "area", "altitude_min", "altitude_max"):
        assert key not in template, key


def test_attributs_metier_conserves():
    template = duplicate.station_template(_station())

    assert template["id_dataset"] == 3
    assert template["station_name"] == "Soula — pelouse haute"
    assert template["date_min"] == "2026-06-12"
    assert template["date_max"] == "2026-06-12"
    assert template["id_nomenclature_exposure"] == 100
    assert "[ANA-EVAL] enjeu=fort [/ANA-EVAL]" in template["comment"]
    assert template["depth_min"] is None  # profondeur : pas déduite de la géométrie


def test_habitats_et_observateurs_conserves():
    template = duplicate.station_template(_station())

    assert len(template["habitats"]) == 1
    habitat = template["habitats"][0]
    assert habitat["cd_hab"] == 5130
    assert habitat["nom_cite"] == "Fruticées"
    assert habitat["recovery_percentage"] == 60
    assert "etat_conservation=bon" in habitat["technical_precision"]

    # Seuls les observateurs identifiés (id_role) sont repris : la station créée
    # les renverra à GeoNature sous forme de liste [{id_role}].
    assert template["observers"] == [{"id_role": 7, "observer_name": "Roy Cédric"}]


def test_station_vide_ou_none():
    for source in (None, {}):
        template = duplicate.station_template(source)
        assert template["habitats"] == []
        assert template["observers"] == []


def test_duplicata_repart_en_brouillon():
    """Copier une station validée ne valide pas la copie : c'est un travail neuf."""
    source = _station()
    source["validation_status"] = "valide"

    template = duplicate.station_template(source)

    assert "validation_status" not in template
