# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests des couleurs d'habitats : une par habitat, dans le ton du milieu."""
import habitat_style as hs


def _f(id_station, nom=None, eunis=None, recouvrement=None, cd_hab=None,
       habitat=None, code_habref=None):
    return {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "id_station": id_station,
            "nom_cite": nom,
            "habitat": habitat,
            "code_habref": code_habref,
            "cd_hab": cd_hab,
            "habitat_code_eunis": eunis,
            "recouvrement_pct": recouvrement,
        },
    }


# ------------------------------------------------------------------ classement
def test_classe_depuis_la_premiere_lettre_eunis():
    assert hs.classe_eunis("G1.6") == "G"
    assert hs.classe_eunis("e2.2") == "E"  # casse indifférente
    assert hs.classe_eunis("F3.16 ; F3.1A") == "F"  # valeurs multiples de la vue


def test_classe_absente_ou_hors_referentiel():
    for valeur in (None, "", "   ", 42, "31.88", "Z9"):
        assert hs.classe_eunis(valeur) is None, valeur


def test_classe_corine_separe_landes_et_prairies():
    """Le groupe 3 de CORINE réunit les deux : seul le 2e chiffre les distingue."""
    assert hs.classe_corine("31.88") == "F"   # landes et fruticées
    assert hs.classe_corine("32.4") == "F"    # matorrals
    assert hs.classe_corine("34.32") == "E"   # pelouses calcicoles
    assert hs.classe_corine("38.22") == "E"   # prairies de fauche
    assert hs.classe_corine("3") == "E"       # sans 2e chiffre : le cas le plus courant


def test_classe_corine_grands_groupes():
    for code, attendu in (("22.1", "C"), ("41.13", "G"), ("51.1", "D"),
                          ("61.3", "H"), ("82.1", "I"), ("15.1", "B")):
        assert hs.classe_corine(code) == attendu, code


def test_classe_n2000_depuis_le_premier_chiffre():
    for code, attendu in (("1150", "B"), ("2130", "B"), ("3150", "C"),
                          ("4030", "F"), ("5110", "F"), ("6510", "E"),
                          ("7110", "D"), ("8220", "H"), ("9120", "G")):
        assert hs.classe_n2000(code) == attendu, code
    # Les Cahiers d'habitats déclinent le même code : « 6510-1 » reste une prairie.
    assert hs.classe_n2000("6510-1") == "E"


def test_classe_codes_illisibles():
    for valeur in (None, "", "   ", 42, "G1.6"):
        assert hs.classe_corine(valeur) is None, valeur
        assert hs.classe_n2000(valeur) is None, valeur


def test_cascade_eunis_puis_corine_puis_n2000():
    """EUNIS l'emporte quand il est là ; sinon on descend la cascade."""
    assert hs.classe_habitat({"habitat_code_eunis": "G1.6",
                              "habitat_code_corine": "38.2"}) == ("G", hs.SOURCE_EUNIS)
    assert hs.classe_habitat({"habitat_code_corine": "38.2"}) == ("E", hs.SOURCE_CORINE)
    assert hs.classe_habitat({"habitat_code_n2000": "9120"}) == ("G", hs.SOURCE_N2000)
    assert hs.classe_habitat({}) == (hs.CLASSE_INCONNUE, None)


def test_poids_selon_le_rang_de_correspondance():
    """Une correspondance directe pèse plus qu'un détour par une autre typologie."""
    assert hs.poids_rang(0) > hs.poids_rang(11)      # déjà dans la typologie
    assert hs.poids_rang(10) > hs.poids_rang(11)     # directe > héritée
    assert hs.poids_rang(11) > hs.poids_rang(21)     # héritée > deux sauts
    assert hs.poids_rang(None) == hs.poids_rang(10)  # rang inconnu : pas pénalisé


def test_le_rang_ecarte_les_correspondances_lointaines():
    """Cas réel : des végétations de bord d'étang classées en « côtes et dunes ».

    Les correspondances à deux sauts rattachent volontiers une magnocariçaie à
    une dépression dunaire — les deux sont humides. Sans pondération par le
    rang, ce détour pesait autant qu'une correspondance directe.
    """
    caricion = {
        "habitat_code_eunis": "B1.81", "habitat_eunis_rang": 21,   # deux sauts
        "habitat_code_corine": "53.21", "habitat_corine_rang": 10,  # directe
    }
    classe, source = hs.classe_habitat(caricion)

    assert classe == "D", "une magnocariçaie n'est pas une dune"
    assert source == hs.SOURCE_CORINE


