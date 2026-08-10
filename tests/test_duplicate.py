# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du modèle de duplication d'une station (module pur `duplicate`)."""
import duplicate
import eval_fields as ef


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
                "sync_status", "sync_date", "date_creation", "date_update",
                # « créée par moi sur GeoNature » : vrai pour la copie, quoi
                # qu'il en soit de l'original récupéré du serveur.
                "mine"):
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


def test_collage_ne_touche_pas_au_nom_ni_aux_listes():
    """Coller renseigne une station DÉJÀ tracée : son nom lui reste propre."""
    fields = duplicate.paste_fields(duplicate.station_template(_station()))

    assert "station_name" not in fields
    assert "habitats" not in fields  # écrits table par table par l'appelant
    assert "observers" not in fields
    # La géométrie de la cible n'est pas concernée, ni son identité.
    for key in ("geom", "geom_type", "area", "altitude_min", "id", "id_station",
                "validation_status"):
        assert key not in fields, key
    assert fields["id_dataset"] == 3
    assert fields["date_min"] == "2026-06-12"


def test_collage_source_vide():
    assert duplicate.paste_fields(None) == {}


def _habitat():
    return {
        "id": 40,
        "id_habitat": 8901,
        "id_station_local": 12,
        "unique_id_sinp_hab": "77aa…",
        "sync_status": "synced",
        "cd_hab": 5130,
        "nom_cite": "Fruticées",
        "recovery_percentage": 60,
        "determiner": "Roy Cédric",
        "id_nomenclature_determination_type": 383,
        "id_nomenclature_collection_technique": 411,
        "id_nomenclature_abundance": 202,
        "id_nomenclature_sensitivity": 160,
        "technical_precision": (
            "au jugé\n\n[ANA-EVAL] {\"etat_conservation\": \"bon\", "
            "\"recouvrement\": 60, \"typicite\": \"bonne\"} [/ANA-EVAL]"
        ),
    }


def test_reprise_habitat_garde_le_contexte_de_saisie():
    """Ce qui se répète d'un habitat au suivant : détermination, technique, N2000."""
    reprise = duplicate.habitat_reprise(_habitat())

    assert reprise["determiner"] == "Roy Cédric"
    assert reprise["id_nomenclature_determination_type"] == 383
    assert reprise["id_nomenclature_collection_technique"] == 411
    assert reprise["id_nomenclature_sensitivity"] == 160
    assert "etat_conservation" in reprise["technical_precision"]
    assert "typicite" in reprise["technical_precision"]
    assert "au jugé" in reprise["technical_precision"]  # texte humain préservé


def test_reprise_habitat_sans_identite_ni_mesure():
    """Nom cité, code, recouvrement et abondance sont propres à CHAQUE habitat.

    Le recouvrement est aussi encodé dans le bloc ANA-EVAL : l'y laisser le
    ferait réapparaître dans le formulaire suivant malgré la colonne retirée.
    """
    reprise = duplicate.habitat_reprise(_habitat())

    for key in ("nom_cite", "cd_hab", "recovery_percentage",
                "id_nomenclature_abundance", "id", "id_habitat",
                "id_station_local", "unique_id_sinp_hab", "sync_status"):
        assert key not in reprise, key
    assert "recouvrement" not in reprise["technical_precision"]


def test_reprise_habitat_sans_bloc_ni_source():
    """Un habitat sans précision technique ne fabrique pas de bloc vide."""
    assert duplicate.habitat_reprise({}) == {}
    assert duplicate.habitat_reprise(None) == {}
    reprise = duplicate.habitat_reprise({"technical_precision": "", "determiner": "X"})
    assert reprise["technical_precision"] == ""

    # Un bloc ne contenant QUE le recouvrement disparaît entièrement.
    reprise = duplicate.habitat_reprise(
        {"technical_precision": "[ANA-EVAL] {\"recouvrement\": 40} [/ANA-EVAL]"}
    )
    assert reprise["technical_precision"] is None


def test_duplicata_repart_en_brouillon():
    """Copier une station validée ne valide pas la copie : c'est un travail neuf."""
    source = _station()
    source["validation_status"] = "valide"

    template = duplicate.station_template(source)

    assert "validation_status" not in template


# ----------- la détermination et les correspondances ne suivent pas l'habitat suivant
def test_la_reprise_jette_determination_et_correspondances():
    """Elles décrivent l'habitat PRÉCÉDENT, sous un code qui va changer.

    `nom_cite` et `cd_hab` sont déjà écartés de la reprise : garder l'alliance et
    ses correspondances les rattacherait au code du prochain habitat — une
    correspondance EUNIS fausse, et muette, puisque rien ne l'affiche tant qu'on
    n'ouvre pas la section.
    """
    habitat = {
        "id_habitat": 7, "cd_hab": 1204, "nom_cite": "Subularion aquaticae",
        "id_nomenclature_collection_technique": 3,
        "technical_precision": ef.encode_eval(
            "Relevé du 12 mai.", enjeu="fort", recouvrement=40,
            determination={"nom": "Subularion aquaticae", "ancre": "CORINE_biotopes"},
            corresp={"EUNIS": {"cd_hab": 1672, "code": "C3.4", "src": "manuel"}},
        ),
    }
    reprise = duplicate.habitat_reprise(habitat)
    codes = ef.decode_eval(reprise["technical_precision"])
    assert "determination" not in codes
    assert "corresp" not in codes
    # Ce qui décrit la MANIÈRE de travailler, lui, se reprend bien.
    assert codes["enjeu"] == "fort"
    assert reprise["id_nomenclature_collection_technique"] == 3
    assert ef.strip_eval(reprise["technical_precision"]) == "Relevé du 12 mai."
