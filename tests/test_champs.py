# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du registre de champs (module pur `champs`)."""
import champs as ch
import eval_fields as ef
import payload
import referentiels as ref


# ------------------------------------------------------------- structure
def test_cles_uniques_par_niveau():
    """`enjeu` existe aux deux niveaux ; un doublon DANS un niveau serait un bug."""
    for niveau in (ch.STATION, ch.HABITAT):
        cles = [c.cle for c in ch.du_niveau(niveau)]
        assert len(cles) == len(set(cles)), sorted(cles)


def test_par_cle_distingue_les_niveaux():
    station = ch.par_cle(ch.STATION, "enjeu")
    habitat = ch.par_cle(ch.HABITAT, "enjeu")

    assert station is not habitat
    assert ch.PORTEUR[station.niveau] == "comment"
    assert ch.PORTEUR[habitat.niveau] == "technical_precision"
    assert ch.par_cle(ch.STATION, "typicite") is None  # champ d'habitat


def test_champs_eval_declarent_une_cle_connue_du_bloc():
    """Un champ EVAL dont la clé n'est pas reconnue par `eval_fields` ne serait
    jamais écrit : la valeur disparaîtrait sans erreur."""
    for champ in ch.CHAMPS:
        if champ.stockage not in (ch.EVAL, ch.DOUBLE):
            continue
        temoin = _valeur_temoin(champ)
        assert ef.decode_eval(ef.encode_eval("", **{champ.cle: temoin})), champ.cle


def test_champs_a_referentiel_bien_appareilles():
    for champ in ch.CHAMPS:
        if champ.type == ch.CODE:
            assert champ.referentiel, champ.cle
        if champ.type == ch.NOMENCLATURE:
            assert champ.nomenclature, champ.cle


def test_un_champ_non_effacable_ne_part_jamais_a_null():
    """Le registre et le payload doivent dire la même chose.

    Les deux listes ont divergé une fois : `id_nomenclature_geographic_object`
    était rangé parmi les effaçables alors que sa colonne est NOT NULL, et toute
    mise à jour d'une station au champ vide se faisait rejeter en 500.
    """
    non_effacables = {c.cle for c in ch.du_niveau(ch.STATION) if not c.effacable}

    assert non_effacables, "aucun champ non effaçable : le drapeau ne sert plus"
    assert not (non_effacables & payload.EFFACABLES_STATION)


def test_modifiables_en_masse_excluent_le_calcule_et_le_technique():
    masse = {(c.niveau, c.cle) for c in ch.modifiables_en_masse()}

    assert (ch.STATION, "area") not in masse         # calculé depuis la géométrie
    assert (ch.STATION, "sync_status") not in masse  # état technique
    assert (ch.STATION, "comment") not in masse      # texte libre
    # …et incluent bien ce qu'on veut pousser en lot.
    assert (ch.STATION, "id_dataset") in masse
    assert (ch.STATION, "date_min") in masse
    assert (ch.HABITAT, "typicite") in masse
    assert (ch.STATION, "validation_status") in masse


def test_identite_de_l_habitat_modifiable_en_masse_et_indissociable():
    """Corriger une détermination doit pouvoir se propager à des dizaines de
    polygones — mais le code et le nom doivent rester modifiables ENSEMBLE.

    Si l'un des deux sortait de la liste, l'interface d'application en masse ne
    proposerait plus qu'une moitié du couple et laisserait des habitats dont le
    cd_hab ne correspond plus au nom cité.
    """
    masse = {(c.niveau, c.cle) for c in ch.modifiables_en_masse()}

    assert (ch.HABITAT, "cd_hab") in masse
    assert (ch.HABITAT, "nom_cite") in masse


# ------------------------------------------------------------- accesseurs
def test_lire_ecrire_colonne():
    champ = ch.par_cle(ch.STATION, "station_name")
    station = {}

    ch.ecrire(station, champ, "Soula 01")

    assert station["station_name"] == "Soula 01"
    assert ch.lire(station, champ) == "Soula 01"


def test_lire_ecrire_eval_station_et_habitat():
    station, habitat = {}, {}
    ch.ecrire(station, ch.par_cle(ch.STATION, "enjeu"), "fort")
    ch.ecrire(habitat, ch.par_cle(ch.HABITAT, "typicite"), "bonne")

    # Chacun dans SON porteur.
    assert "enjeu" in station["comment"]
    assert "technical_precision" in habitat
    assert ch.lire(station, ch.par_cle(ch.STATION, "enjeu")) == "fort"
    assert ch.lire(habitat, ch.par_cle(ch.HABITAT, "typicite")) == "bonne"


