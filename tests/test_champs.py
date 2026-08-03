# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du registre de champs (module pur `champs`)."""
import champs as ch
import eval_fields as ef


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


def test_recouvrement_ecrit_dans_les_deux_stockages():
    champ = ch.par_cle(ch.HABITAT, "recouvrement")
    habitat = {}

    ch.ecrire(habitat, champ, 60)

    assert habitat["recovery_percentage"] == 60          # colonne native OccHab
    assert "recouvrement" in habitat["technical_precision"]  # et le bloc
    assert ch.lire(habitat, champ) == 60


def test_recouvrement_repli_sur_la_colonne_native():
    """Habitat venu du serveur : colonne renseignée, aucun bloc."""
    champ = ch.par_cle(ch.HABITAT, "recouvrement")
    assert ch.lire({"recovery_percentage": 42}, champ) == 42


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
    # DOUBLE : le bloc de l'habitat ET la colonne native.
    assert ch.colonnes_touchees(ch.par_cle(ch.HABITAT, "recouvrement")) == {
        "technical_precision", "recovery_percentage"}


def test_colonnes_touchees_couvre_tout_le_registre():
    """Aucun champ ne doit rendre un ensemble vide : il serait jamais enregistré."""
    for champ in ch.CHAMPS:
        assert ch.colonnes_touchees(champ), champ.cle