def test_un_habitat_vraiment_dunaire_reste_dunaire():
    """Le garde-fou ne doit pas empêcher un littoral légitime de sortir."""
    dune = {
        "habitat_code_eunis": "B1.82", "habitat_eunis_rang": 10,
        "habitat_code_corine": "16.32", "habitat_corine_rang": 10,
    }
    assert hs.classe_habitat(dune)[0] == "B"


def test_rangs_absents_ancienne_vue():
    """Une vue sans colonnes de rang doit continuer de fonctionner."""
    assert hs.classe_habitat({"habitat_code_eunis": "G1.6 ; G1.7"})[0] == "G"


def test_cascade_sauve_une_carto_pvf1():
    """Cas réel : en PVF1, HABREF ne mène qu'aux habitats d'intérêt communautaire.

    Sans cascade, toute une cartographie du Prodrome tombait en « non
    déterminé » — la carte entière en gris.
    """
    pvf1 = {"typologie_habitat": "Prodrome_des_végétations_de_France_(PVF1)",
            "code_habref": "3.0.1.0.5", "habitat_code_eunis": None,
            "habitat_code_corine": None, "habitat_code_cahiers": "6510-1"}
    classe, source = hs.classe_habitat(pvf1)

    assert classe == "E"
    assert source == hs.SOURCE_N2000


def test_source_de_classement_est_conservee():
    features = [_f(1, "Prairie", None, 100, cd_hab=1)]
    features[0]["properties"]["habitat_code_corine"] = "38.22"
    hs.enrichir(features)

    assert features[0]["properties"][hs.CHAMP_SOURCE] == hs.SOURCE_CORINE


# -------------------------------------------------------------------- couleurs
def test_eclaircir_garde_la_teinte():
    """Éclaircir en RVB délaverait la saturation : un vert virerait au gris."""
    import colorsys

    base, clair = "#1b5e20", hs.eclaircir("#1b5e20", 0.25)
    teinte = lambda c: colorsys.rgb_to_hls(*hs._hex_vers_rgb(c))[0]  # noqa: E731
    assert abs(teinte(base) - teinte(clair)) < 0.01
    assert clair != base


def test_eclaircir_plafonne():
    """Sans plafond, une nuance de plus finirait blanche et illisible."""
    assert hs.eclaircir("#7cb342", 5.0) == hs.eclaircir("#7cb342", 10.0)
    assert hs.eclaircir("#7cb342", 5.0) != "#ffffff"


def _ecart(a, b):
    """Écart RVB moyen entre deux couleurs, sur 255. Sous 10, c'est indiscernable."""
    return sum(abs(x - y) for x, y in zip(hs._hex_vers_rgb(a), hs._hex_vers_rgb(b))) * 255 / 3


def test_gamme_nuances_toutes_distinctes():
    for classe in hs.CLASSES_EUNIS:
        for nombre in (2, 3, 4, 6, 8, 12):
            couleurs = hs.gamme(classe, nombre)
            assert len(couleurs) == nombre
            assert len(set(couleurs)) == nombre, (classe, nombre, couleurs)


def test_gamme_nuances_reellement_separees():
    """Deux habitats d'un même milieu doivent se distinguer à l'œil.

    Le seuil (10/255) est le point sous lequel deux aplats deviennent
    indiscernables une fois imprimés. Il n'est pas plus haut par choix : élargir
    la gamme d'un milieu séparerait mieux SES habitats, mais rapprocherait une
    prairie très sombre d'un vert forestier. La confusion entre milieux coûte
    plus cher — la légende, elle, groupe déjà les habitats par milieu.
    """
    for classe in hs.CLASSES_EUNIS:
        for nombre in (2, 3, 4, 5, 6):
            couleurs = hs.gamme(classe, nombre)
            pires = min(_ecart(couleurs[i], couleurs[j])
                        for i in range(nombre) for j in range(i + 1, nombre))
            assert pires >= 10, (classe, nombre, pires, couleurs)


def test_gamme_change_de_saturation_au_dela_de_six():
    """Au-delà de six nuances, la luminosité seule ne suffit plus.

    Sans second axe, les paliers se resserrent jusqu'à l'indiscernable ; on
    ouvre donc un palier de saturation, sans quitter le ton.
    """
    import colorsys

    saturations = {
        round(colorsys.rgb_to_hls(*hs._hex_vers_rgb(c))[2], 3)
        for c in hs.gamme("G", 12)
    }
    assert len(saturations) > 1


def test_gamme_habitat_unique():
    assert hs.gamme("G", 1) == [hs.couleur_classe("G")]
    assert hs.gamme("G", 0) == [hs.couleur_classe("G")]


def test_gammes_de_milieux_differents_ne_se_confondent_pas():
    forets = set(hs.gamme("G", 5))
    prairies = set(hs.gamme("E", 5))
    assert not (forets & prairies)


