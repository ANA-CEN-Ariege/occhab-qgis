# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests des champs métier ANA / N2000 (module pur `eval_fields`).

L'enjeu principal : les stations déjà synchronisées portent l'ANCIEN format
`clé=valeur | clé=valeur`. Le décodage doit continuer à les lire, et la première
réécriture ne doit rien perdre.
"""
import json

import eval_fields as ef
import referentiels as ref


# ------------------------------------------------------- référentiels
def test_niveaux_enjeu_du_plus_fort_au_plus_faible():
    assert [code for code, _ in ef.NIVEAUX_ENJEU] == [
        "tres_fort", "fort", "moyen", "faible", "aucun", "inconnu",
    ]


def test_etats_conservation_alignes_sur_le_cahier_des_charges():
    """Annexe 2, id_et_cons : 0 inconnu · 1 excellent · 2 bon · 3 moyen · 4 mauvais."""
    assert [code for code, _ in ef.ETATS_CONSERVATION] == [
        "inconnu", "excellent", "bon", "moyen", "mauvais",
    ]


def test_codes_herites_convertis():
    assert ef.normalize_enjeu("majeur") == "tres_fort"
    assert ef.normalize_etat("nd") == "inconnu"
    for code, _ in ef.NIVEAUX_ENJEU:
        assert ef.normalize_enjeu(code) == code
    for code, _ in ef.ETATS_CONSERVATION:
        assert ef.normalize_etat(code) == code


# ------------------------------------------------------- encodage JSON
def test_encode_produit_un_bloc_json():
    encoded = ef.encode_eval("Texte libre.", enjeu="fort", typicite="bonne")

    assert "Texte libre." in encoded
    raw = encoded.split(ef.EVAL_START)[1].split(ef.EVAL_END)[0].strip()
    assert json.loads(raw) == {"enjeu": "fort", "typicite": "bonne"}


def test_texte_libre_hostile_preserve():
    """Le motif qui cassait l'ancien format : pipes, crochets, retours à la ligne."""
    critere = "Présence de PEE | recouvrement > 30 % [voir annexe 2]\nsecond paragraphe"
    encoded = ef.encode_eval("", critere=critere, pee=["Reynoutria japonica"])

    assert ef.decode_eval(encoded)["critere"] == critere
    assert ef.decode_eval(encoded)["pee"] == ["Reynoutria japonica"]


def test_balises_saisies_par_l_utilisateur_neutralisees():
    """JSON échappe les guillemets, pas nos crochets.

    Une balise dans une remarque — ou collée avec un commentaire recopié depuis
    une autre station via l'interface web — couperait le bloc au mauvais endroit
    et ferait perdre les valeurs à la relecture.
    """
    piege = "Voir station voisine [/ANA-EVAL] et son [ANA-EVAL] bloc"
    encoded = ef.encode_eval(piege, enjeu="fort", remarque=piege)

    assert encoded.count(ef.EVAL_START) == 1
    assert encoded.count(ef.EVAL_END) == 1
    relu = ef.decode_eval(encoded)
    assert relu["enjeu"] == "fort"          # la valeur survit
    assert "ANA-EVAL" not in relu["remarque"]


def test_commentaire_copie_colle_avec_son_bloc():
    """Cas réel : un commentaire entier recopié d'une station à l'autre."""
    source = ef.encode_eval("Note de terrain.", enjeu="fort", typicite="bonne")

    # Collé tel quel dans une autre station, puis réenregistré avec ses valeurs.
    recopie = ef.encode_eval(source, enjeu="faible")

    assert recopie.count(ef.EVAL_START) == 1
    assert ef.decode_eval(recopie) == {"enjeu": "faible"}
    assert ef.strip_eval(recopie) == "Note de terrain."


def test_bloc_remplace_jamais_duplique():
    once = ef.encode_eval("Note.", enjeu="fort")
    twice = ef.encode_eval(once, enjeu="faible")

    assert twice.count(ef.EVAL_START) == 1
    assert ef.decode_eval(twice)["enjeu"] == "faible"
    assert ef.strip_eval(twice) == "Note."


def test_encodage_stable_entre_deux_ecritures():
    """Deux enregistrements d'une même saisie doivent donner le MÊME texte.

    Sinon l'empreinte serveur change à chaque synchro et un conflit est détecté
    alors que rien n'a bougé.
    """
    a = ef.encode_eval("", enjeu="fort", typicite="bonne", dynamique="stable")
    b = ef.encode_eval("", dynamique="stable", enjeu="fort", typicite="bonne")
    assert a == b


