# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de la carte des plantes exotiques envahissantes (module pur `pee`)."""
import pee


def test_lecture_de_la_chaine_de_la_vue():
    """La vue rend « a, b, c » ; trois taxons au plus par habitat."""
    assert pee.especes("Reynoutria japonica, Robinia pseudoacacia") == [
        "Reynoutria japonica", "Robinia pseudoacacia"]
    assert pee.especes("  Buddleja davidii  ") == ["Buddleja davidii"]


def test_doublons_et_espaces_ne_font_pas_deux_especes():
    assert pee.especes("Buddleja davidii, buddleja  davidii") == ["Buddleja davidii"]


def test_absence_de_pee():
    for valeur in (None, "", "   ", ",,", 42):
        assert pee.especes(valeur) == [], valeur


def _entite(chaine):
    return {"properties": {"habitat_pee": chaine}}


def test_inventaire_trie_par_nom():
    """La couleur ne doit pas dépendre de l'ordre des lignes du serveur."""
    entites = [_entite("Robinia pseudoacacia"), _entite("Buddleja davidii"),
               _entite("Reynoutria japonica, Buddleja davidii")]
    assert pee.inventaire(entites) == [
        "Buddleja davidii", "Reynoutria japonica", "Robinia pseudoacacia"]
    # Le même jeu dans l'autre sens donne la même liste, donc les mêmes couleurs.
    assert pee.inventaire(list(reversed(entites))) == pee.inventaire(entites)


def test_couleurs_distinctes_et_stables():
    couleurs = [pee.couleur(rang) for rang in range(12)]
    assert len(set(couleurs)) == 12
    assert all(c.startswith("#") and len(c) == 7 for c in couleurs)
    # Ajouter une espèce ne rebat pas les couleurs déjà attribuées.
    assert [pee.couleur(r) for r in range(11)] == couleurs[:11]


def test_deux_couleurs_voisines_se_distinguent():
    def rvb(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

    for rang in range(11):
        a, b = rvb(pee.couleur(rang)), rvb(pee.couleur(rang + 1))
        assert sum(abs(x - y) for x, y in zip(a, b)) > 120, rang


def test_palette_complete():
    entites = [_entite("Reynoutria japonica"), _entite("Buddleja davidii")]
    palette = pee.palette(entites)
    assert [nom for nom, _c in palette] == ["Buddleja davidii", "Reynoutria japonica"]


def test_repartition_alternee():
    """Alterner, et non découper en blocs : trois taches contiguës se liraient
    comme une localisation que la donnée ne contient pas."""
    points = list(range(9))
    parts = pee.repartir(["a", "b", "c"], points)
    assert parts == {"a": [0, 3, 6], "b": [1, 4, 7], "c": [2, 5, 8]}


def test_repartition_quand_il_y_a_moins_de_points_que_d_especes():
    """Deux points pour trois espèces : la troisième n'est pas inventée."""
    parts = pee.repartir(["a", "b", "c"], [0, 1])
    assert parts == {"a": [0], "b": [1]}


def test_repartition_vide():
    assert pee.repartir([], [1, 2]) == {}
    assert pee.repartir(["a"], []) == {}