# --------------------------------------------------------------------- entités
def test_cle_habitat_prefere_le_cd_hab():
    """Deux stations nommant différemment le MÊME habitat : une seule couleur."""
    a = _f(1, "Hêtraie", "G1.6", cd_hab=5130)
    b = _f(2, "Hêtraie à houx", "G1.6", cd_hab=5130)
    assert hs.cle_habitat(a) == hs.cle_habitat(b)


def test_cle_habitat_repli_sur_le_nom():
    assert hs.cle_habitat(_f(1, "Hêtraie")) == "nom:Hêtraie"
    assert hs.cle_habitat(_f(1)) is None


def test_dominant_est_le_plus_couvrant():
    features = [
        _f(1, "Lande", "F3.16", 25, cd_hab=2),
        _f(1, "Hêtraie", "G1.6", 60, cd_hab=1),
        _f(1, "Prairie", "E2.2", 15, cd_hab=3),
    ]
    hs.enrichir(features)

    dominants = [f for f in features if f["properties"][hs.CHAMP_DOMINANT]]
    assert len(dominants) == 1, "un seul aplat par station, sinon ils s'empilent"
    assert dominants[0]["properties"]["nom_cite"] == "Hêtraie"
    assert len(features) == 3, "les autres restent dans la couche"


def test_mosaique_signalee_et_composition_ordonnee():
    features = [_f(1, "Lande", "F3.16", 25), _f(1, "Hêtraie", "G1.6", 60)]
    hs.enrichir(features)

    assert all(f["properties"][hs.CHAMP_MOSAIQUE] == 1 for f in features)
    assert features[0]["properties"][hs.CHAMP_COMPOSITION] == "Hêtraie 60 % ; Lande 25 %"


def test_station_a_un_seul_habitat_n_est_pas_une_mosaique():
    features = [_f(2, "Hêtraie", "G1.6", 100)]
    hs.enrichir(features)

    props = features[0]["properties"]
    assert props[hs.CHAMP_MOSAIQUE] == 0
    assert props[hs.CHAMP_DOMINANT] == 1


def test_station_sans_habitat():
    """Une station sans habitat reste dessinée, en classe « non déterminé »."""
    features = [_f(3)]
    hs.enrichir(features)

    props = features[0]["properties"]
    assert props[hs.CHAMP_CLASSE] == hs.CLASSE_INCONNUE
    assert props[hs.CHAMP_DOMINANT] == 1
    assert props[hs.CHAMP_COMPOSITION] is None


def test_recouvrements_absents_ou_illisibles():
    features = [_f(4, "A", "G1.6"), _f(4, "B", "E2.2", "texte")]
    hs.enrichir(features)

    dominants = [f["properties"]["nom_cite"]
                 for f in features if f["properties"][hs.CHAMP_DOMINANT]]
    assert dominants == ["A"], "à égalité, l'ordre du serveur tranche (stable)"


# --------------------------------------------------------------------- palette
def test_palette_une_couleur_par_habitat_dans_le_ton_du_milieu():
    features = [
        _f(1, "Hêtraie", "G1.6", 100, cd_hab=1, habitat="Hêtraie", code_habref="41.1"),
        _f(2, "Chênaie", "G1.A", 100, cd_hab=2, habitat="Chênaie", code_habref="41.2"),
        _f(3, "Pineraie", "G3.4", 100, cd_hab=3, habitat="Pineraie", code_habref="42.5"),
        _f(4, "Prairie", "E2.2", 100, cd_hab=4, habitat="Prairie", code_habref="38.2"),
    ]
    hs.enrichir(features)
    palette = hs.palette(features)

    milieux = [(classe, len(habitats)) for classe, _lib, habitats in palette]
    assert milieux == [("E", 1), ("G", 3)], "ordre EUNIS, 3 forêts et 1 prairie"

    forets = dict((cle, couleur) for cle, _lib, couleur in palette[1][2])
    assert len(set(forets.values())) == 3, "trois nuances distinctes"
    # Toutes dans le ton : même teinte que la couleur de référence du milieu.
    import colorsys
    teinte_ref = colorsys.rgb_to_hls(*hs._hex_vers_rgb(hs.couleur_classe("G")))[0]
    for couleur in forets.values():
        assert abs(colorsys.rgb_to_hls(*hs._hex_vers_rgb(couleur))[0] - teinte_ref) < 0.01


def test_palette_un_meme_habitat_une_seule_entree():
    """Le même habitat sur dix stations : une entrée de légende, une couleur."""
    features = [_f(i, "Hêtraie", "G1.6", 100, cd_hab=5130) for i in range(1, 11)]
    hs.enrichir(features)
    palette = hs.palette(features)

    assert len(palette) == 1
    assert len(palette[0][2]) == 1


