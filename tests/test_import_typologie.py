# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests des règles d'import du catalogue des végétations (`import_typologie`).

Ce script ne tourne qu'une fois de temps en temps, à la main : personne ne verra
passer une régression. Ce sont donc ses règles métier qui sont testées ici — pas
son interface —, et surtout celles qui ont déjà coûté cher :

- les **tirets longs** du tableur, qui faisaient chuter la résolution de 81 % à
  63 % en la faisant échouer en silence ;
- le **routage Natura 2000**, où `6510` et `6510-1` ne sont pas la même
  typologie HABREF ;
- l'**ancrage** des alliances absentes de HABREF, seul moyen de saisir une
  détermination que le référentiel national ne connaît pas.

Aucun test n'accède au réseau : tout ce qui est vérifié ici est pur.
"""
import import_typologie as it


# ------------------------------------------------------------- normalisation
def test_tirets_unifies():
    """Le tableur écrit « – », HABREF « - » : les deux doivent se comparer égaux."""
    assert it.normaliser("Achilleo ptarmicae – Cirsion palustris") == \
        it.normaliser("Achilleo ptarmicae-Cirsion palustris")


def test_normalisation_accents_et_casse():
    assert it.normaliser("Forêts  MIXTES") == "forets mixtes"


def test_nom_alliance_sans_glose():
    """Commentaire, synonyme et variante ne font pas partie du nom."""
    assert it.nom_alliance('Charion fragilis (! Nommé "Charion intermediae" GC)') == \
        "Charion fragilis"
    assert it.nom_alliance("Cephalanthero rubrae-Pinion sylvestris = Junipero") == \
        "Cephalanthero rubrae-Pinion sylvestris"
    assert it.nom_alliance("Junipero hemisphaericae-Pinion sylvestris ; Vaccinio") == \
        "Junipero hemisphaericae-Pinion sylvestris"


def test_mot_sonde_prend_l_epithete_en_ion():
    """C'est l'alliance qui discrimine, pas le genre qui la précède."""
    assert it.mot_sonde("Achilleo ptarmicae – Cirsion palustris") == "cirsion"
    assert it.mot_sonde("Nitellion flexilis") == "nitellion"


def test_mot_sonde_sans_epithete_en_ion():
    assert it.mot_sonde("Crypsis schoenoides") == "schoenoides"


def test_nom_habref_coupe_le_doublon():
    """`search_name` répète le nom avant les auteurs : on s'arrête au doublon."""
    assert it.nom_habref(
        "18.0.1.0.1 - Nitellion flexilis Nitellion flexilis Segal ex Krause 1969"
    ) == "Nitellion flexilis"


# -------------------------------------------------------------------- codes
def test_extraire_plusieurs_codes():
    assert it.extraire_codes("C1.25 ; C1.141", "eunis") == (["C1.25", "C1.141"], "")


def test_extraire_code_et_condition():
    """La condition n'est pas jetée : c'est elle qui dit si le code s'applique."""
    codes, reste = it.extraire_codes("6430 (pp si habitat linéaire)", "n2000")
    assert codes == ["6430"]
    assert reste == "(pp si habitat linéaire)"


def test_extraire_cellule_vide():
    for vide in ("", "/", "-", None):
        assert it.extraire_codes(vide, "corine") == ([], "")


def test_extraire_texte_seul_sans_code():
    """Un nom de taxon en colonne CORINE ne doit pas passer pour un code."""
    codes, reste = it.extraire_codes("Hypericum humifusum", "corine")
    assert codes == []
    assert reste == "Hypericum humifusum"


def test_code_corine_avec_suffixe_alphabetique():
    assert it.extraire_codes("34.332G", "corine") == (["34.332G"], "")


# ----------------------------------------------------------- routage N2000
def test_routage_n2000_vers_les_deux_typologies():
    """`6510` est un HIC ; `6510-1` sa déclinaison en Cahiers d'habitats."""
    assert it.typologie_n2000("6510") == "Habitats_d'intérêt_communautaire"
    assert it.typologie_n2000("6510-1") == "Cahiers_d'habitats"
    assert it.typologie_n2000("3150-3") == "Cahiers_d'habitats"


