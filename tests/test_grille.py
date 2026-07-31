# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du tampon d'édition de la table attributaire (module pur `grille`)."""
import champs as ch
import grille as gr


def _stations():
    """Deux stations : l'une en mosaïque (2 habitats), l'autre sans habitat."""
    return [
        {
            "id": 1, "id_dataset": 3, "station_name": "Soula 01",
            "date_min": "2026-06-12", "comment": None,
            "habitats": [
                {"id": 10, "cd_hab": 5130, "nom_cite": "Fruticées",
                 "recovery_percentage": 60, "technical_precision": None},
                {"id": 11, "cd_hab": 6210, "nom_cite": "Pelouse",
                 "recovery_percentage": 40, "technical_precision": None},
            ],
        },
        {
            "id": 2, "id_dataset": 3, "station_name": "Soula 02",
            "date_min": "2026-06-13", "comment": None, "habitats": [],
        },
    ]


def _champ(niveau, cle):
    return ch.par_cle(niveau, cle)


# ------------------------------------------------------------- structure
def test_une_ligne_par_habitat_et_une_pour_les_stations_sans_habitat():
    grille = gr.Grille(_stations())

    assert len(grille) == 3
    assert [ligne.station["station_name"] for ligne in grille.lignes] == [
        "Soula 01", "Soula 01", "Soula 02"]
    assert grille.lignes[2].habitat is None


def test_ne_modifie_pas_les_dicts_source():
    source = _stations()
    grille = gr.Grille(source)

    grille.definir(grille.lignes[0], _champ(ch.STATION, "station_name"), "Modifié")

    assert source[0]["station_name"] == "Soula 01"


def test_cellule_habitat_d_une_station_sans_habitat_non_editable():
    grille = gr.Grille(_stations())
    ligne = grille.lignes[2]

    assert grille.editable(ligne, _champ(ch.HABITAT, "typicite")) is False
    assert grille.valeur(ligne, _champ(ch.HABITAT, "typicite")) is None
    assert grille.definir(ligne, _champ(ch.HABITAT, "typicite"), "bonne") is False


def test_champ_en_lecture_seule_refuse_l_ecriture():
    grille = gr.Grille(_stations())
    assert grille.definir(grille.lignes[0], _champ(ch.STATION, "area"), 999) is False


# --------------------------------------------- propagation des champs station
def test_champ_station_propage_aux_lignes_soeurs():
    """Le risque n°1 de la grille : deux lignes du même polygone qui divergent."""
    grille = gr.Grille(_stations())
    champ = _champ(ch.STATION, "date_min")

    grille.definir(grille.lignes[0], champ, "2026-07-01")

    assert grille.valeur(grille.lignes[1], champ) == "2026-07-01"  # ligne sœur
    assert grille.valeur(grille.lignes[2], champ) == "2026-06-13"  # autre station


def test_champ_station_en_bloc_propage_aussi():
    grille = gr.Grille(_stations())
    champ = _champ(ch.STATION, "enjeu")

    grille.definir(grille.lignes[0], champ, "fort")

    assert grille.valeur(grille.lignes[1], champ) == "fort"


def test_champ_habitat_ne_propage_pas():
    grille = gr.Grille(_stations())
    champ = _champ(ch.HABITAT, "typicite")

    grille.definir(grille.lignes[0], champ, "bonne")

    assert grille.valeur(grille.lignes[1], champ) is None


def test_lignes_de_donne_les_soeurs():
    grille = gr.Grille(_stations())
    assert grille.lignes_de(grille.lignes[0]) == [0, 1]
    assert grille.lignes_de(grille.lignes[2]) == [2]


# ------------------------------------------------------------- suivi
def test_marquage_des_cellules_modifiees():
    grille = gr.Grille(_stations())
    champ = _champ(ch.HABITAT, "typicite")

    assert grille.modifie(grille.lignes[0], champ) is False
    grille.definir(grille.lignes[0], champ, "bonne")
    assert grille.modifie(grille.lignes[0], champ) is True
    assert grille.modifie(grille.lignes[1], champ) is False


