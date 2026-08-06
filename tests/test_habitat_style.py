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


def test_racine_habref_fait_autorite():
    """Quand la vue donne la racine HABREF, elle prime sur nos tables maison."""
    props = {"grand_type_code": "G",
             "grand_type_nom": "Woodland, forest and other wooded land",
             "habitat_code_corine": "38.2"}   # nos tables diraient « prairies »
    assert hs.classe_habitat(props) == ("G", hs.SOURCE_HABREF)


def test_racine_hors_eunis_est_ignoree():
    """Une racine d'une autre typologie n'a pas de couleur : on revient au vote.

    Sans ce garde-fou, un grand type sans couleur attribuée sortirait en gris.
    """
    props = {"grand_type_code": "4", "habitat_code_corine": "41.1"}
    classe, source = hs.classe_habitat(props)
    assert (classe, source) == ("G", hs.SOURCE_CORINE)


def test_libelle_habref_remplace_le_notre():
    features = [_f(1, "Hêtraie", None, 100, cd_hab=1)]
    features[0]["properties"].update(
        grand_type_code="G", grand_type_nom="Forêts (HABREF)")
    hs.enrichir(features)

    assert features[0]["properties"][hs.CHAMP_LIBELLE] == "Forêts (HABREF)"


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
def test_cle_habitat_regroupe_les_cd_hab_d_un_meme_syntaxon():
    """HABREF porte plusieurs cd_hab pour une même végétation.

    Cas réel : « Tetragonolobo maritimi-Mesobromenion erecti (26.0.2.0.3.3) »
    sortait DEUX fois dans la légende, libellé et code identiques, en deux
    couleurs — parce que la clé était le cd_hab. Le nom HABREF les regroupe.
    """
    a = _f(1, None, "E1.2", cd_hab=101, habitat="Tetragonolobo-Mesobromenion")
    b = _f(2, None, "E1.2", cd_hab=202, habitat="Tetragonolobo-Mesobromenion")
    assert hs.cle_habitat(a) == hs.cle_habitat(b)

    # Une entrée sans code se regroupe avec son homonyme codé.
    code = _f(3, None, "C3.2", cd_hab=303, habitat="Phragmition communis",
              code_habref="51.0.1.0.1")
    sans = _f(4, None, "C3.2", cd_hab=404, habitat="Phragmition communis")
    assert hs.cle_habitat(code) == hs.cle_habitat(sans)


def test_cle_habitat_insensible_a_la_casse_et_aux_espaces():
    assert hs.cle_habitat(_f(1, habitat="Hêtraie  acidiphile")) == \
           hs.cle_habitat(_f(2, habitat="hêtraie acidiphile"))


def test_cle_habitat_replis_successifs():
    """Sans nom HABREF : le nom cité, puis le cd_hab, puis rien."""
    assert hs.cle_habitat(_f(1, "Hêtraie")) == "nom:hêtraie"
    assert hs.cle_habitat(_f(1, cd_hab=5130)) == "cd:5130"
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


def test_parts_cumulees_du_plus_au_moins_couvrant():
    """Chaque habitat occupe sa bande, bout à bout et sans trou.

    Le dominant vient en premier, donc en bas du polygone.
    """
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


def test_parts_renormalisees_si_le_total_n_est_pas_cent():
    """Recouvrements ne totalisant pas 100 : le polygone reste entièrement rempli."""
    features = [_f(1, "A", "G1.6", 30, cd_hab=1), _f(1, "B", "G1.7", 30, cd_hab=2)]
    hs.enrichir(features)

    parts = [(f["properties"][hs.CHAMP_DEBUT], f["properties"][hs.CHAMP_FIN])
             for f in features]
    assert min(d for d, _f in parts) == 0.0
    assert max(f for _d, f in parts) == 100.0


def test_parts_sans_recouvrement_renseigne():
    """Sans recouvrement, des parts égales : mieux qu'un habitat réduit à rien."""
    features = [_f(1, "A", "G1.6", None, cd_hab=1), _f(1, "B", "G1.7", None, cd_hab=2)]
    hs.enrichir(features)

    parts = sorted((f["properties"][hs.CHAMP_DEBUT], f["properties"][hs.CHAMP_FIN])
                   for f in features)
    assert parts == [(0.0, 50.0), (50.0, 100.0)]


