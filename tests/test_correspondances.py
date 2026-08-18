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

import champs as ch
import correspondances as co
import export

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


def test_par_determination_ne_trouve_que_les_determinations():
    catalogue = _catalogue()
    assert catalogue.par_determination(16480).nom == "Nitellion flexilis"
    assert catalogue.par_determination("16480").nom == "Nitellion flexilis"
    # 4289 est l'ANCRE de « Hyperico montani-Quercion petraeae » : pas elle.
    assert catalogue.par_determination(4289) is None
    assert catalogue.par_determination(999999) is None


# -------------------------------------------------------------- chargement
def test_catalogue_absent_ne_fait_pas_echouer():
    """Sans catalogue, le plugin reste utilisable : HABREF est la voie normale."""
    catalogue = co.charger("/inexistant/dictionnaire.csv")
    assert len(catalogue) == 0
    assert catalogue.chercher("quercion") == []


def test_catalogue_livre_avec_le_plugin():
    """Le CSV livré doit se charger et être cohérent avec l'import qui l'a produit."""
    catalogue = co.charger(CATALOGUE_LIVRE)
    assert len(catalogue) == 227
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
    assert catalogue.par_determination(1204) is None
    assert catalogue.par_determination(16480).nom == "Nitellion flexilis"


# ------------------- compléter les libellés des correspondances déjà arbitrées
def _bloc(**corresp):
    import eval_fields as ef
    return ef.encode_eval("Relevé du 12 mai.", enjeu="fort", corresp=corresp)


def _bloc_ancien(**corresp):
    """Bloc à la forme d'avant la 0.11.0, monté à la main.

    `encode_eval` ne sait plus produire cette forme — code et libellé ne font
    plus partie du format. Or c'est exactement ce qui dort dans les bases : il
    faut donc l'écrire ici pour avoir quoi alléger.
    """
    import json
    import eval_fields as ef
    contenu = json.dumps({"enjeu": "fort", "corresp": corresp}, ensure_ascii=False,
                         sort_keys=True)
    return "Relevé du 12 mai.\n\n%s %s %s" % (ef.EVAL_START, contenu, ef.EVAL_END)


def test_reperer_les_correspondances_a_alleger():
    """Celles d'avant la 0.11.0 recopient code et libellé."""
    ancien = _bloc_ancien(
        EUNIS={"cd_hab": 1778, "code": "F9.1", "src": "manuel"},
        CORINE_biotopes={"cd_hab": 1378, "code": "44.1",
                         "nom": "Formations riveraines de Saules",
                         "src": "catalogue"})
    assert co.correspondances_a_alleger(ancien)
    assert not co.correspondances_a_alleger("")
    # Un bloc déjà court n'est pas à reprendre : sans quoi chaque passage
    # marquerait toutes les stations « à synchroniser » pour rien.
    assert not co.correspondances_a_alleger(
        _bloc(EUNIS={"cd_hab": 1778, "src": "manuel"}))


def test_alleger_ne_perd_que_le_code_et_le_libelle():
    import eval_fields as ef
    ancien = _bloc_ancien(
        EUNIS={"cd_hab": 1778, "code": "F9.1", "src": "manuel"},
        CORINE_biotopes={"cd_hab": 1378, "code": "44.1", "nom": "Déjà là",
                         "src": "catalogue"})
    court = co.alleger_correspondances(ancien)
    assert len(court) < len(ancien)
    lu = ef.decode_eval(court)
    # Ce qui fait la correspondance survit : le cd_hab, et d'où elle vient.
    assert lu["corresp"]["EUNIS"] == {"cd_hab": 1778, "src": "manuel"}
    assert lu["corresp"]["CORINE_biotopes"] == {"cd_hab": 1378, "src": "catalogue"}
    # Le reste du bloc est intact : c'est un allègement, pas une réécriture.
    assert lu["enjeu"] == "fort"
    assert ef.strip_eval(court) == "Relevé du 12 mai."