def test_valeur_identique_ne_marque_rien():
    grille = gr.Grille(_stations())
    champ = _champ(ch.STATION, "station_name")

    assert grille.definir(grille.lignes[0], champ, "Soula 01") is False
    assert grille.a_des_modifications() is False


def test_modifications_ne_rend_que_les_stations_touchees():
    grille = gr.Grille(_stations())
    grille.definir(grille.lignes[0], _champ(ch.HABITAT, "typicite"), "bonne")

    touchees = grille.modifications()

    assert [s["id"] for s in touchees] == [1]  # station 2 intacte


def test_modification_d_un_habitat_rend_sa_station():
    """Les habitats sont remplacés en bloc : c'est la station qu'il faut réécrire."""
    grille = gr.Grille(_stations())
    grille.definir(grille.lignes[1], _champ(ch.HABITAT, "dynamique"), "stable")

    assert [s["id"] for s in grille.modifications()] == [1]


def test_oublier_modifications():
    grille = gr.Grille(_stations())
    grille.definir(grille.lignes[0], _champ(ch.STATION, "station_name"), "X")

    grille.oublier_modifications()

    assert grille.a_des_modifications() is False
    assert grille.modifications() == []
    assert grille.valeur(grille.lignes[0], _champ(ch.STATION, "station_name")) == "X"


# ------------------------------------------------------------- en masse
def test_appliquer_un_champ_station_n_ecrit_qu_une_fois_par_station():
    grille = gr.Grille(_stations())
    valeurs = {(ch.STATION, "validation_status"): "valide"}

    # Les deux lignes de la station 1 sont sélectionnées.
    ecrites = grille.appliquer(grille.lignes[0:2], valeurs)

    assert ecrites == 1
    assert grille.valeur(grille.lignes[0], _champ(ch.STATION, "validation_status")) == "valide"


def test_appliquer_un_champ_habitat_touche_chaque_habitat():
    grille = gr.Grille(_stations())
    valeurs = {(ch.HABITAT, "typicite"): "bonne"}

    ecrites = grille.appliquer(grille.lignes, valeurs)

    assert ecrites == 2  # la 3e ligne n'a pas d'habitat
    assert grille.valeur(grille.lignes[1], _champ(ch.HABITAT, "typicite")) == "bonne"


def test_appliquer_plusieurs_champs():
    grille = gr.Grille(_stations())
    ecrites = grille.appliquer(grille.lignes, {
        (ch.STATION, "date_min"): "2026-07-01",
        (ch.HABITAT, "restauration"): "possible",
    })
    assert ecrites == 4  # 2 stations + 2 habitats


def test_previsualiser_compte_les_ecrasements_pas_les_lignes():
    """Ce qui doit alerter, c'est la valeur existante qui disparaît."""
    grille = gr.Grille(_stations())
    grille.definir(grille.lignes[0], _champ(ch.HABITAT, "typicite"), "moyenne")
    grille.oublier_modifications()

    apercu = grille.previsualiser(grille.lignes, {(ch.HABITAT, "typicite"): "bonne"})

    assert apercu["habitats"] == 2
    assert apercu["ecrasements"] == 1  # seul l'habitat 10 avait déjà une valeur


def test_previsualiser_ne_modifie_rien():
    grille = gr.Grille(_stations())
    grille.previsualiser(grille.lignes, {(ch.HABITAT, "typicite"): "bonne"})

    assert grille.a_des_modifications() is False
    assert grille.valeur(grille.lignes[0], _champ(ch.HABITAT, "typicite")) is None


