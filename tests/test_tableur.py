# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de la mise en TSV : une cellule ne doit jamais décaler le tableau."""
import tableur


def test_cellule_ordinaire_intacte():
    assert tableur.cellule("Chênaie") == "Chênaie"
    assert tableur.cellule(42) == "42"
    assert tableur.cellule(None) == ""


def test_commentaire_multiligne_reste_dans_sa_cellule():
    """Un commentaire de station tient souvent sur plusieurs lignes."""
    texte = "Prairie humide\nà revoir au printemps"
    assert tableur.cellule(texte) == '"Prairie humide\nà revoir au printemps"'


def test_tabulation_collee_depuis_ailleurs():
    assert tableur.cellule("Lande\tsèche") == '"Lande\tsèche"'


def test_guillemets_doubles():
    assert tableur.cellule('dit « bas-marais "vrai" »') == \
        '"dit « bas-marais ""vrai"" »"'


def test_tableau_complet():
    lignes = [["N°", "Nom"], [1, "Pelouse"], [2, "Chênaie"]]
    assert tableur.tsv(lignes) == "N°\tNom\r\n1\tPelouse\r\n2\tChênaie"


def test_tableau_vide():
    assert tableur.tsv([]) == ""
    assert tableur.tsv(None) == ""


def test_le_nombre_de_colonnes_ne_bouge_pas():
    """Le piège que tout l'échappement sert à éviter."""
    lignes = [["a", "b", "c"], ["x\ty", "saut\nligne", "ok"]]
    rendu = tableur.tsv(lignes)
    # Hors guillemets, chaque ligne doit garder ses deux séparateurs.
    dehors, tabulations = True, 0
    for caractere in rendu:
        if caractere == '"':
            dehors = not dehors
        elif caractere == "\t" and dehors:
            tabulations += 1
    assert tabulations == 4  # deux par ligne, deux lignes