def test_valeurs_hors_referentiel_non_ecrites():
    assert "enjeu" not in ef.decode_eval(ef.encode_eval("", enjeu="n_importe_quoi"))
    assert "typicite" not in ef.decode_eval(ef.encode_eval("", typicite="excellente"))
    assert ef.encode_eval("", cle_inventee="valeur") == ""


def test_pee_limite_a_trois_taxons():
    encoded = ef.encode_eval("", pee=["Reynoutria japonica", "Buddleja davidii",
                                      "Ailanthus altissima", "Robinia pseudoacacia"])
    assert len(ef.decode_eval(encoded)["pee"]) == 3


def test_sans_valeur_utile_pas_de_bloc():
    assert ef.encode_eval("Juste du texte.") == "Juste du texte."
    assert ef.encode_eval("") == ""


# ------------------------------------------- lecture de l'ancien format
def test_ancien_format_relu():
    ancien = ("Texte de terrain.\n\n[ANA-EVAL] enjeu=fort | etat_conservation=bon"
              " | recouvrement=45 | zone_humide=true [/ANA-EVAL]")

    codes = ef.decode_eval(ancien)

    assert codes["enjeu"] == "fort"
    assert codes["etat_conservation"] == "bon"
    assert codes["recouvrement"] == 45
    assert codes["zone_humide"] == "oui"
    assert ef.strip_eval(ancien) == "Texte de terrain."


def test_ancien_format_codes_herites_convertis_a_la_relecture():
    """« majeur » et « nd » ne sont plus des codes valides : sans conversion, la
    relecture les perdrait et la réécriture les effacerait."""
    ancien = "[ANA-EVAL] enjeu=majeur | etat_conservation=nd [/ANA-EVAL]"

    codes = ef.decode_eval(ancien)

    assert codes["enjeu"] == "tres_fort"
    assert codes["etat_conservation"] == "inconnu"


def test_migration_ancien_vers_json_sans_perte():
    ancien = ("Relevé du 12 juin.\n\n[ANA-EVAL] enjeu=majeur | etat_conservation=bon"
              " | recouvrement=60 | zone_humide=true [/ANA-EVAL]")

    codes = ef.decode_eval(ancien)
    reecrit = ef.encode_eval(ef.strip_eval(ancien), **codes)

    assert "Relevé du 12 juin." in reecrit
    relu = ef.decode_eval(reecrit)
    assert relu == {"enjeu": "tres_fort", "etat_conservation": "bon",
                    "recouvrement": 60, "zone_humide": "oui"}
    # …et le bloc est désormais du JSON.
    assert reecrit.split(ef.EVAL_START)[1].split(ef.EVAL_END)[0].strip().startswith("{")


def test_bloc_illisible_ignore_sans_planter():
    """Bloc trituré à la main dans l'interface web GeoNature."""
    for raw in ("{ceci n'est pas du json", "", "   ", "[]", "null"):
        texte = "Note.\n\n%s %s %s" % (ef.EVAL_START, raw, ef.EVAL_END)
        assert ef.decode_eval(texte) == {}
        assert ef.strip_eval(texte) == "Note."


def test_aucun_bloc():
    assert ef.decode_eval("Simple commentaire.") == {}
    assert ef.decode_eval("") == {}
    assert ef.decode_eval(None) == {}


# ------------------------------------------------------- recouvrement
def test_recouvrement_et_classe_d_abondance():
    assert ef.decode_eval(ef.encode_eval("", recouvrement=45))["recouvrement"] == 45
    assert ef.decode_eval(ef.encode_eval("", recouvrement=12.5))["recouvrement"] == 12.5
    for value in (0, -1, 101, None, "abc", True):
        assert "recouvrement" not in ef.decode_eval(ef.encode_eval("", recouvrement=value))

    assert ef.cover_class(3) == 1
    assert ef.cover_class(10) == 2
    assert ef.cover_class(30) == 3
    assert ef.cover_class(75) == 4
    assert ef.cover_class(90) == 5
    assert ef.cover_class(None) is None