def test_alleger_ramene_un_bloc_sous_la_limite_du_champ():
    """C'est tout l'objet : GeoNature refuse la station entière au-delà de 500."""
    quatre = {
        "CORINE_biotopes": {"cd_hab": 3972, "code": "22.41",
                            "nom": "Végétations flottant librement", "src": "manuel"},
        "EUNIS": {"cd_hab": 5273, "code": "E3.44",
                  "nom": "Gazons inondés et communautés apparentées", "src": "manuel"},
        "Cahiers_d'habitats": {
            "cd_hab": 1234, "code": "3150-1",
            "nom": "Plans d'eau eutrophes avec dominance de macrophytes libres flottants",
            "src": "manuel"},
        "Habitats_d'intérêt_communautaire": {
            "cd_hab": 4321, "code": "3150",
            "nom": "Lacs eutrophes naturels avec végétation du Magnopotamion",
            "src": "manuel"},
    }
    ancien = _bloc_ancien(**quatre)
    assert len(ancien) > 500
    court = co.alleger_correspondances(ancien)
    assert len(court) <= 500
    # Les quatre correspondances sont toutes encore là.
    import eval_fields as ef
    assert len(ef.decode_eval(court)["corresp"]) == 4


def test_rien_a_alleger_ne_reecrit_rien():
    """Sans changement, on ne touche pas au bloc : pas de station marquée à
    synchroniser pour rien. L'opération est donc idempotente."""
    ancien = _bloc_ancien(EUNIS={"cd_hab": 1778, "code": "F9.1", "src": "manuel"})
    court = co.alleger_correspondances(ancien)
    assert court is not None
    assert co.alleger_correspondances(court) is None
    assert co.alleger_correspondances("") is None


# --------------------------- rapprocher une forme abrégée de sa forme complète
def test_squelette_reduit_aux_genres():
    """HABREF abrège, le catalogue développe : les deux doivent se rejoindre.

    `Eleocharito-Sagittarion` (HABREF) et `Eleocharito palustris-Sagittarion
    sagittifoliae` (catalogue) sont la même végétation. Sans ce rapprochement,
    ses correspondances restaient introuvables dès qu'elle était choisie sous sa
    forme courte — six polygones sans aucune proposition, sur le terrain.
    """
    assert co.squelette("Eleocharito-Sagittarion") == "eleocharito-sagittarion"
    assert co.squelette("Eleocharito palustris-Sagittarion sagittifoliae") == \
        "eleocharito-sagittarion"
    assert co.squelette("Brachypodio-Centaureion nemoralis") == \
        co.squelette("Brachypodio rupestris-Centaureion nemorali")


def test_squelette_epargne_ce_qui_n_est_pas_un_syntaxon():
    """Un intitulé français n'est pas une nomenclature latine : le réduire à son
    premier mot rapprocherait n'importe quoi de n'importe quoi."""
    assert co.squelette("Cultures et jardins maraîchers") == \
        "cultures et jardins maraichers"
    assert co.squelette("") == ""
    assert co.squelette(None) == ""


def test_squelette_ne_coupe_que_sur_un_suffixe_de_syntaxon():
    """C'est le DERNIER membre qui décide : lui seul porte le rang du syntaxon."""
    assert co.squelette("Alno glutinosae-Salicion cinereae") == "alno-salicion"
    # Pas de suffixe reconnu en fin de nom → aucune réduction.
    assert co.squelette("Carex rostrata Stokes") == "carex rostrata stokes"


def test_par_nom_approche_retrouve_l_alliance():
    catalogue = co.Catalogue([
        _alliance(alliance="Eleocharito palustris-Sagittarion sagittifoliae",
                  cd_hab="", ancre_cd_hab="1204",
                  ancre_typologie="CORINE_biotopes", ancre_code="53.14A"),
        _alliance(alliance="Cultures et jardins maraîchers", cd_hab="17000"),
    ])
    assert catalogue.par_nom_approche("Eleocharito-Sagittarion").nom == \
        "Eleocharito palustris-Sagittarion sagittifoliae"
    # Identité exacte : elle passe par le même index, sans traitement à part.
    assert catalogue.par_nom_approche("Cultures et jardins maraîchers") is not None
    assert catalogue.par_nom_approche("Nardion strictae") is None
    assert catalogue.par_nom_approche("") is None
    assert catalogue.par_nom_approche(None) is None


def test_par_nom_approche_refuse_de_trancher_entre_deux_syntaxons():
    """Même squelette, deux alliances : on ne propose RIEN.

    « Rubo caesii-Populion nigrae » et « Rubo ulmifolii-Populion albae » se
    réduisent tous deux à « rubo-populion ». En choisir un écrirait ses
    correspondances sur l'autre — une erreur de donnée que rien ne signale.
    Le catalogue livré en compte deux paires.
    """
    catalogue = co.Catalogue([
        _alliance(ligne_xlsx="10", alliance="Rubo caesii-Populion nigrae", cd_hab="1"),
        _alliance(ligne_xlsx="11", alliance="Rubo ulmifolii-Populion albae", cd_hab="2"),
    ])
    assert catalogue.par_nom_approche("Rubo-Populion") is None
    # Sous son nom complet, chacune reste parfaitement identifiable.
    assert catalogue.par_nom_approche("Rubo caesii-Populion nigrae").ligne == 10
    assert catalogue.par_nom_approche("Rubo ulmifolii-Populion albae").ligne == 11