# ------------------------------------------------------- lignes du catalogue
def test_ligne_de_catalogue_reconnue():
    assert it.est_ligne_catalogue({"D": "Charetea fragilis", "H": "Nitellion flexilis"})


def test_ligne_de_brouillon_ecartee():
    """Bas de feuille : la colonne Classe porte un code CORINE, pas un syntaxon."""
    assert not it.est_ligne_catalogue({"D": "22.32", "H": "Crypsis schoenoides"})


def test_ligne_sans_alliance_ecartee():
    assert not it.est_ligne_catalogue({"D": "Charetea fragilis", "H": ""})


def test_classe_vide_ne_disqualifie_pas():
    """Trois alliances réelles n'ont pas leur classe recopiée (l.35, l.36, l.179).

    Une première version exigeait une classe non vide et les perdait en silence —
    exactement ce que ce script doit rendre impossible.
    """
    assert it.est_ligne_catalogue({"D": "", "H": "Arabidion soyeri"})


# ------------------------------------------------------------------ ancrage
def test_ancre_corine_prioritaire():
    """42 des 43 alliances ancrées ont un CORINE, plus fin qu'EUNIS ici."""
    assert it.choisir_ancre(["31.8"], ["F3.1"]) == ("CORINE_biotopes", "31.8")


def test_ancre_eunis_en_repli():
    assert it.choisir_ancre([], ["F3.1"]) == ("EUNIS", "F3.1")


def test_aucune_ancre_possible():
    """Cas bloquant : la ligne n'est pas saisissable tant qu'elle n'a pas de code."""
    assert it.choisir_ancre([], []) is None


# --------------------------- la prose du tableur n'est pas un code de typologie
def test_un_mot_ne_passe_pas_pour_un_code_eunis():
    """EUNIS a de vrais codes d'une lettre : « A » en est un, « A définir » non.

    Sans cette distinction, « Aucune correspondance » ressortait en code EUNIS
    « A » — parfaitement résoluble dans HABREF, donc invisible à la relecture.
    """
    for prose in ("Aucune correspondance", "A définir", "Non concerné"):
        assert it.extraire_codes(prose, "eunis") == ([], prose)
    assert it.extraire_codes("A", "eunis") == (["A"], "")
    assert it.extraire_codes("A3.112", "eunis") == (["A3.112"], "")


def test_le_texte_non_codifie_est_rendu_une_seule_fois():
    """`_resoudre_codes` rend la condition qu'il a déjà calculée.

    Elle était recalculée par un second appel à `extraire_codes` : deux analyses
    de la même cellule, dont l'une décide si le code Natura 2000 s'applique.
    """
    codes, reste = it.extraire_codes("6430 (pp si habitat linéaire)", "n2000")
    assert codes == ["6430"]
    assert reste == "(pp si habitat linéaire)"


def test_complement_lu_par_numero_de_ligne():
    """Un complément se rattache à une ligne du tableur, et à elle seule."""
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as dossier:
        chemin = os.path.join(dossier, "complement.csv")
        with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
            f.write("ligne_xlsx;corine;eunis\n251;44.1;F9.1\nabc;1;2\n")
        assert it.lire_complement(chemin) == {251: {"corine": "44.1", "eunis": "F9.1"}}
    assert it.lire_complement(None) == {}


def test_un_code_eunis_suivi_d_une_lettre_n_est_pas_tronque():
    """« E1.26a » ne doit pas ressortir en « E1.2 » — code valide, donc invisible.

    Une sentinelle `(?![A-Za-z])` dans le motif faisait rétro-agir le moteur
    d'expressions régulières DANS les chiffres du dernier niveau. Le contrôle se
    fait donc après la recherche, et ce qu'on ne sait pas lire part en anomalie
    plutôt qu'en correspondance devinée.
    """
    assert it.extraire_codes("E1.26a", "eunis") == ([], "E1.26a")
    assert it.extraire_codes("E1.26", "eunis") == (["E1.26"], "")