# ------------------------------------------- correspondance cahier des charges
def test_chaque_code_a_son_equivalent_numerique_cdc():
    """Le rendu réglementaire attend des entiers : aucun code ne doit manquer."""
    for items, mapping in (
        (ref.ETATS_CONSERVATION, ref.CDC_ETAT_CONSERVATION),
        (ref.DYNAMIQUES, ref.CDC_DYNAMIQUE),
        (ref.RESTAURATIONS, ref.CDC_RESTAURATION),
        (ref.TYPICITES, ref.CDC_TYPICITE),
        (ref.UNITES_VEGETALES, ref.CDC_UNITE_VEGETALE),
        (ref.NATURES_OBSERVATION, ref.CDC_NATURE_OBSERVATION),
    ):
        assert ref.codes(items) == set(mapping), mapping


def test_valeurs_numeriques_conformes_a_l_annexe_2():
    """Transcription vérifiable ligne à ligne face au cahier des charges.

    Noter que `id_uv` (unité végétale) est le seul à démarrer à 1 : l'annexe ne
    prévoit pas de valeur « 0 inconnu » pour ce champ.
    """
    assert ref.CDC_ETAT_CONSERVATION == {
        "inconnu": 0, "excellent": 1, "bon": 2, "moyen": 3, "mauvais": 4}
    assert ref.CDC_DYNAMIQUE == {
        "inconnue": 0, "stable": 1, "progressive_lente": 2, "regressive_lente": 3,
        "progressive_rapide": 4, "regressive_rapide": 5}
    assert ref.CDC_RESTAURATION == {
        "inconnu": 0, "difficile": 1, "impossible": 2, "possible": 3,
        "possible_avec_efforts": 4}
    assert ref.CDC_TYPICITE == {"inconnue": 0, "bonne": 1, "moyenne": 2, "mauvaise": 3}
    assert ref.CDC_UNITE_VEGETALE == {
        "non_complexe": 1, "mosaique_non_definie": 2, "mosaique_temporelle": 3,
        "mosaique_topographique": 4, "mixte": 5}
    assert ref.CDC_NATURE_OBSERVATION == {
        "inconnu": 0, "directe_avec_releve": 1, "directe_sans_releve": 2,
        "a_distance": 3, "photo_interpretation": 4, "autre": 5}


# ------------------------------------------------- écriture partielle du bloc
def test_merge_eval_conserve_les_autres_cles():
    """Changer le seul statut ne doit pas effacer le travail de saisie."""
    complet = ef.encode_eval("Note.", enjeu="fort", typicite="bonne", recouvrement=60)

    fusionne = ef.merge_eval(complet, statut="valide")

    assert ef.decode_eval(fusionne) == {
        "enjeu": "fort", "typicite": "bonne", "recouvrement": 60, "statut": "valide",
    }
    assert ef.strip_eval(fusionne) == "Note."


def test_merge_eval_sur_texte_sans_bloc():
    fusionne = ef.merge_eval("Commentaire simple.", statut="brouillon")
    assert ef.decode_eval(fusionne) == {"statut": "brouillon"}
    assert ef.strip_eval(fusionne) == "Commentaire simple."


def test_merge_eval_none_supprime_la_cle():
    complet = ef.encode_eval("", enjeu="fort", statut="valide")
    assert ef.decode_eval(ef.merge_eval(complet, statut=None)) == {"enjeu": "fort"}


def test_merge_eval_sur_ancien_format():
    ancien = "[ANA-EVAL] enjeu=majeur | recouvrement=30 [/ANA-EVAL]"
    fusionne = ef.merge_eval(ancien, statut="valide")
    assert ef.decode_eval(fusionne) == {
        "enjeu": "tres_fort", "recouvrement": 30, "statut": "valide",
    }


def test_statut_validation_est_un_code_ferme():
    assert ef.decode_eval(ef.encode_eval("", statut="valide"))["statut"] == "valide"
    assert "statut" not in ef.decode_eval(ef.encode_eval("", statut="en_cours"))


# --- Zone humide : trois états, et non plus une case à cocher ----------------
def test_zone_humide_a_verifier():
    """Le troisième état, celui qui manquait : ni oui, ni non."""
    comment = ef.encode_eval("Bas-fond sec en août.", zone_humide="a_verifier")
    assert ef.decode_eval(comment)["zone_humide"] == "a_verifier"


def test_zone_humide_non_est_une_information():
    """« Non » se stocke, alors qu'une case décochée ne disait rien."""
    assert ef.decode_eval(ef.encode_eval("", zone_humide="non"))["zone_humide"] == "non"