def test_un_nom_simple_ne_perd_jamais_son_epithete():
    """Le catalogue porte cinq « Salicion » et quatre « Caricion ».

    Réduire « Salicion cinereae » à « Salicion » les confondait tous : la
    première ligne venue emportait la mise, et ses correspondances partaient sur
    quatre autres végétations. L'abréviation qu'on rattrape ne se produit que
    sur les noms à deux genres.
    """
    assert co.squelette("Salicion cinereae") == "salicion cinereae"
    assert co.squelette("Caricion gracilis") != co.squelette("Caricion remotae")
    catalogue = co.Catalogue([
        _alliance(ligne_xlsx="10", alliance="Caricion remotae", cd_hab="1"),
        _alliance(ligne_xlsx="11", alliance="Caricion fuscae", cd_hab="2"),
    ])
    assert catalogue.par_nom_approche("Caricion gracilis") is None
    assert catalogue.par_nom_approche("Caricion remotae").ligne == 10


def test_le_catalogue_livre_n_a_aucun_squelette_ambigu_indexe():
    """Garde-fou sur le VRAI fichier : deux paires s'y réduisent pareil."""
    cat = co.catalogue()
    par_squelette = {}
    for alliance in cat.alliances:
        par_squelette.setdefault(co.squelette(alliance.nom), set()).add(
            co.normaliser(alliance.nom))
    for sq, noms in par_squelette.items():
        if len(noms) > 1:
            assert cat.par_nom_approche(sq) is None, sq


# --------------------------- nettoyer un libellé HABREF sans l'amputer
def test_nom_habref_coupe_le_code_de_tete_et_le_doublon():
    assert co.nom_habref(
        "6.0.1.0.2 - Brachypodio rupestris-Centaureion nemoralis "
        "Brachypodio rupestris-Centaureion nemoralis Br.-Bl. 1967"
    ) == "Brachypodio rupestris-Centaureion nemoralis"
    # Habitat sans code : le séparateur commence par l'espace de tête.
    assert co.nom_habref(
        " - Brachypodio-Centaureion nemoralis Brachypodio-Centaureion "
        "nemoralis Br.-Bl. 1967"
    ) == "Brachypodio-Centaureion nemoralis"


def test_nom_habref_n_ampute_pas_un_syntaxon_a_tiret_espace():
    """Certains noms portent un tiret ESPACÉ, comme le séparateur du code.

    Couper au premier « - » venu rendait « Blackstonion perfoliatae » — la
    moitié d'un nom d'alliance, parfaitement plausible et donc invisible.
    """
    for nom in ("Centaurio pulchelli - Blackstonion perfoliatae",
                "Loto pedunculati - Filipenduletalia ulmariae",
                "Mentho longifoliae - Juncion inflexi"):
        assert co.nom_habref(nom) == nom


def test_nom_habref_est_idempotente():
    """C'est ce qui permet de rattraper un libellé déjà mis en cache."""
    for brut in ("18.0.1.0.1 - Nitellion flexilis Nitellion flexilis Segal 1969",
                 "Caricion gracilis Caricion gracilis Neuhäusl 1959",
                 "Réseaux de transport et autres zones à surface dure",
                 "Cynosurion cristati", "", None):
        propre = co.nom_habref(brut)
        assert co.nom_habref(propre) == propre


def test_un_libelle_au_nom_repete_redevient_trouvable():
    """Le cas réel : 12 libellés en cache portaient le nom répété.

    Le squelette d'un tel libellé se termine par « Bl. 1967 » — plus rien d'un
    syntaxon —, donc l'alliance restait introuvable et ses correspondances
    avec elle.
    """
    brut = ("Brachypodio rupestris-Centaureion nemoralis Brachypodio "
            "rupestris-Centaureion nemoralis Br.-Bl. 1967")
    catalogue = co.Catalogue([
        _alliance(alliance="Brachypodio rupestris-Centaureion nemorali",
                  cd_hab="", ancre_cd_hab="4314",
                  ancre_typologie="CORINE_biotopes", ancre_code="38.21"),
    ])
    assert catalogue.par_nom_approche(brut) is None
    assert catalogue.par_nom_approche(co.nom_habref(brut)) is not None


