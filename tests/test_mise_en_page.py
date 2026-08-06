# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de la composition de planche (modules purs `mise_en_page`, `gabarits`).

L'encombrement de la légende n'est pas calculé mais MESURÉ par QGIS (cf.
`print_layout._essayer`) : l'estimer au caractère donnait un résultat plausible
et faux. Restent ici les deux calculs qu'aucune mesure ne donne — la place libre
autour d'un cadre, et le corps d'un bloc de mentions converti depuis du HTML.
"""
import gabarits as gb
import mise_en_page as mep

#: Le cadre de légende du gabarit A4 de l'ANA, tel qu'il est déclaré, et la
#: place que la page lui laisse réellement.
_CADRE_A4 = (227.0, 42.0, 4.0, 7.5)
_PAGE_A4 = (297.0, 210.0)
_VOISINS_A4 = [
    (0.0, 0.0, 297.0, 210.0),      # carte pleine page : englobe, ne borne pas
    (227.0, 18.0, 70.0, 24.0),     # sous-titre, au-dessus
    (227.0, 172.0, 70.0, 4.0),     # mention du fond, en dessous
    (227.0, 192.0, 31.8, 14.0),    # logo
]


def test_espace_libre_ignore_les_cadres_englobants():
    """La carte pleine page est sous la légende, pas devant elle."""
    largeur, hauteur = mep.espace_libre(_CADRE_A4, _VOISINS_A4, _PAGE_A4)
    assert largeur > 60  # jusqu'au bord droit de la page
    assert hauteur > 110  # jusqu'à la mention du fond, à 172 mm


def test_espace_libre_bute_sur_le_voisin_du_dessous():
    cadre = (10.0, 10.0, 5.0, 5.0)
    voisins = [(10.0, 80.0, 50.0, 10.0)]
    _largeur, hauteur = mep.espace_libre(cadre, voisins, (200.0, 200.0))
    assert abs(hauteur - (80.0 - 10.0 - mep.GOUTTIERE)) < 0.01


def test_espace_libre_bute_sur_le_voisin_de_droite():
    cadre = (10.0, 10.0, 5.0, 5.0)
    voisins = [(60.0, 8.0, 30.0, 20.0)]
    largeur, _hauteur = mep.espace_libre(cadre, voisins, (200.0, 200.0))
    assert abs(largeur - (60.0 - 10.0 - mep.GOUTTIERE)) < 0.01


# --- Blocs de mentions convertis depuis du HTML ------------------------------
_ADRESSE = (
    "<strong>Vidallac - 09240 Alzen</strong><br />\n"
    "<strong>05 61 65 80 54 - https://ariegenature.fr</strong><br />\n"
    "SIRET 393 302 104 00046 - APE 9104Z<br />\n<br />\n"
    "<strong>L'ANA-CEN Ariège est labellisée centre permanent</strong>"
)


def test_texte_nu_compte_les_sauts_de_ligne():
    lignes = mep.texte_nu(_ADRESSE).split("\n")
    assert "Vidallac - 09240 Alzen" in lignes
    assert "<strong>" not in mep.texte_nu(_ADRESSE)


def test_un_bloc_serre_reduit_le_corps():
    """Le cadre de l'adresse fait 37 × 12 mm dans le gabarit A4."""
    serre = mep.taille_pour_bloc(_ADRESSE, 37.0, 12.0)
    large = mep.taille_pour_bloc(_ADRESSE, 90.0, 60.0)
    assert serre < large
    assert serre >= mep.TAILLES_MENTION[-1]


def test_un_bloc_court_garde_un_corps_lisible():
    assert mep.taille_pour_bloc("<strong>Fond.</strong> BD ORTHO®, IGN.",
                                70.0, 8.0) >= 6.0


def test_bloc_vide_ne_divise_pas_par_zero():
    assert mep.taille_pour_bloc("", 37.0, 12.0) == mep.TAILLES_MENTION[0]
    assert mep.taille_pour_bloc(_ADRESSE, 0.0, 0.0) == mep.TAILLES_MENTION[0]


# --- Gabarits ----------------------------------------------------------------
def test_libelle_lisible():
    assert gb.libelle("/x/carte_seule_pleine_page_a4_cen.qpt") == \
        "carte seule pleine page a4 cen"
    assert gb.libelle("") == "gabarit"


def test_variables_de_fond_eteignent_les_autres():
    """Citer un fond qu'on n'affiche pas est une erreur de source."""
    variables = gb.variables_fond("bd_ortho")
    assert variables[gb.VAR_FOND["bd_ortho"]] == "1"
    assert variables[gb.VAR_FOND["scan25"]] == ""
    assert variables[gb.VAR_FOND["cartes_ign"]] == ""


def test_aucun_fond_cite():
    assert set(gb.variables_fond("").values()) == {""}


def test_trouver_ignore_les_dossiers_absents(tmp_path=None):
    assert gb.trouver(["/dossier/qui/n/existe/pas"]) == []
    assert gb.trouver([]) == []
    assert gb.trouver(None) == []


def test_trouver_dedoublonne_et_priorise_le_premier_dossier():
    import os
    import shutil
    import tempfile

    partage = tempfile.mkdtemp()
    local = tempfile.mkdtemp()
    try:
        for dossier in (partage, local):
            with open(os.path.join(dossier, "carte_a4.qpt"), "w") as fh:
                fh.write("<Layout/>")
        with open(os.path.join(local, "carte_a3.qpt"), "w") as fh:
            fh.write("<Layout/>")
        trouves = gb.trouver([partage, local])
        assert len(trouves) == 2  # le doublon n'est compté qu'une fois
        a4 = [c for c in trouves if c.endswith("carte_a4.qpt")]
        assert a4 and a4[0].startswith(partage)  # le partage l'emporte
    finally:
        shutil.rmtree(partage, ignore_errors=True)
        shutil.rmtree(local, ignore_errors=True)