def test_ecrire_un_champ_eval_preserve_les_autres():
    """Le risque principal du stockage en bloc : s'écraser soi-même."""
    habitat = {}
    for cle, valeur in (("typicite", "bonne"), ("dynamique", "stable"),
                        ("restauration", "possible"), ("enjeu", "fort")):
        ch.ecrire(habitat, ch.par_cle(ch.HABITAT, cle), valeur)

    codes = ef.decode_eval(habitat["technical_precision"])
    assert codes == {"typicite": "bonne", "dynamique": "stable",
                     "restauration": "possible", "enjeu": "fort"}


def test_texte_libre_ne_detruit_pas_le_bloc():
    habitat = {}
    ch.ecrire(habitat, ch.par_cle(ch.HABITAT, "typicite"), "bonne")

    ch.ecrire(habitat, ch.par_cle(ch.HABITAT, "technical_precision"), "Relevé partiel.")

    assert ch.lire(habitat, ch.par_cle(ch.HABITAT, "typicite")) == "bonne"
    assert ch.lire(habitat, ch.par_cle(ch.HABITAT, "technical_precision")) == "Relevé partiel."


def test_bloc_ne_detruit_pas_le_texte_libre():
    habitat = {}
    ch.ecrire(habitat, ch.par_cle(ch.HABITAT, "technical_precision"), "Relevé partiel.")

    ch.ecrire(habitat, ch.par_cle(ch.HABITAT, "typicite"), "moyenne")

    assert ch.lire(habitat, ch.par_cle(ch.HABITAT, "technical_precision")) == "Relevé partiel."
    assert ch.lire(habitat, ch.par_cle(ch.HABITAT, "typicite")) == "moyenne"


def test_recouvrement_ecrit_dans_la_colonne_native_seule():
    """La colonne OccHab suffit : la clé du bloc ferait doublon."""
    champ = ch.par_cle(ch.HABITAT, "recouvrement")
    habitat = {}

    ch.ecrire(habitat, champ, 60)

    assert habitat["recovery_percentage"] == 60
    # Pas de porteur créé pour rien : sans clé à purger, on n'y touche pas.
    assert "technical_precision" not in habitat
    assert ch.lire(habitat, champ) == 60


def test_recouvrement_purge_la_cle_d_un_bloc_ancien():
    """Écrire nettoie le bloc, sans toucher aux autres clés ni au texte libre."""
    champ = ch.par_cle(ch.HABITAT, "recouvrement")
    habitat = {
        "recovery_percentage": 30,
        "technical_precision": ef.encode_eval(
            "Relevé partiel.", recouvrement=30, typicite="bonne"
        ),
    }

    ch.ecrire(habitat, champ, 60)

    assert habitat["recovery_percentage"] == 60
    assert "recouvrement" not in ef.decode_eval(habitat["technical_precision"])
    assert ef.decode_eval(habitat["technical_precision"])["typicite"] == "bonne"
    assert ch.lire(habitat, ch.par_cle(ch.HABITAT, "technical_precision")) == \
        "Relevé partiel."
    assert ch.lire(habitat, champ) == 60


def test_recouvrement_la_colonne_prime_sur_un_bloc_perime():
    """Un recouvrement corrigé dans GeoNature ne doit pas être masqué.

    Seule la colonne native est visible et modifiable côté web ; le bloc revient
    du serveur intact. Le faire primer réaffichait l'ancienne valeur.
    """
    champ = ch.par_cle(ch.HABITAT, "recouvrement")
    habitat = {
        "recovery_percentage": 40,
        "technical_precision": ef.encode_eval("", recouvrement=30),
    }

    assert ch.lire(habitat, champ) == 40


def test_recouvrement_repli_sur_le_bloc():
    """Habitat antérieur à la colonne : le bloc reste la seule source."""
    champ = ch.par_cle(ch.HABITAT, "recouvrement")
    habitat = {"technical_precision": ef.encode_eval("", recouvrement=30)}

    assert ch.lire(habitat, champ) == 30


