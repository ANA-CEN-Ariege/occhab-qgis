# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du catalogue des végétations (module pur `correspondances`).

Deux choses sont vérifiées ici plus que les autres :

- **ancre ≠ détermination.** 43 alliances n'ont pas d'entrée HABREF et portent
  un code CORINE d'emprunt. Confondre les deux, c'est faire passer une
  approximation pour une détermination dans un livrable Natura 2000 ;
- **la recherche trouve malgré les tirets.** Le catalogue écrit « – », HABREF
  « - » ; une recherche qui échoue sur ce seul motif fait conclure au botaniste
  que son alliance est absente.

Les tests portent sur un catalogue construit ici, sauf le dernier qui contrôle
le fichier réellement livré avec le plugin.
"""
import os

import correspondances as co

_ICI = os.path.dirname(os.path.abspath(__file__))
CATALOGUE_LIVRE = os.path.join(
    os.path.dirname(_ICI), "resources", "typologie", "dictionnaire_typologie.csv"
)


def _alliance(**valeurs):
    ligne = {"ligne_xlsx": "3", "alliance": "Nitellion flexilis",
             "classe": "Charetea fragilis"}
    ligne.update(valeurs)
    return co.Alliance(ligne)


# ------------------------------------------------------------ normalisation
def test_recherche_insensible_aux_tirets():
    """« – » du tableur et « - » de HABREF doivent se chercher pareil."""
    assert co.normaliser("Achilleo ptarmicae – Cirsion palustris") == \
        co.normaliser("Achilleo ptarmicae-Cirsion palustris")


# --------------------------------------------------------- ancre ≠ détermination
def test_alliance_resolue_pose_son_cd_hab():
    alliance = _alliance(cd_hab="16480", typologie="PVF1", code_habref="18.0.1.0.1")
    assert not alliance.est_ancree
    assert alliance.cd_hab_a_poser == 16480


def test_alliance_ancree_pose_l_ancre_et_le_dit():
    """Le code posé est un emprunt : `est_ancree` doit le signaler."""
    alliance = _alliance(
        alliance="Salicion pyrenaicae", cd_hab="",
        ancre_cd_hab="1204", ancre_typologie="CORINE_biotopes", ancre_code="22.3",
    )
    assert alliance.est_ancree
    assert alliance.cd_hab_a_poser == 1204
    assert "ancre" in alliance.libelle()


def test_alliance_sans_code_n_est_pas_saisissable():
    """`cd_hab` est obligatoire côté OccHab : sans code, rien à poser."""
    alliance = _alliance(cd_hab="", ancre_cd_hab="")
    assert not alliance.est_saisissable
    assert alliance.cd_hab_a_poser is None


# ------------------------------------------------------------ correspondances
def test_correspondances_lues_par_typologie_habref():
    alliance = _alliance(
        corine_cd_hab="9403", corine_code="22.442",
        eunis_cd_hab="10829", eunis_code="C1.142",
        n2000_cd_hab="2757", n2000_code="3140",
    )
    corresp = alliance.correspondances()
    assert corresp["CORINE_biotopes"]["cd_hab"] == 9403
    assert corresp["CORINE_biotopes"]["code"] == "22.442"
    assert corresp["EUNIS"]["code"] == "C1.142"
    assert corresp["Habitats_d'intérêt_communautaire"]["cd_hab"] == 2757
    assert "Cahiers_d'habitats" not in corresp  # colonne vide → clé absente


def test_correspondances_rendues_en_copie():
    """L'appelant y ajoute `src` : il ne doit pas modifier le catalogue."""
    alliance = _alliance(eunis_cd_hab="10829", eunis_code="C1.142")
    corresp = alliance.correspondances()
    corresp["EUNIS"]["src"] = "catalogue"
    assert "src" not in alliance.correspondances()["EUNIS"]


# ------------------------------------------------------------------ recherche
def _catalogue():
    return co.Catalogue([
        _alliance(alliance="Quercion pubescenti-petraeae", cd_hab="",
                  ancre_cd_hab="4300", ancre_typologie="CORINE_biotopes",
                  ancre_code="41.71"),
        _alliance(alliance="Hyperico montani-Quercion petraeae", cd_hab="",
                  ancre_cd_hab="4289", ancre_typologie="CORINE_biotopes",
                  ancre_code="41.12"),
        _alliance(alliance="Nitellion flexilis", cd_hab="16480", typologie="PVF1"),
    ])