def test_palette_couvre_aussi_les_habitats_secondaires():
    """Une lande sous une hêtraie EST dessinée (en hachures) : elle a sa couleur.

    C'est ce qui permet de représenter plusieurs habitats sur un même polygone
    au lieu de n'afficher que le dominant.
    """
    features = [
        _f(1, "Hêtraie", "G1.6", 60, cd_hab=1),
        _f(1, "Lande", "F3.16", 40, cd_hab=2),
    ]
    hs.enrichir(features)

    assert [classe for classe, _l, _h in hs.palette(features)] == ["F", "G"]


def test_bandes_proportionnelles_au_recouvrement():
    """Chaque habitat occupe sa part du polygone, bout à bout et sans trou."""
    features = [
        _f(1, "Lande", "F3.16", 25, cd_hab=2),
        _f(1, "Hêtraie", "G1.6", 60, cd_hab=1),
        _f(1, "Prairie", "E2.2", 15, cd_hab=3),
    ]
    hs.enrichir(features)

    bornes = {f["properties"]["nom_cite"]:
              (f["properties"][hs.CHAMP_DEBUT], f["properties"][hs.CHAMP_FIN])
              for f in features}
    assert bornes == {"Hêtraie": (0.0, 60.0), "Lande": (60.0, 85.0),
                      "Prairie": (85.0, 100.0)}


def test_bandes_renormalisees_si_le_total_n_est_pas_cent():
    """Un polygone dont les recouvrements ne totalisent pas 100 reste rempli."""
    features = [_f(1, "A", "G1.6", 30, cd_hab=1), _f(1, "B", "G1.7", 30, cd_hab=2)]
    hs.enrichir(features)

    assert features[0]["properties"][hs.CHAMP_DEBUT] == 0.0
    assert features[-1]["properties"][hs.CHAMP_FIN] == 100.0


def test_bandes_sans_recouvrement_renseigne():
    """Sans recouvrement, des parts égales : mieux qu'un habitat réduit à rien."""
    features = [_f(1, "A", "G1.6", None, cd_hab=1), _f(1, "B", "G1.7", None, cd_hab=2)]
    hs.enrichir(features)

    bandes = [(f["properties"][hs.CHAMP_DEBUT], f["properties"][hs.CHAMP_FIN])
              for f in features]
    assert bandes == [(0.0, 50.0), (50.0, 100.0)]


def test_bande_unique_couvre_tout_le_polygone():
    features = [_f(2, "Seul", "G1.6", 40, cd_hab=1)]
    hs.enrichir(features)

    props = features[0]["properties"]
    assert (props[hs.CHAMP_DEBUT], props[hs.CHAMP_FIN]) == (0.0, 100.0)


def test_rang_et_couleur_par_entite():
    """Le rang ordonne les hachures ; la couleur est posée sur chaque entité."""
    features = [
        _f(1, "Prairie", "E2.2", 10, cd_hab=3),
        _f(1, "Hêtraie", "G1.6", 60, cd_hab=1),
        _f(1, "Lande", "F3.16", 25, cd_hab=2),
    ]
    hs.enrichir(features)
    hs.palette(features)

    rangs = {f["properties"]["nom_cite"]: f["properties"][hs.CHAMP_RANG] for f in features}
    assert rangs == {"Hêtraie": 0, "Lande": 1, "Prairie": 2}
    couleurs = {f["properties"][hs.CHAMP_COULEUR] for f in features}
    assert len(couleurs) == 3, "chaque habitat de la mosaïque a sa propre couleur"


def test_palette_ordre_stable_par_code():
    """Deux chargements des mêmes données doivent donner les mêmes couleurs."""
    def construire():
        features = [
            _f(2, "B", "G3.4", 100, cd_hab=2), _f(1, "A", "G1.6", 100, cd_hab=1),
        ]
        hs.enrichir(features)
        return hs.palette(features)

    assert construire() == construire()
    # …et la nuance suit l'ordre du code EUNIS, pas l'ordre d'arrivée.
    habitats = construire()[0][2]
    assert [libelle for _c, libelle, _coul in habitats] == ["A (G1.6)", "B (G3.4)"]


def test_palette_inconnue_en_dernier():
    features = [
        _f(1, "Sans code", None, 100, cd_hab=9),
        _f(2, "Hêtraie", "G1.6", 100, cd_hab=1),
    ]
    hs.enrichir(features)

    assert [classe for classe, _l, _h in hs.palette(features)] == ["G", hs.CLASSE_INCONNUE]


def test_entrees_vides_ou_mal_formees():
    assert hs.enrichir(None) == []
    assert hs.enrichir([None, "texte", 3]) == []
    assert hs.palette([]) == []
    assert hs.palette(None) == []