def test_previsualiser_ignore_la_valeur_identique():
    grille = gr.Grille(_stations())
    grille.definir(grille.lignes[0], _champ(ch.HABITAT, "typicite"), "bonne")

    apercu = grille.previsualiser(grille.lignes, {(ch.HABITAT, "typicite"): "bonne"})

    assert apercu["ecrasements"] == 0  # même valeur : rien ne se perd


# ------------------------------------------------------------- cohérence
def test_recouvrements_coherents():
    assert gr.Grille(_stations()).recouvrements_incoherents() == []


def test_recouvrements_incoherents_signales():
    grille = gr.Grille(_stations())
    grille.definir(grille.lignes[0], _champ(ch.HABITAT, "recouvrement"), 80)

    fautives = grille.recouvrements_incoherents()

    assert len(fautives) == 1
    station, total = fautives[0]
    assert station["id"] == 1
    assert total == 120


def test_recouvrement_non_renseigne_n_est_pas_une_incoherence():
    stations = _stations()
    for habitat in stations[0]["habitats"]:
        habitat["recovery_percentage"] = None

    assert gr.Grille(stations).recouvrements_incoherents() == []


# ------------------------------------------------- rétrogradation du statut
def _stations_validees():
    stations = _stations()
    for station in stations:
        station["validation_status"] = "valide"
    return stations


def test_retoucher_une_station_validee_la_remet_en_brouillon():
    grille = gr.Grille(_stations_validees())
    grille.definir(grille.lignes[0], _champ(ch.HABITAT, "typicite"), "bonne")

    assert [s["id"] for s in grille.statuts_retrogrades()] == [1]


def test_valider_une_station_ne_la_retrograde_pas():
    """Sans cette exception, valider remettrait aussitôt en brouillon."""
    grille = gr.Grille(_stations())
    grille.definir(grille.lignes[0], _champ(ch.STATION, "validation_status"), "valide")

    assert grille.statuts_retrogrades() == []


def test_valider_et_retoucher_dans_la_meme_passe_reste_valide():
    """L'utilisateur a explicitement demandé « validé » : sa décision prime."""
    grille = gr.Grille(_stations())
    grille.definir(grille.lignes[0], _champ(ch.HABITAT, "typicite"), "bonne")
    grille.definir(grille.lignes[0], _champ(ch.STATION, "validation_status"), "valide")

    assert grille.statuts_retrogrades() == []


def test_station_brouillon_non_concernee():
    grille = gr.Grille(_stations())
    grille.definir(grille.lignes[0], _champ(ch.HABITAT, "typicite"), "bonne")

    assert grille.statuts_retrogrades() == []


def test_station_validee_non_touchee_reste_validee():
    grille = gr.Grille(_stations_validees())
    grille.definir(grille.lignes[2], _champ(ch.STATION, "station_name"), "Renommée")

    assert [s["id"] for s in grille.statuts_retrogrades()] == [2]


# ----------------------------------- cellule non éditable mais modifiable en lot
def test_observateurs_non_editables_en_cellule():
    """Une liste multi-valuée n'a pas sa place dans une cellule."""
    grille = gr.Grille(_stations())
    champ = _champ(ch.STATION, "observers")

    assert grille.editable(grille.lignes[0], champ) is False
    assert grille.definir(grille.lignes[0], champ, [{"id_role": 7}]) is False


def test_observateurs_modifiables_en_masse():
    """…mais poser une équipe sur toute une campagne doit rester possible.

    C'est la distinction entre `cellule` et `masse` : les confondre rendait les
    observateurs intouchables partout.
    """
    grille = gr.Grille(_stations())
    equipe = [{"id_role": 7, "observer_name": "Roy Cédric"}]

    ecrites = grille.appliquer(grille.lignes, {(ch.STATION, "observers"): equipe})

    assert ecrites == 2  # une écriture par station, pas par ligne
    assert grille.valeur(grille.lignes[0], _champ(ch.STATION, "observers")) == equipe
    assert [s["id"] for s in grille.modifications()] == [1, 2]