def test_recherche_privilegie_le_debut_du_nom():
    """« quercion » : l'alliance qui commence par ce mot d'abord."""
    trouves = _catalogue().chercher("quercion")
    assert [a.nom for a in trouves] == [
        "Quercion pubescenti-petraeae", "Hyperico montani-Quercion petraeae",
    ]


def test_recherche_sur_la_classe():
    """On ne se rappelle pas toujours l'alliance, toujours le grand type."""
    assert [a.nom for a in _catalogue().chercher("charetea")]


def test_recherche_vide_ne_rend_rien():
    assert _catalogue().chercher("") == []


def test_par_cd_hab_trouve_determination_et_ancre():
    catalogue = _catalogue()
    assert catalogue.par_cd_hab(16480).nom == "Nitellion flexilis"
    assert catalogue.par_cd_hab("4289").nom == "Hyperico montani-Quercion petraeae"
    assert catalogue.par_cd_hab(999999) is None


# -------------------------------------------------------------- chargement
def test_catalogue_absent_ne_fait_pas_echouer():
    """Sans catalogue, le plugin reste utilisable : HABREF est la voie normale."""
    catalogue = co.charger("/inexistant/dictionnaire.csv")
    assert len(catalogue) == 0
    assert catalogue.chercher("quercion") == []


def test_catalogue_livre_avec_le_plugin():
    """Le CSV livré doit se charger et être cohérent avec l'import qui l'a produit."""
    catalogue = co.charger(CATALOGUE_LIVRE)
    assert len(catalogue) == 225
    assert len(catalogue.ancrees()) == 43
    # Toute alliance doit pouvoir être saisie : c'est ce que l'import garantit.
    assert [a.nom for a in catalogue.alliances if not a.est_saisissable] == []


# ------------------------------------------- plusieurs lignes pour une alliance
def test_le_libelle_montre_les_correspondances():
    """Sans elles, quatre variantes d'une même alliance sont indiscernables."""
    alliance = _alliance(corine_cd_hab="9941", corine_code="41.112",
                         eunis_cd_hab="5537", eunis_code="G1.62")
    assert alliance.libelle_correspondances() == \
        "CORINE biotopes 41.112 · EUNIS G1.62"
    assert "41.112" in alliance.libelle()


def test_libelle_sans_correspondance_reste_lisible():
    assert _alliance(cd_hab="16480", typologie="PVF1").libelle_correspondances() == ""


def _quatre_variantes():
    """Le cas réel : `Luzulo luzuloidis – Fagion sylvaticae` a quatre lignes."""
    return co.Catalogue([
        _alliance(alliance="Luzulo luzuloidis – Fagion sylvaticae",
                  cd_hab="16402", typologie="PVF1", code_habref="57.0.3.3.3",
                  corine_code=code, corine_cd_hab=cd_corine, corine_nom=nom,
                  eunis_code=eunis, eunis_cd_hab=cd_eunis)
        for code, cd_corine, nom, eunis, cd_eunis in (
            ("41.112", "1", "Hêtraies montagnardes à Luzule", "G1.62", "10"),
            ("41.172", "2", "Hêtraies acidiphiles des Pyrénées", "G1.672", "11"),
            ("42.113", "3", "Sapinières intra-pyrénéennes", "G3.113", "12"),
            ("41.112", "1", "Hêtraies montagnardes à Luzule", "G1.612", "13"),
        )
    ])


def test_une_seule_proposition_pour_une_alliance_a_variantes():
    """Quatre lignes de même nom ne font qu'une proposition : elles sont
    indiscernables à l'écran, et c'est la correspondance qui se choisit ensuite.

    Sans NOMBRE dans le libellé : deux des quatre variantes partagent leur code
    CORINE, la liste n'en proposera donc que trois. Annoncer « 4 » ferait
    chercher une option qui n'existe pas.
    """
    trouves = _quatre_variantes().chercher("luzulo")
    assert len(trouves) == 1
    assert "correspondances à choisir" in trouves[0].libelle()
    assert "4" not in trouves[0].libelle_correspondances()


