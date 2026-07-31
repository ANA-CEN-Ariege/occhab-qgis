# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de l'aplatissement cartographie (module pur `export`)."""
import eval_fields
import export as ex


def test_flatten_one_row_per_habitat():
    comment = eval_fields.encode_eval("texte libre", enjeu="fort", etat_conservation="moyen")
    station = {
        "id_station": 1, "station_name": "S",
        "geom": "POLYGON ((0 0, 1 0, 1 1, 0 0))", "geom_type": "polygon",
        "id_nomenclature_exposure": 100, "id_digitiser": 7, "comment": comment,
    }
    habitats = [
        {"id_habitat": 10, "cd_hab": 5130, "nom_cite": "Fruticées",
         "recovery_percentage": 45, "id_nomenclature_abundance": 200},
        {"id_habitat": 11, "cd_hab": 5140, "nom_cite": "Pelouse"},
    ]
    observers = [{"id_role": 7, "observer_name": "Roy Cédric"}]
    labels = {100: "Sud", 200: "Abondant"}

    habref = {5130: {"nom": "Chênaies-charmaies", "code": "41.2"}}

    rows = ex.flatten_cartography(
        [(station, habitats, observers)],
        nomenclature_label=labels.get,
        jdd_name="JDD test",
        role_label={7: "Roy Cédric"}.get,
        habref_label=habref.get,
    )

    assert len(rows) == 2  # une ligne par habitat
    first = rows[0]
    assert first["id_station"] == 1
    assert first["jdd"] == "JDD test"
    assert first["exposition"] == "Sud"
    assert first["numerisateur"] == "Roy Cédric"
    assert first["observateurs"] == "Roy Cédric"  # reconstruit depuis les observers
    assert first["st_enjeu"] == "fort"
    assert first["st_etat_cons"] == "moyen"
    assert first["cd_hab"] == 5130
    assert first["habitat_officiel"] == "Chênaies-charmaies"  # libellé HABREF résolu
    assert first["code_habref"] == "41.2"
    assert first["nom_cite"] == "Fruticées"
    assert first["recouvrement"] == 45
    assert first["abondance"] == "Abondant"
    assert first["_geom_type"] == "polygon"
    assert first["_geom"].startswith("POLYGON")

    # 2e habitat : cd_hab non résolu et abondance non renseignée → None
    assert rows[1]["cd_hab"] == 5140
    assert rows[1]["habitat_officiel"] is None
    assert rows[1]["abondance"] is None


def test_flatten_station_without_habitat():
    rows = ex.flatten_cartography([({"id_station": 2, "geom": "POINT (1 2)",
                                     "geom_type": "point"}, [], [])])
    assert len(rows) == 1
    assert rows[0]["id_habitat"] is None
    assert rows[0]["cd_hab"] is None
    assert rows[0]["_geom_type"] == "point"
    # toutes les colonnes du schéma sont présentes
    for name in ex.FIELDS:
        assert name in rows[0]


def test_colonnes_n2000_exportees():
    """Les champs de l'annexe 2 doivent ressortir dans la cartographie exportée."""
    comment = eval_fields.encode_eval(
        "Note.", enjeu="fort", unite_vegetale="mosaique_temporelle",
        nature_observation="directe_avec_releve", echelle=5000, zone_humide=True,
    )
    precision = eval_fields.encode_eval(
        "", typicite="bonne", dynamique="regressive_lente",
        restauration="possible_avec_efforts", critere="Présence de PEE",
        pee=["Reynoutria japonica", "Buddleja davidii"], remarque="À revoir",
    )
    station = {
        "id_station": 1, "validation_status": "valide", "comment": comment,
        "geom": "POINT (1 2)", "geom_type": "point",
    }
    habitats = [{"id_habitat": 10, "cd_hab": 5130, "nom_cite": "Fruticées",
                 "technical_precision": precision}]

    row = ex.flatten_cartography([(station, habitats, [])])[0]

    assert row["statut"] == "valide"
    assert row["unite_vegetale"] == "mosaique_temporelle"
    assert row["nature_obs"] == "directe_avec_releve"
    assert row["echelle"] == 5000
    assert row["st_zone_humide"] is True
    assert row["typicite"] == "bonne"
    assert row["dynamique"] == "regressive_lente"
    assert row["restauration"] == "possible_avec_efforts"
    assert row["critere"] == "Présence de PEE"
    # Pas de type liste dans un shapefile : les taxons sont concaténés.
    assert row["pee"] == "Reynoutria japonica ; Buddleja davidii"
    assert row["remarque"] == "À revoir"


def test_toutes_les_colonnes_declarees_sont_presentes():
    row = ex.flatten_cartography(
        [({"id_station": 1, "geom": "POINT (1 2)", "geom_type": "point"}, [], [])]
    )[0]
    for champ in ex.FIELDS:
        assert champ in row, champ