def test_habitat_unique_couvre_tout_le_polygone():
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


# --- Le piège de l'annexe I : des bas-marais rangés dans les dunes -----------
# Cas relevé sur une carto ariégeoise. HABREF relie plusieurs alliances de
# prairies humides et de cariçaies à l'habitat 2190 « Dépressions humides
# intradunales », parce qu'elles décrivent AUSSI la végétation des pannes
# dunaires. Prises au mot, elles peuplaient un poste « Côtes, dunes et plages »
# sur une carte à 600 m d'altitude, à 150 km de la mer.
_N2000_DUNAIRE = {
    "habitat_code_n2000": "2190",
    "habitat_n2000_rang": 10,
    "habitat_code_cahiers": "2190 ; 2190-1 ; 2190-2",
    "habitat_cahiers_rang": 20,
}


def test_l_annexe_i_seule_ne_range_pas_dans_les_dunes():
    classe, _source = hs.classe_habitat(dict(_N2000_DUNAIRE))
    assert classe != "B"
    assert classe == hs.CLASSE_INCONNUE


def test_une_vraie_dune_reste_une_dune():
    """EUNIS et CORINE, eux, font foi : un habitat littoral le reste."""
    classe, source = hs.classe_habitat({
        "habitat_code_eunis": "B1.3", "habitat_eunis_rang": 10,
    })
    assert classe == "B"
    assert source == hs.SOURCE_EUNIS


def test_le_littoral_corrobore_par_corine_tient():
    classe, _source = hs.classe_habitat({
        "habitat_code_corine": "16.29", "habitat_corine_rang": 10,
    })
    assert classe in ("A", "B")


def test_le_tiret_espace_ne_separe_pas_deux_fois_la_meme_alliance():
    """HABREF écrit « a-b » ici et « a - b » là : une seule végétation."""
    serre = hs.cle_habitat({"properties": {"habitat": "Mentho longifoliae-Juncion inflexi"}})
    espace = hs.cle_habitat({"properties": {"habitat": "Mentho longifoliae - Juncion inflexi"}})
    assert serre == espace


def test_un_habitat_muet_reprend_le_milieu_de_son_homonyme():
    """Deux entrées HABREF, une seule végétation : un seul grand milieu."""
    features = [
        {"properties": {"id_station": 1, "cd_hab": 16747, "recouvrement_pct": 60,
                        "habitat": "Mentho longifoliae - Juncion inflexi",
                        "habitat_code_eunis": "E3.1", "habitat_eunis_rang": 10}},
        {"properties": dict(_N2000_DUNAIRE, id_station=2, cd_hab=16573,
                            recouvrement_pct=100,
                            habitat="Mentho longifoliae-Juncion inflexi")},
    ]
    hs.enrichir(features)
    classes = {f["properties"][hs.CHAMP_CLASSE] for f in features}
    assert classes == {"E"}
    assert features[1]["properties"][hs.CHAMP_SOURCE] == hs.SOURCE_HOMONYME
    # Un seul poste de légende, donc un seul groupe.
    assert len(hs.palette(features)) == 1


def test_le_silence_ne_deteint_pas_sur_une_classe_etablie():
    """La propagation ne va que dans un sens."""
    features = [
        {"properties": {"id_station": 1, "cd_hab": 1, "recouvrement_pct": 100,
                        "habitat": "Alliance X",
                        "habitat_code_eunis": "G1", "habitat_eunis_rang": 10}},
        {"properties": {"id_station": 2, "cd_hab": 2, "recouvrement_pct": 100,
                        "habitat": "Alliance X"}},
    ]
    hs.enrichir(features)
    assert features[0]["properties"][hs.CHAMP_CLASSE] == "G"
    assert features[1]["properties"][hs.CHAMP_CLASSE] == "G"