def test_lire_objet_vide_ou_none():
    for champ in ch.CHAMPS:
        assert ch.lire({}, champ) is None
        assert ch.lire(None, champ) is None


def _valeur_temoin(champ):
    """Valeur valide plausible, pour vérifier qu'une clé est acceptée du bloc."""
    if champ.type == ch.CODE:
        return champ.referentiel[1][0]  # un code autre que le premier
    if champ.type == ch.BOOLEEN:
        return True
    if champ.type == ch.LISTE_TEXTE:
        return ["Reynoutria japonica"]
    if champ.type in (ch.POURCENTAGE,):
        return 50
    if champ.type == ch.ENTIER:
        return 5000
    return "texte"


# ------------------------------------------- correspondance champ -> colonnes
def test_colonnes_touchees_suit_le_stockage():
    """Contrepartie de `ecrire()` : où la valeur atterrit réellement."""
    assert ch.colonnes_touchees(ch.par_cle(ch.STATION, "station_name")) == {"station_name"}
    # EVAL : dans le bloc ANA-EVAL porté par le commentaire de la station.
    assert ch.colonnes_touchees(ch.par_cle(ch.STATION, "enjeu")) == {"comment"}
    # TEXTE_LIBRE : le commentaire lui-même, bloc préservé.
    assert ch.colonnes_touchees(ch.par_cle(ch.STATION, "comment")) == {"comment"}
    # DOUBLE : la colonne native, ET le bloc — dont l'écriture retire la clé.
    assert ch.colonnes_touchees(ch.par_cle(ch.HABITAT, "recouvrement")) == {
        "technical_precision", "recovery_percentage"}


def test_colonnes_touchees_couvre_tout_le_registre():
    """Aucun champ ne doit rendre un ensemble vide : il serait jamais enregistré."""
    for champ in ch.CHAMPS:
        assert ch.colonnes_touchees(champ), champ.cle


# ------------- la détermination et les correspondances survivent aux éditions
def _habitat_avec_correspondances():
    """Habitat portant une alliance ancrée et deux correspondances arbitrées."""
    return {"cd_hab": 1204, "nom_cite": "Subularion aquaticae",
            "technical_precision": ef.encode_eval(
                "Relevé du 12 mai.",
                enjeu="fort",
                determination={"nom": "Subularion aquaticae",
                               "ancre": "CORINE_biotopes"},
                corresp={"EUNIS": {"cd_hab": 1672, "code": "C3.4", "src": "manuel"}},
            )}


def test_editer_un_champ_du_bloc_preserve_les_correspondances():
    """La table attributaire écrit clé par clé : `merge_eval` doit garder le reste.

    Sans cela, changer l'enjeu d'une ligne effacerait l'arbitrage EUNIS de la
    même ligne — une perte silencieuse, et invisible à l'écran puisque la table
    n'affiche pas ces clés.
    """
    habitat = _habitat_avec_correspondances()
    ch.ecrire(habitat, ch.par_cle(ch.HABITAT, "enjeu"), "faible")
    codes = ef.decode_eval(habitat["technical_precision"])
    assert codes["enjeu"] == "faible"
    assert codes["determination"]["nom"] == "Subularion aquaticae"
    assert codes["corresp"]["EUNIS"]["cd_hab"] == 1672
    assert codes["corresp"]["EUNIS"]["src"] == "manuel"
    assert "nom" not in codes["corresp"]["EUNIS"], "le libellé ne revient pas"


def test_editer_le_texte_libre_preserve_les_correspondances():
    """L'autre chemin d'écriture : `encode_eval` reconstruit le bloc entier."""
    habitat = _habitat_avec_correspondances()
    ch.ecrire(habitat, ch.par_cle(ch.HABITAT, "technical_precision"), "Autre remarque.")
    codes = ef.decode_eval(habitat["technical_precision"])
    assert ef.strip_eval(habitat["technical_precision"]) == "Autre remarque."
    assert codes["determination"]["ancre"] == "CORINE_biotopes"
    assert codes["corresp"]["EUNIS"]["src"] == "manuel"


def test_les_cles_structurees_ne_sont_pas_des_champs_saisissables():
    """Ni colonne ni éditeur : elles n'ont pas de forme scalaire à afficher."""
    for cle in ("determination", "corresp"):
        assert ch.par_cle(ch.HABITAT, cle) is None


# ------------------------- correspondances modifiables en masse depuis le tableau
def _corresp(cle):
    return ch.par_cle(ch.HABITAT, cle)