def test_candidats_dedoublonnes_sur_le_cd_hab():
    """Deux variantes partagent le CORINE 41.112 : un seul choix doit apparaître."""
    alliance = _quatre_variantes().chercher("luzulo")[0]
    corine = alliance.candidats("CORINE_biotopes")
    assert [c["code"] for c in corine] == ["41.112", "41.172", "42.113"]
    assert corine[0]["nom"] == "Hêtraies montagnardes à Luzule"
    assert len(alliance.candidats("EUNIS")) == 4


def test_candidats_d_une_typologie_absente():
    assert _quatre_variantes().chercher("luzulo")[0].candidats("Cahiers_d'habitats") == []


def test_le_catalogue_livre_porte_bien_ces_quatre_variantes():
    catalogue = co.charger(CATALOGUE_LIVRE)
    assert len(catalogue.chercher("Luzulo luzuloidis")) == 1
    alliance = catalogue.chercher("Luzulo luzuloidis")[0]
    assert len(alliance.variantes) == 4
    # Le libellé de chaque candidat doit être lisible sans connaître le code.
    assert all(c["nom"] for c in alliance.candidats("EUNIS"))


# ------------------------------------------- correspondances publiées par HABREF
_FICHE = {
    "cd_hab": 23597, "cd_typo": 17, "lb_code": "57.0.4.1.1.2.1",
    "correspondances": [
        {"cd_typo_sortie": 4, "habref": {
            "cd_hab": 1091, "lb_code": "92A0",
            "lb_hab_fr": "Forêts galeries à Salix alba et Populus alba"}},
        {"cd_typo_sortie": 4, "habref": {
            "cd_hab": 8884, "lb_code": "92A0-7",
            "lb_hab_fr": "Aulnaies-Frênaies à Frêne oxyphylle"}},
        # même cible deux fois : HABREF publie parfois la relation dans les deux sens
        {"cd_typo_sortie": 4, "habref": {"cd_hab": 1091, "lb_code": "92A0"}},
        # typologie hors cibles (Unités phytosociologiques) : ignorée
        {"cd_typo_sortie": 17, "habref": {"cd_hab": 20629, "lb_code": "57.0.4.1.1.2"}},
    ],
}
_NOMS = {4: "Cahiers_d'habitats", 17: "Unités_phytosociologiques", 22: "CORINE_biotopes"}


def test_candidats_habref_avec_libelles():
    """Le libellé vient avec : c'est lui qui rend le code choisissable."""
    candidats = co.candidats_habref(_FICHE, _NOMS)
    assert list(candidats) == ["Cahiers_d'habitats"]
    assert [c["code"] for c in candidats["Cahiers_d'habitats"]] == ["92A0", "92A0-7"]
    assert candidats["Cahiers_d'habitats"][1]["nom"] == "Aulnaies-Frênaies à Frêne oxyphylle"


def test_candidats_habref_sans_noms_de_typologie():
    """Sans la table des typologies, ne rien proposer plutôt que de deviner."""
    assert co.candidats_habref(_FICHE, None) == {}


def test_candidats_habref_fiche_vide():
    assert co.candidats_habref(None, _NOMS) == {}
    assert co.candidats_habref({}, _NOMS) == {}


# ---------------------------------------- une ancre n'attribue rien à personne
def test_par_determination_ignore_les_ancres():
    """Déterminer directement un code d'ancre ne détermine pas l'alliance.

    Une ancre est un code CORINE emprunté, partagé avec bien d'autres habitats.
    Lui rendre l'alliance qui l'emprunte ferait affirmer à l'habitat un syntaxon
    que personne n'a déterminé — avec ses correspondances, marquées « reprises
    du catalogue ».
    """
    catalogue = co.Catalogue([
        _alliance(alliance="Salicion pyrenaicae", cd_hab="",
                  ancre_cd_hab="1204", ancre_typologie="CORINE_biotopes",
                  ancre_code="22.3", eunis_cd_hab="1672", eunis_code="C3.4"),
        _alliance(alliance="Nitellion flexilis", cd_hab="16480", typologie="PVF1"),
    ])
    assert catalogue.par_cd_hab(1204).nom == "Salicion pyrenaicae"   # affichage
    assert catalogue.par_determination(1204) is None                 # attribution
    assert catalogue.par_determination(16480).nom == "Nitellion flexilis"