# --- Formes abrégées de HABREF ----------------------------------------------
# HABREF donne la même alliance sous sa forme complète et sous sa forme abrégée.
# Trois paires relevées sur une seule carto ariégeoise, chacune sortie en deux
# postes de légende de deux couleurs différentes.
_ABREGES = [
    ("Brachypodio rupestris-Centaureion nemoralis", "Brachypodio-Centaureion nemoralis"),
    ("Tetragonolobo maritimi-Mesobromenion erecti", "Tetragonolobo-Mesobromenion"),
    ("Mentho longifoliae-Juncion inflexi", "Mentho-Juncion inflexi"),
    ("Mentho longifoliae - Juncion inflexi", "Mentho-Juncion inflexi"),
]


def test_la_forme_abregee_rejoint_la_forme_complete():
    for complet, abrege in _ABREGES:
        assert hs.cle_habitat({"properties": {"habitat": complet}}) == \
            hs.cle_habitat({"properties": {"habitat": abrege}}), complet


def test_un_nom_qui_n_est_pas_un_syntaxon_reste_entier():
    """Sans garde-fou, « Lacs, étangs… » tomberait à « Lacs, »."""
    for nom in ("Lacs, étangs et mares temporaires (C1.6)",
                "Réseaux de transport et autres zones de construction (J4)",
                "Autres plantations d'arbres feuillus caducifoliés (G1.C4)"):
        assert hs._squelette(nom) == hs._normaliser(nom), nom


def test_deux_syntaxons_differents_ne_fusionnent_pas():
    assert hs._squelette("Molinion caeruleae") != hs._squelette("Trifolion medii")
    assert hs._squelette("Galio aparines-Alliarietalia petiolatae") != \
        hs._squelette("Loto pedunculati - Filipenduletalia ulmariae")


def test_la_legende_garde_le_libelle_le_plus_renseigne():
    """Entre la forme complète et l'abrégée, on affiche celle qui apprend le plus."""
    features = [
        {"properties": {"id_station": 1, "cd_hab": 1, "recouvrement_pct": 100,
                        "habitat": "Brachypodio-Centaureion nemoralis",
                        "habitat_code_eunis": "E1.2", "habitat_eunis_rang": 10}},
        {"properties": {"id_station": 2, "cd_hab": 2, "recouvrement_pct": 100,
                        "habitat": "Brachypodio rupestris-Centaureion nemoralis",
                        "code_habref": "6.0.1.0.2",
                        "habitat_code_eunis": "E1.2", "habitat_eunis_rang": 10}},
    ]
    hs.enrichir(features)
    postes = [poste for _c, _l, habitats in hs.palette(features) for poste in habitats]
    assert len(postes) == 1  # une seule végétation, un seul poste
    assert "rupestris" in postes[0][1]


# --- Un habitat, une voix ----------------------------------------------------
# Cahiers d'habitats du Prunetalia spinosae, tels que la vue les rend : 81 fiches
# pour 8 habitats de l'annexe I. À elle seule, la pelouse calcicole 6210 en
# aligne 45, contre 11 pour la lande 4060.
_CAHIERS_PRUNETALIA = (
    "4060 ; 4060-1 ; 4060-2 ; 4060-3 ; 4060-4 ; 4060-5 ; 4060-6 ; 4060-7 ; "
    "4060-8 ; 4060-9 ; 4060-10 ; 4070 et 4060 ; (4070 et 4060)-1 ; "
    "5110 ; 5110-1 ; 5110-2 ; 5110-3 ; 5130 ; 5130-1 ; 5130-2 ; "
    "5210-1 ; 5210 (2250 inclus) ; (5210 et 2250)-2 ; "
    + " ; ".join("6210-%d" % i for i in range(1, 40))
    + " ; 9560 et 5210 ; (9560 et 5210)-1"
)


def test_les_declinaisons_des_cahiers_ne_votent_qu_une_fois():
    codes = hs.habitats_annexe_i(_CAHIERS_PRUNETALIA)
    assert codes == ["4060", "4070", "5110", "5130", "5210", "2250", "6210", "9560"]