def test_les_quatre_typologies_sont_des_champs():
    """Dérivés du référentiel : ajouter une typologie les fait apparaître seule."""
    cles = [c.cle for c in ch.CHAMPS if c.stockage == ch.CORRESP]
    assert cles == [cle for cle, _lib, _court in ref.TYPOLOGIES_CORRESPONDANCE]
    assert all(c.niveau == ch.HABITAT and c.masse for c in ch.CHAMPS
               if c.stockage == ch.CORRESP)


def test_lire_une_correspondance_rend_son_code():
    """Le code n'est plus stocké : il vient du catalogue, via le `cd_hab`."""
    connu = 9403  # Tapis de Nitella, 22.442 — présent au catalogue livré
    habitat = {"technical_precision": ef.encode_eval("", corresp={
        "EUNIS": {"cd_hab": connu}})}
    assert ch.lire(habitat, _corresp("EUNIS")) == "22.442"
    assert ch.lire(habitat, _corresp("CORINE_biotopes")) is None


def test_lire_une_correspondance_hors_catalogue_rend_le_cd_hab():
    """Mieux vaut le `cd_hab` nu qu'une case vide : la correspondance existe."""
    habitat = {"technical_precision": ef.encode_eval("", corresp={
        "EUNIS": {"cd_hab": 999999}})}
    assert ch.lire(habitat, _corresp("EUNIS")) == "999999"


def test_ecrire_une_correspondance_preserve_les_autres():
    """`merge_eval` remplace la clé `corresp` en bloc : les omettre les effacerait.

    C'est le piège de ce stockage — écrire l'EUNIS de trente lignes ne doit pas
    faire disparaître leur CORINE.
    """
    habitat = {"technical_precision": ef.encode_eval(
        "Relevé du 12 mai.", enjeu="fort",
        corresp={"EUNIS": {"cd_hab": 1, "src": "catalogue"}})}
    ch.ecrire(habitat, _corresp("CORINE_biotopes"),
              {"cd_hab": 9403, "code": "37.24", "nom": "Prairies à Agropyre"})
    codes = ef.decode_eval(habitat["technical_precision"])
    assert codes["corresp"]["EUNIS"]["cd_hab"] == 1
    assert codes["corresp"]["CORINE_biotopes"]["cd_hab"] == 9403
    assert codes["enjeu"] == "fort"
    assert ef.strip_eval(habitat["technical_precision"]) == "Relevé du 12 mai."


def test_une_correspondance_posee_par_le_tableau_est_arbitree():
    """Choisir soi-même une correspondance, c'est l'arbitrer : `src` le dit."""
    habitat = {}
    ch.ecrire(habitat, _corresp("EUNIS"),
              {"cd_hab": 1, "code": "E3.44", "nom": "Gazons inondés"})
    entree = ef.decode_eval(habitat["technical_precision"])["corresp"]["EUNIS"]
    assert entree["src"] == "manuel"


def test_vider_une_correspondance_la_retire():
    """Seul moyen d'enlever en masse une correspondance posée par erreur."""
    habitat = {"technical_precision": ef.encode_eval("", enjeu="fort", corresp={
        "EUNIS": {"cd_hab": 1, "code": "E3.44"},
        "CORINE_biotopes": {"cd_hab": 2, "code": "37.24"}})}
    ch.ecrire(habitat, _corresp("EUNIS"), None)
    codes = ef.decode_eval(habitat["technical_precision"])
    assert sorted(codes["corresp"]) == ["CORINE_biotopes"]
    assert codes["enjeu"] == "fort"


def test_retirer_la_derniere_correspondance_ne_laisse_pas_de_cle_vide():
    habitat = {"technical_precision": ef.encode_eval("", enjeu="fort", corresp={
        "EUNIS": {"cd_hab": 1, "code": "E3.44"}})}
    ch.ecrire(habitat, _corresp("EUNIS"), None)
    codes = ef.decode_eval(habitat["technical_precision"])
    assert "corresp" not in codes
    assert codes["enjeu"] == "fort"


def test_l_ecriture_ne_touche_que_le_porteur_du_bloc():
    """Contrepartie de `ecrire` : l'enregistrement ne réécrit que ces colonnes."""
    assert ch.colonnes_touchees(_corresp("EUNIS")) == {"technical_precision"}