# ------------- le code du bloc ancien vaut mieux qu'un cd_hab nu à l'affichage
#: Bloc réel du poste d'une utilisatrice (habitat 2568, « Caricion gracilis ») :
#: ses deux correspondances ont été arbitrées à la main, et leurs `cd_hab` sont
#: étrangers au catalogue livré. Le bloc, lui, porte encore les codes.
_BLOC_ANCIEN_HORS_CATALOGUE = (
    '[ANA-EVAL] {"corresp": {'
    '"CORINE_biotopes": {"cd_hab": 17228, "code": "53.2142",'
    ' "nom": "Cariçaies à Carex vesicaria", "src": "manuel"},'
    ' "EUNIS": {"cd_hab": 17730, "code": "D5.2142",'
    ' "nom": "Cariçaies à Laîche vésiculeuse", "src": "manuel"}},'
    ' "recouvrement": 100} [/ANA-EVAL]'
)


def test_le_code_du_bloc_ancien_est_lisible():
    """`decode_eval` ne rend plus le code : il faut le relire dans le bloc brut."""
    assert co.code_stocke(_BLOC_ANCIEN_HORS_CATALOGUE,
                               "CORINE_biotopes") == "53.2142"
    assert co.code_stocke(_BLOC_ANCIEN_HORS_CATALOGUE, "EUNIS") == "D5.2142"
    assert co.nom_stocke(_BLOC_ANCIEN_HORS_CATALOGUE,
                              "CORINE_biotopes") == "Cariçaies à Carex vesicaria"


def test_l_allegement_garde_le_code_que_le_catalogue_ignore():
    """Ce bloc-ci porte deux correspondances arbitrées HORS catalogue.

    Les alléger effacerait la seule copie de leur code, et la colonne afficherait
    ensuite « 17228 » — un nombre, dans une colonne de codes. L'allègement ne
    retire donc que ce qu'il sait faire revenir.
    """
    allege = co.alleger_correspondances(_BLOC_ANCIEN_HORS_CATALOGUE) \
        or _BLOC_ANCIEN_HORS_CATALOGUE
    assert co.code_stocke(allege, "CORINE_biotopes") == "53.2142"
    assert co.code_stocke(allege, "EUNIS") == "D5.2142"
    # Le libellé, lui, part : c'est lui qui pesait.
    assert co.nom_stocke(allege, "CORINE_biotopes") is None
    assert "Cariçaies" not in allege


def test_sans_bloc_ni_typologie_le_code_stocke_ne_casse_pas():
    for mauvais in (None, "", "texte libre sans bloc", "[ANA-EVAL] pas du json [/ANA-EVAL]"):
        assert co.code_stocke(mauvais, "EUNIS") is None
        assert co.nom_stocke(mauvais, "EUNIS") is None


def test_la_colonne_montre_le_code_du_bloc_plutot_qu_un_cd_hab_nu():
    """Le cas signalé depuis le terrain : « 17228 » s'affichait dans une colonne
    de codes CORINE, où il se lit comme un code — alors que la donnée disait
    « 53.2142 ». Le catalogue ignore ce cd_hab ; le bloc, lui, savait."""
    habitat = {"technical_precision": _BLOC_ANCIEN_HORS_CATALOGUE}
    lues = {c.cle: ch.lire(habitat, c) for c in ch.CHAMPS
            if c.stockage == ch.CORRESP}
    assert lues["CORINE_biotopes"] == "53.2142", lues
    assert lues["EUNIS"] == "D5.2142", lues


def test_l_export_montre_le_code_du_bloc_plutot_qu_un_cd_hab_nu():
    """Même repli côté export : une colonne de codes ne doit pas recevoir un
    nombre quand la donnée porte le code."""
    station = ({"id_station": 1, "geom": "POINT(0 0)", "geom_type": "Point"},
               [{"id_habitat": 1, "cd_hab": 16508, "nom_cite": "Caricion gracilis",
                 "technical_precision": _BLOC_ANCIEN_HORS_CATALOGUE}], [])
    ligne = export.flatten_cartography([station], code_corresp=lambda _cd: None)[0]
    assert ligne["corine_cite"] == "53.2142"
    assert ligne["eunis_cite"] == "D5.2142"