def test_un_ordre_de_fourres_n_est_pas_une_pelouse():
    """Prunetalia spinosae : cinq habitats de landes contre une pelouse."""
    classe, _source = hs.classe_habitat({
        "habitat_code_n2000": "8240", "habitat_n2000_rang": 10,
        "habitat_code_cahiers": _CAHIERS_PRUNETALIA, "habitat_cahiers_rang": 21,
    })
    assert classe == "F"  # Landes et fruticées


def test_le_nombre_de_fiches_ne_fait_pas_le_milieu():
    """Le même habitat, décliné une fois ou quarante, pèse pareil."""
    peu = {"habitat_code_cahiers": "6210 ; 4060", "habitat_cahiers_rang": 20}
    beaucoup = {"habitat_code_cahiers":
                " ; ".join(["6210"] + ["6210-%d" % i for i in range(40)] + ["4060"]),
                "habitat_cahiers_rang": 20}
    assert hs.classe_habitat(peu)[0] == hs.classe_habitat(beaucoup)[0]


def test_un_seul_habitat_annexe_i_reste_lisible():
    assert hs.habitats_annexe_i("6410") == ["6410"]
    assert hs.habitats_annexe_i(None) == []
    assert hs.habitats_annexe_i("") == []


# --- La classe du Prodrome, dernier recours ----------------------------------
def test_classe_pvf_ne_retient_que_les_codes_numeriques():
    assert hs.classe_pvf({"code_habref": "51.0.2.0.2"}) == "51"
    assert hs.classe_pvf({"code_habref": "6.0.1.0.2"}) == "6"
    # « C1.6 », « E2.12 » sont des codes EUNIS : leur milieu se lit directement.
    assert hs.classe_pvf({"code_habref": "C1.6"}) is None
    assert hs.classe_pvf({"code_habref": None}) is None
    assert hs.classe_pvf({}) is None


def test_une_alliance_sans_correspondance_suit_sa_classe():
    """Caricion gracilis rejoint le Phragmition : même classe, mêmes bas-marais."""
    features = [
        {"properties": {"id_station": 1, "cd_hab": 1, "recouvrement_pct": 100,
                        "habitat": "Phragmition communis", "code_habref": "51.0.1.0.1",
                        "habitat_code_n2000": "7210", "habitat_n2000_rang": 10}},
        {"properties": {"id_station": 2, "cd_hab": 2, "recouvrement_pct": 100,
                        "habitat": "Caricion gracilis", "code_habref": "51.0.2.0.2"}},
    ]
    hs.enrichir(features)
    assert features[0]["properties"][hs.CHAMP_CLASSE] == "D"
    assert features[1]["properties"][hs.CHAMP_CLASSE] == "D"
    assert features[1]["properties"][hs.CHAMP_SOURCE] == hs.SOURCE_PVF


def test_une_classe_sans_voisin_reste_non_rattachee():
    """On ne rattache qu'à partir de ce qui est SUR LA CARTE."""
    features = [
        {"properties": {"id_station": 1, "cd_hab": 1, "recouvrement_pct": 100,
                        "habitat": "Sisymbrion officinalis",
                        "code_habref": "66.0.2.0.1"}},
    ]
    hs.enrichir(features)
    assert features[0]["properties"][hs.CHAMP_CLASSE] == hs.CLASSE_INCONNUE


def test_la_classe_pvf_ne_deteint_pas_sur_un_habitat_deja_rattache():
    features = [
        {"properties": {"id_station": 1, "cd_hab": 1, "recouvrement_pct": 100,
                        "habitat": "Alliance A", "code_habref": "20.0.1",
                        "habitat_code_eunis": "F3", "habitat_eunis_rang": 10}},
        {"properties": {"id_station": 2, "cd_hab": 2, "recouvrement_pct": 100,
                        "habitat": "Alliance B", "code_habref": "20.0.2",
                        "habitat_code_eunis": "G1", "habitat_eunis_rang": 10}},
    ]
    hs.enrichir(features)
    assert features[0]["properties"][hs.CHAMP_CLASSE] == "F"
    assert features[1]["properties"][hs.CHAMP_CLASSE] == "G"