def test_zone_humide_ancien_booleen():
    """Les stations déjà saisies portent True / False, pas un code."""
    assert ef.decode_eval(ef.encode_eval("", zone_humide=True))["zone_humide"] == "oui"
    # `False` ne voulait dire que « case décochée » : rien à en conclure.
    assert "zone_humide" not in ef.decode_eval(ef.encode_eval("", zone_humide=False))


def test_zone_humide_ancien_texte():
    """Ancien format textuel du bloc : `zone_humide=true`."""
    comment = "[ANA-EVAL] zone_humide=true [/ANA-EVAL]"
    assert ef.decode_eval(comment)["zone_humide"] == "oui"


def test_zone_humide_code_inconnu_ecarte():
    assert "zone_humide" not in ef.decode_eval(
        ef.encode_eval("", zone_humide="peut-etre-bien")
    )


def test_zone_humide_dans_le_referentiel():
    assert ref.codes(ref.ZONES_HUMIDES) == {"oui", "non", "a_verifier"}
    # L'ordre d'AFFICHAGE compte : « À vérifier » se choisit après avoir hésité
    # entre les deux autres, pas avant.
    assert [code for code, _ in ref.ZONES_HUMIDES] == ["oui", "non", "a_verifier"]


# ------------------------- détermination hors HABREF et correspondances
def test_correspondance_arbitree_survit_a_l_aller_retour():
    """Le cœur de la fonctionnalité : ce que le botaniste tranche est conservé."""
    texte = ef.encode_eval(
        "", corresp={"EUNIS": {"cd_hab": 5678, "code": "F9.12", "src": "manuel"}}
    )
    assert ef.decode_eval(texte)["corresp"] == {
        "EUNIS": {"cd_hab": 5678, "code": "F9.12", "src": "manuel"}
    }


def test_determination_hors_habref_dit_son_ancre():
    texte = ef.encode_eval(
        "", determination={"nom": "Salicion pyrenaicae", "ancre": "CORINE_biotopes"}
    )
    assert ef.decode_eval(texte)["determination"] == {
        "nom": "Salicion pyrenaicae", "ancre": "CORINE_biotopes",
    }


def test_determination_sans_nom_ecartee():
    """Un `cd_hab` d'ancre sans nom d'alliance ne dit rien de plus qu'un cd_hab."""
    assert ef.decode_eval(ef.encode_eval("", determination={"ancre": "EUNIS"})) == {}


def test_ancre_hors_referentiel_ecartee_mais_nom_garde():
    codes = ef.decode_eval(
        ef.encode_eval("", determination={"nom": "Salicion pyrenaicae",
                                          "ancre": "TYPOLOGIE_INVENTEE"})
    )
    assert codes["determination"] == {"nom": "Salicion pyrenaicae"}


def test_typologie_inconnue_ecartee_des_correspondances():
    codes = ef.decode_eval(ef.encode_eval("", corresp={
        "EUNIS": {"cd_hab": 5678}, "PIFOMETRE": {"cd_hab": 1},
    }))
    assert set(codes["corresp"]) == {"EUNIS"}


def test_correspondance_sans_cd_hab_ecartee():
    """C'est le cd_hab qui fait la correspondance : un code seul ne se raccorde à rien."""
    assert ef.decode_eval(
        ef.encode_eval("", corresp={"EUNIS": {"code": "F9.12"}})
    ) == {}


def test_source_hors_referentiel_ecartee_sans_inventer():
    """Écrire « manuel » d'office ferait croire à une vérification jamais faite."""
    codes = ef.decode_eval(ef.encode_eval("", corresp={
        "EUNIS": {"cd_hab": 5678, "src": "au_pif"},
    }))
    assert codes["corresp"]["EUNIS"] == {"cd_hab": 5678}


def test_bloc_reste_lisible_avec_le_texte_humain():
    texte = ef.encode_eval(
        "Relevé du 12 mai.", enjeu="fort",
        corresp={"EUNIS": {"cd_hab": 5678, "src": "catalogue"}},
    )
    assert ef.strip_eval(texte) == "Relevé du 12 mai."
    assert ef.decode_eval(texte)["enjeu"] == "fort"


def test_merge_efface_les_correspondances_sans_toucher_au_reste():
    """Ce dont dépend la reprise de l'habitat précédent (cf. duplicate)."""
    texte = ef.encode_eval("", enjeu="fort", determination={"nom": "Salicion"},
                           corresp={"EUNIS": {"cd_hab": 5678}})
    apres = ef.decode_eval(ef.merge_eval(texte, determination=None, corresp=None))
    assert apres == {"enjeu": "fort"}
