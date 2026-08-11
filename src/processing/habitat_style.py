# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Couleurs des habitats : une par habitat, harmonisées par grand milieu.

Deux niveaux, et c'est tout l'intérêt :

- le **ton** vient de la première lettre du code EUNIS, dont le niveau 1 est un
  découpage en grands milieux (G forêts, E prairies, F landes…) : une carte se
  lit d'un coup d'œil, tous les verts foncés sont des bois ;
- la **nuance** distingue chaque habitat à l'intérieur du ton. Les habitats
  présents sont étalés sur la plage de luminosité du milieu, dans l'ordre de
  leur code — deux codes voisins reçoivent donc deux nuances voisines, ce qui
  est une information et non un hasard.

Aucune liste d'habitats n'est maintenue ici : un habitat jamais rencontré reçoit
sa couleur sans que rien ne soit à déclarer.

Le rattachement **cascade sur les typologies** que la vue `v_occhab_complet`
fournit — EUNIS, puis CORINE biotopes, puis les codes de l'annexe I (et leur
déclinaison en Cahiers d'habitats). EUNIS d'abord, parce que son niveau 1 EST un
découpage en milieux ; les autres sont des approximations utiles. Sans cette
cascade, une cartographie saisie en **PVF1** virait entièrement au gris : dans
HABREF, le Prodrome n'a qu'une seule table de correspondance, `PVF1_HIC`, qui
mène aux habitats d'intérêt communautaire et pas à EUNIS.

Une station en mosaïque occupe plusieurs lignes de l'export, et **toutes sont
dessinées** — mais **côte à côte**, jamais superposées : chaque habitat reçoit
une **bande** du polygone proportionnelle à son recouvrement
(`bande_debut_pct` / `bande_fin_pct`), et garde ainsi un aplat de couleur franc.
Les hachures colorées superposées, essayées d'abord, saturaient la carte dès
qu'elle se densifiait et obligeaient à deviner que la hachure reprenait la
couleur d'un autre poste de légende.

Ce module ne dépend que de la bibliothèque standard.
"""
import colorsys
import re

#: Niveau 1 d'EUNIS : {lettre: (libellé, couleur de référence)}. La couleur est
#: le CENTRE de la gamme du milieu : les nuances s'en écartent vers le sombre et
#: vers le clair, ce qui double la plage disponible.
CLASSES_EUNIS = {
    "A": ("Milieux marins", "#1a237e"),
    "B": ("Côtes, dunes et plages", "#dd8f21"),
    "C": ("Eaux douces", "#039be5"),
    "D": ("Tourbières et bas-marais", "#5e35b1"),
    "E": ("Prairies et pelouses", "#7cb342"),
    "F": ("Landes et fruticées", "#6d4c41"),
    "G": ("Forêts et bois", "#1b5e20"),
    "H": ("Rochers, éboulis, peu végétalisé", "#757575"),
    "I": ("Cultures et jardins", "#c0ca33"),
    "J": ("Bâti et milieux artificialisés", "#bf360c"),
    "X": ("Complexes d'habitats", "#00897b"),
}
#: Classe de repli : habitat sans équivalent EUNIS, ou station sans habitat.
CLASSE_INCONNUE = "?"
LIBELLE_INCONNU = "Habitat non rattaché (ni EUNIS, ni CORINE, ni N2000)"
COULEUR_INCONNUE = "#9e9e9e"

#: Champs ajoutés à chaque entité. Nommés en clair : ils apparaissent dans la
#: table attributaire de QGIS et dans la légende.
CHAMP_CLASSE = "classe_milieu"
CHAMP_LIBELLE = "libelle_milieu"
CHAMP_CLE = "cle_habitat"
CHAMP_DOMINANT = "est_dominant"
CHAMP_MOSAIQUE = "est_mosaique"
CHAMP_COMPOSITION = "composition"
CHAMP_SOURCE = "source_classe"
#: Rang de l'habitat dans sa station : 0 = dominant, 1, 2… par recouvrement
#: décroissant. Fixe l'ordre des bandes et désigne qui porte le contour.
CHAMP_RANG = "rang_habitat"
CHAMP_COULEUR = "couleur"
#: Bornes de la bande revenant à l'habitat dans son polygone, en pourcentage
#: cumulé (0 → 60 → 85 → 100). Le rendu y découpe des aplats côte à côte au lieu
#: de superposer des hachures.
CHAMP_DEBUT = "bande_debut_pct"
CHAMP_FIN = "bande_fin_pct"

_SEPARATEUR = " ; "
#: Écart de luminosité admis de part et d'autre de la couleur de référence.
#: Volontairement modéré : étaler davantage sépare mieux DEUX habitats d'un même
#: milieu, mais rapproche une prairie très sombre d'un vert forestier — et la
#: confusion entre milieux coûte plus cher que la confusion à l'intérieur d'un
#: milieu, où la légende reste groupée.
_AMPLITUDE = 0.20
#: Bornes volontairement en retrait du noir et du blanc : aux extrêmes, la
#: saturation ne se voit plus, et deux nuances de saturations différentes s'y
#: confondraient.
_LUMINOSITE_MAX = 0.74
_LUMINOSITE_MIN = 0.20


# --------------------------------------------------------------- classement
def classe_eunis(code):
    """Lettre de classe EUNIS d'un code, ou None.

    Accepte les valeurs multiples de la vue (« F3.16 ; F3.1A ») : la première
    sert, les équivalents d'un même habitat relevant du même grand milieu.
    """
    if not isinstance(code, str):
        return None
    premier = code.split(_SEPARATEUR.strip())[0].strip()
    if not premier:
        return None
    lettre = premier[0].upper()
    return lettre if lettre in CLASSES_EUNIS else None


def libelle_classe(classe):
    """Libellé lisible d'une classe (repli compris)."""
    return CLASSES_EUNIS.get(classe, (LIBELLE_INCONNU, COULEUR_INCONNUE))[0]


def couleur_classe(classe):
    """Couleur de référence d'une classe (repli compris)."""
    return CLASSES_EUNIS.get(classe, (LIBELLE_INCONNU, COULEUR_INCONNUE))[1]


# ----------------------------------------------------------------- couleurs
def _hex_vers_rgb(couleur):
    valeur = (couleur or "").lstrip("#")
    return tuple(int(valeur[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _rgb_vers_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c * 255))) for c in rgb)


def _nuance(couleur, delta_lum=0.0, facteur_sat=1.0, delta_teinte=0.0):
    """Décliner une couleur en TSL (luminosité, saturation, teinte).

    Passe par TSL et non par RVB : éclaircir en ajoutant du blanc délave aussi
    la saturation, et une gamme de verts finirait grisâtre.
    """
    teinte, lum, sat = colorsys.rgb_to_hls(*_hex_vers_rgb(couleur))
    lum = max(0.0, min(_LUMINOSITE_MAX, lum + delta_lum))
    sat = max(0.0, min(1.0, sat * facteur_sat))
    return _rgb_vers_hex(colorsys.hls_to_rgb((teinte + delta_teinte) % 1.0, lum, sat))


def eclaircir(couleur, delta):
    """Même teinte, luminosité augmentée de `delta` (bornée)."""
    return _nuance(couleur, delta_lum=delta)


#: Saturations successives d'un même niveau de luminosité. Une gamme répartie
#: sur la SEULE luminosité s'effondre vite : au-delà de huit habitats dans un
#: milieu, deux nuances quelconques passaient sous 10 d'écart RVB (sur 255),
#: soit l'indiscernable. Croiser luminosité et saturation multiplie par trois le
#: nombre de nuances séparables, sans sortir du ton.
_SATURATIONS = (1.0, 0.55, 0.30)
#: En deçà, la couleur est un gris : son axe de saturation ne sépare rien.
_SATURATION_MINIMALE = 0.08
#: Nuances distinguables sur la seule luminosité. Au-delà, les paliers se
#: resserrent trop : on ouvre un nouveau palier de saturation.
_NIVEAUX_LUMINOSITE_MAX = 6


def _plage_luminosite(base):
    """(min, max) de luminosité exploitables autour de la couleur de référence.

    La plage est REPORTÉE, pas rognée : un ton déjà très sombre — le vert des
    forêts — bute sur la borne basse et perdrait sinon la moitié de son étendue,
    au point que six nuances y devenaient indiscernables alors qu'elles
    tenaient largement ailleurs. Ce qui manque d'un côté est repris de l'autre.
    """
    lum = colorsys.rgb_to_hls(*_hex_vers_rgb(base))[1]
    bas, haut = lum - _AMPLITUDE, lum + _AMPLITUDE
    if bas < _LUMINOSITE_MIN:
        haut += _LUMINOSITE_MIN - bas
        bas = _LUMINOSITE_MIN
    if haut > _LUMINOSITE_MAX:
        bas -= haut - _LUMINOSITE_MAX
        haut = _LUMINOSITE_MAX
    return max(_LUMINOSITE_MIN, bas), min(_LUMINOSITE_MAX, haut)


def _teinte_saturation(base):
    teinte, _lum, sat = colorsys.rgb_to_hls(*_hex_vers_rgb(base))
    return teinte, sat


def gamme(classe, nombre):
    """`nombre` nuances de la classe, toutes dans son ton, aussi écartées que possible.

    Deux régimes, parce qu'un seul ne convient pas aux deux bouts :

    - **peu d'habitats** — la luminosité seule sépare le mieux, on l'étale sur
      toute la plage du ton (un vert très sombre et un vert clair) ;
    - **beaucoup d'habitats** — la luminosité ne suffit plus (au-delà de huit,
      deux nuances passaient sous 10 d'écart RVB sur 255, soit l'indiscernable) :
      on croise alors luminosité et saturation, ce qui triple le nombre de
      nuances séparables sans sortir du ton.
    """
    base = couleur_classe(classe)
    if nombre <= 1:
        return [base]
    lum_min, lum_max = _plage_luminosite(base)
    teinte, sat_base = _teinte_saturation(base)

    def couleur(lum, facteur_sat):
        return _rgb_vers_hex(colorsys.hls_to_rgb(
            teinte, lum, max(0.0, min(1.0, sat_base * facteur_sat))
        ))

    # Un ton achromatique (le gris des rochers) n'a pas de saturation à faire
    # varier : la multiplier laisserait des nuances identiques. Seule la
    # luminosité sépare alors, et elle seule.
    if sat_base < _SATURATION_MINIMALE:
        pas = (lum_max - lum_min) / (nombre - 1)
        return [couleur(lum_min + pas * i, 1.0) for i in range(nombre)]

    # LUMINOSITÉ EN AXE RAPIDE. L'inverse paraissait plus malin — épuiser les
    # saturations avant de changer de luminosité — mais il place les premières
    # nuances au point le plus sombre du ton, là où baisser la saturation ne
    # change presque rien : trois quasi-identiques, écart RVB sous 5. La
    # luminosité, elle, sépare partout.
    niveaux = min(nombre, _NIVEAUX_LUMINOSITE_MAX)
    pas = (lum_max - lum_min) / max(1, niveaux - 1)
    couleurs = []
    for i in range(nombre):
        rang, phase = i % niveaux, i // niveaux
        facteur = _SATURATIONS[min(phase, len(_SATURATIONS) - 1)]
        # Chaque palier de saturation est DÉCALÉ d'une fraction de cran : sans
        # ce décalage, deux paliers partagent les mêmes luminosités et ne se
        # distinguent plus que par la saturation — insuffisant sur un ton déjà
        # peu saturé comme le brun des landes (écart tombé sous 5 sur 255).
        decalage = pas * (phase / len(_SATURATIONS))
        couleurs.append(couleur(min(lum_max, lum_min + pas * rang + decalage), facteur))
    return couleurs


# --------------------------------------------------- classement en cascade
#: Niveau 1 de CORINE biotopes → grand milieu. Le groupe 3 réunit landes ET
#: prairies : le deuxième chiffre les sépare (31 à 33 = landes, fruticées et
#: matorrals ; 34 et au-delà = pelouses et prairies).
_CORINE_VERS_MILIEU = {
    "1": "B", "2": "C", "4": "G", "5": "D", "6": "H", "8": "I",
}
#: Groupes de l'annexe I de la directive Habitats → grand milieu. Structure
#: stable et documentée : 1 côtiers, 2 dunes, 3 eaux douces, 4 landes et fourrés
#: tempérés, 5 fourrés sclérophylles, 6 formations herbacées, 7 tourbières et
#: marais, 8 habitats rocheux, 9 forêts.
_N2000_VERS_MILIEU = {
    "1": "B", "2": "B", "3": "C", "4": "F", "5": "F",
    "6": "E", "7": "D", "8": "H", "9": "G",
}
#: Ordre de la cascade : colonne de la vue, fonction de lecture, étiquette de
#: provenance. EUNIS d'abord — c'est le seul dont le niveau 1 EST un découpage
#: en milieux ; les autres sont des approximations utiles.
SOURCE_EUNIS = "EUNIS"
SOURCE_CORINE = "CORINE"
SOURCE_N2000 = "N2000"


def codes_multiples(valeur):
    """Tous les codes d'une colonne pouvant en porter plusieurs (« a ; b »).

    Les lire TOUS est essentiel : la vue agrège les équivalents par ordre
    alphabétique, si bien que n'en retenir qu'un revenait à laisser l'alphabet
    décider du milieu. Une chênaie-frênaie dont les équivalents commençaient par
    un code « B… » se retrouvait ainsi classée en « côtes et dunes ».
    """
    if not isinstance(valeur, str):
        return []
    return [code.strip() for code in valeur.split(_SEPARATEUR.strip()) if code.strip()]


def _premier_code(valeur):
    """Premier code d'une colonne pouvant en porter plusieurs (« a ; b »)."""
    codes = codes_multiples(valeur)
    return codes[0] if codes else None


def classe_corine(code):
    """Grand milieu déduit d'un code CORINE biotopes, ou None."""
    premier = _premier_code(code)
    if not premier or not premier[0].isdigit():
        return None
    if premier[0] == "3":
        # 31 landes et fruticées, 32/33 matorrals : des fourrés. 34 et suivants :
        # pelouses et prairies. Sans ce partage, une pelouse sèche se colorerait
        # comme une lande.
        second = premier[1] if len(premier) > 1 and premier[1].isdigit() else "4"
        return "F" if second in "123" else "E"
    return _CORINE_VERS_MILIEU.get(premier[0])


def classe_n2000(code):
    """Grand milieu déduit d'un code de l'annexe I (« 6510 », « 9120 »), ou None."""
    premier = _premier_code(code)
    if not premier or not premier[0].isdigit():
        return None
    return _N2000_VERS_MILIEU.get(premier[0])


#: Poids d'un code selon sa typologie. EUNIS pèse double : son niveau 1 EST un
#: découpage en milieux, là où CORINE et l'annexe I n'en sont que des reflets.
_POIDS = {SOURCE_EUNIS: 2, SOURCE_CORINE: 1, SOURCE_N2000: 1}
#: Milieux marins et littoraux : retenus seulement si RIEN d'autre ne vote.
_LITTORALES = frozenset({"A", "B"})
#: Sources qui peuvent, à elles seules, ranger un habitat dans un milieu
#: littoral. L'annexe I n'en fait PAS partie : ses correspondances disent où une
#: végétation *peut se rencontrer*, pas ce qu'elle est. HABREF relie ainsi le
#: Caricion gracilis, le Mentho longifoliae-Juncion inflexi et l'Oenanthion
#: fistulosae à l'habitat 2190 « Dépressions humides intradunales », parce que
#: ces alliances décrivent aussi la végétation des pannes dunaires. Les prendre
#: au mot range des bas-marais ariégeois dans les dunes.
_TEMOINS_LITTORAUX = frozenset({SOURCE_EUNIS, SOURCE_CORINE})


#: Poids selon le RANG de la correspondance, tel que la vue le calcule :
#: 0 = l'habitat est déjà dans cette typologie, 10 = correspondance directe,
#: 11/12 = héritée d'un parent ou d'un descendant, 20+ = obtenue en traversant
#: une typologie intermédiaire.
#:
#: C'est le garde-fou décisif contre le bruit. Les correspondances à deux sauts
#: rattachent volontiers une magnocariçaie à une dépression dunaire — les deux
#: sont humides — et sans pondération, ce détour pesait autant qu'une
#: correspondance directe. D'où des végétations de bord d'étang classées en
#: « côtes et dunes ».
_POIDS_RANG = ((10, 4), (13, 2))
_POIDS_RANG_LOINTAIN = 1


def poids_rang(rang):
    """Poids d'une correspondance selon son éloignement."""
    try:
        valeur = int(rang)
    except (TypeError, ValueError):
        return _POIDS_RANG[0][1]  # rang inconnu : on ne pénalise pas
    for seuil, poids in _POIDS_RANG:
        if valeur <= seuil:
            return poids
    return _POIDS_RANG_LOINTAIN


#: Un code de l'annexe I : quatre chiffres. Ses déclinaisons des Cahiers
#: d'habitats ajoutent un tiret et un numéro (« 6210-38 »), et certains libellés
#: en citent deux à la fois (« (5210 et 2250)-2 »).
_CODE_ANNEXE_I = re.compile(r"\b(\d{4})\b")


def habitats_annexe_i(valeur):
    """Codes d'habitat de l'annexe I cités, sans leurs déclinaisons ni doublons.

    Les Cahiers d'habitats déclinent chaque habitat en autant de fiches qu'il a
    de variantes, et le compte varie du simple au quadruple : l'habitat 6210
    (pelouses calcicoles) en aligne **45**, l'habitat 4060 (landes) en aligne 11.
    Laisser voter chaque fiche revient à voter le nombre de variantes plutôt que
    le milieu.

    Mesuré sur le `Prunetalia spinosae` — un ordre de FOURRÉS : relié à 4060,
    4070, 5110, 5130 et 5210 (landes et fruticées) contre le seul 6210, il
    sortait pourtant en « Prairies et pelouses », les 45 fiches de 6210 écrasant
    les 36 des cinq autres. Un habitat, une voix.
    """
    vus = []
    for code in _CODE_ANNEXE_I.findall(str(valeur or "")):
        if code not in vus:
            vus.append(code)
    return vus


def _lectures(props):
    """(typologie, code, lecture, poids du rang) pour chaque code disponible."""
    for source, colonne, colonne_rang, lecture, decoupe in (
        (SOURCE_EUNIS, "habitat_code_eunis", "habitat_eunis_rang", classe_eunis,
         codes_multiples),
        (SOURCE_CORINE, "habitat_code_corine", "habitat_corine_rang", classe_corine,
         codes_multiples),
        (SOURCE_N2000, "habitat_code_n2000", "habitat_n2000_rang", classe_n2000,
         habitats_annexe_i),
        # Les Cahiers d'habitats déclinent les codes de l'annexe I (« 6510-1 ») :
        # même premier chiffre, même lecture, et un seul vote par habitat.
        (SOURCE_N2000, "habitat_code_cahiers", "habitat_cahiers_rang", classe_n2000,
         habitats_annexe_i),
    ):
        poids = poids_rang(props.get(colonne_rang))
        for code in decoupe(props.get(colonne)):
            yield source, code, lecture, poids


#: Colonnes que la vue PEUT fournir : racine hiérarchique HABREF de l'équivalent
#: EUNIS, avec le libellé officiel. Quand elles sont là, elles font autorité et
#: le vote ci-dessous n'a pas lieu — le rattachement vient alors du référentiel
#: lui-même et non des tables de conversion de ce module.
COLONNE_GRAND_TYPE = "grand_type_code"
COLONNE_GRAND_TYPE_NOM = "grand_type_nom"
SOURCE_HABREF = "HABREF"
#: Milieu repris d'une autre entrée HABREF portant le même nom de végétation.
SOURCE_HOMONYME = "homonyme"


def classe_declaree(props):
    """(classe, libellé) fournis par la vue, ou (None, None).

    La racine n'est retenue que si c'est une classe EUNIS connue : une racine
    venue d'une autre typologie n'aurait pas de couleur attribuée, et un grand
    type sans couleur ne sert à rien sur une carte.
    """
    code = (props or {}).get(COLONNE_GRAND_TYPE)
    if not isinstance(code, str):
        return None, None
    lettre = code.strip().upper()[:1]
    if lettre not in CLASSES_EUNIS:
        return None, None
    return lettre, (props.get(COLONNE_GRAND_TYPE_NOM) or "").strip() or None


def classe_habitat(props):
    """(classe, provenance) d'un habitat, par VOTE de tous ses équivalents.

    Un vote, et non le premier code venu. Les correspondances HABREF obtenues à
    deux sauts charrient du bruit : un habitat forestier peut hériter d'un
    équivalent côtier isolé, et le prendre pour argent comptant range la chênaie
    dans les dunes. La majorité des codes, elle, désigne le bon milieu.

    Les typologies votent ensemble plutôt qu'en cascade stricte : quand EUNIS
    hésite, CORINE et l'annexe I tranchent. Une cartographie **PVF1** ne dispose
    d'ailleurs que de ces dernières — le Prodrome n'a, dans HABREF, qu'une table
    de correspondance, `PVF1_HIC`.
    """
    # La vue fait autorité quand elle donne la racine HABREF : inutile de voter.
    declaree, _libelle = classe_declaree(props)
    if declaree:
        return declaree, SOURCE_HABREF

    voix, temoins = {}, {}
    for source, code, lecture, poids in _lectures(props or {}):
        classe = lecture(code)
        if not classe:
            continue
        voix[classe] = voix.get(classe, 0) + _POIDS[source] * poids
        temoins.setdefault(classe, set()).add(source)
    # Un milieu littoral que seule l'annexe I désigne n'est pas une information :
    # c'est un effet de bord des correspondances (cf. `_TEMOINS_LITTORAUX`).
    for classe in list(voix):
        if classe in _LITTORALES and not (temoins[classe] & _TEMOINS_LITTORAUX):
            del voix[classe]
            del temoins[classe]
    if not voix:
        return CLASSE_INCONNUE, None
    ordre = list(CLASSES_EUNIS)
    # Trois critères, dans cet ordre :
    #  1. les milieux littoraux passent en DERNIER RECOURS. Une correspondance
    #     isolée vers un habitat de dune suffisait à ranger une chênaie dans les
    #     côtes ; en cartographie continentale c'est toujours du bruit, et un
    #     habitat réellement littoral l'emporte quand même — rien d'autre ne vote ;
    #  2. le nombre de voix ;
    #  3. à égalité, l'ordre d'EUNIS, pour que le résultat ne dépende pas de
    #     l'ordre de parcours d'un dictionnaire.
    gagnante = max(voix, key=lambda c: (
        c not in _LITTORALES,
        voix[c],
        -ordre.index(c) if c in ordre else 0,
    ))
    provenance = "+".join(
        s for s in (SOURCE_EUNIS, SOURCE_CORINE, SOURCE_N2000)
        if s in temoins[gagnante]
    )
    return gagnante, provenance


# ------------------------------------------------------------------ entités
def _proprietes(feature):
    return (feature or {}).get("properties") or {}


def _recouvrement(feature):
    """Recouvrement numérique d'une entité, 0 si absent ou illisible."""
    valeur = _proprietes(feature).get("recouvrement_pct")
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return 0.0


def _nom_habitat(feature):
    props = _proprietes(feature)
    return props.get("nom_cite") or props.get("habitat") or None


def _normaliser(texte):
    """Nom comparable : ni la casse, ni les espaces, ni le tiret ne séparent.

    HABREF écrit la même alliance « Mentho longifoliae-Juncion inflexi » ici et
    « Mentho longifoliae - Juncion inflexi » là. Deux entrées de légende, deux
    couleurs, pour une seule végétation — et, depuis que les correspondances
    diffèrent d'une entrée à l'autre, deux GRANDS MILIEUX différents.
    """
    texte = " ".join(str(texte or "").split())
    texte = re.sub(r"\s*-\s*", "-", texte)  # « a - b » et « a-b » sont un seul nom
    return texte.casefold()


#: Terminaisons des noms de syntaxons. Un nom de végétation se reconnaît à son
#: dernier rang : -ion pour une alliance, -enion pour une sous-alliance,
#: -etalia pour un ordre, -etea pour une classe, -etum pour une association.
_SUFFIXES_SYNTAXON = ("ion", "etalia", "etea", "etum")


def _squelette(nom):
    """Nom de syntaxon réduit à ses genres, ou le nom tel quel.

    HABREF donne la même alliance sous sa forme complète et sous sa forme
    abrégée : « Brachypodio rupestris-Centaureion nemoralis » et
    « Brachypodio-Centaureion nemoralis », « Tetragonolobo maritimi-Mesobromenion
    erecti » et « Tetragonolobo-Mesobromenion ». Deux entrées de légende, deux
    couleurs, pour une seule végétation. Les épithètes seules diffèrent, et pas
    toujours les mêmes : on ne garde donc que le premier mot de chaque membre.

    La réduction ne s'applique QU'AUX noms de syntaxons, reconnus au suffixe de
    leur dernier membre. Sans ce garde-fou, « Lacs, étangs et mares temporaires »
    tomberait à « Lacs, » et se confondrait avec tout ce qui commence pareil.
    """
    normalise = _normaliser(nom)
    if "-" not in normalise or "," in normalise:
        return normalise
    membres = [m.strip() for m in normalise.split("-") if m.strip()]
    if len(membres) < 2:
        return normalise
    dernier = membres[-1].split()[0]
    if not dernier.endswith(_SUFFIXES_SYNTAXON):
        return normalise
    return "-".join(membre.split()[0] for membre in membres)


def _correspondance(props, typologie):
    """(nom, code) de l'habitat dans `typologie`, ou None s'il n'en a pas.

    `None` déclenche le REPLI sur l'habitat saisi : une carte ne doit pas perdre
    un polygone parce que HABREF ne sait pas le traduire. Mieux vaut un habitat
    exprimé dans une autre typologie qu'un trou dans la légende.
    """
    if not typologie:
        return None
    nom = props.get("habitat_nom_%s" % typologie)
    code = props.get("habitat_code_%s" % typologie)
    return (nom, code) if (nom or code) else None


def cle_habitat(feature, typologie=None):
    """Identité de l'habitat pour la couleur : son NOM HABREF, sinon le cd_hab.

    `typologie` (nom court : « corine », « eunis »…) demande de cartographier
    l'habitat dans CETTE typologie plutôt que dans celle où il a été déterminé.
    Sans correspondance, on retombe sur l'habitat saisi.

    Le `cd_hab` semblait l'identifiant sûr. Il crée en fait des doublons de
    légende : HABREF porte plusieurs `cd_hab` pour un même syntaxon — la même
    végétation y figure sous une entrée codée et une entrée sans code, ou
    simplement deux fois. Une carto en a sorti « Tetragonolobo maritimi-
    Mesobromenion erecti (26.0.2.0.3.3) » DEUX fois, libellé et code identiques,
    en deux couleurs.

    Le nom scientifique (`lb_hab_fr` de HABREF) regroupe ces entrées, réduit à
    ses genres (`_squelette`) pour que la forme abrégée rejoigne la complète.
    Repli sur le nom cité puis sur le cd_hab quand il manque.
    """
    props = _proprietes(feature)
    correspondance = _correspondance(props, typologie)
    if correspondance is not None:
        nom, code = correspondance
        # Le nom d'abord, pour la même raison que plus bas : il regroupe les
        # entrées HABREF en double. Le code seul quand la vue n'a pas résolu le
        # libellé — c'est le cas d'une correspondance saisie.
        return "nom:%s" % _squelette(nom) if nom else "code:%s" % code
    for valeur in (props.get("habitat"), props.get("nom_cite")):
        if valeur:
            return "nom:%s" % _squelette(valeur)
    cd_hab = props.get("cd_hab")
    return "cd:%s" % cd_hab if cd_hab not in (None, "") else None


def libelle_habitat(feature, typologie=None):
    """Libellé de légende : nom de l'habitat suivi de son code.

    Suit le même choix de typologie que `cle_habitat` — sans quoi la légende
    nommerait un habitat autrement que la couleur ne le regroupe.
    """
    props = _proprietes(feature)
    correspondance = _correspondance(props, typologie)
    if correspondance is not None:
        nom, code = correspondance
    else:
        nom = props.get("habitat") or props.get("nom_cite")
        code = props.get("code_habref") or props.get("habitat_code_eunis")
    if nom and code:
        return "%s (%s)" % (nom, str(code).split(_SEPARATEUR.strip())[0].strip())
    return nom or (str(code) if code else LIBELLE_INCONNU)


def composition(features):
    """« Hêtraie 60 % ; Lande 25 % » pour une station, du plus couvrant au moins."""
    parts = []
    for feature in sorted(features, key=_recouvrement, reverse=True):
        nom = _nom_habitat(feature)
        if not nom:
            continue
        pct = _recouvrement(feature)
        parts.append("%s %g %%" % (nom, pct) if pct else nom)
    return _SEPARATEUR.join(parts) or None


def _bandes(classement):
    """{id(entité): (début %, fin %)} — la part de polygone revenant à chacun.

    C'est ce qui permet de dessiner les habitats d'une mosaïque **côte à côte**
    plutôt que superposés : chacun occupe une bande proportionnelle à son
    recouvrement, et garde donc un aplat de couleur franc, lisible à n'importe
    quelle densité de polygones. Le dominant vient en premier, donc en bas.

    Sans recouvrement renseigné, les parts sont égales : mieux vaut des bandes
    arbitraires mais visibles qu'un habitat réduit à rien.
    """
    ordre = list(classement)
    valeurs = [_recouvrement(f) for f in ordre]
    total = sum(valeurs)
    if total <= 0:
        valeurs = [1.0] * len(ordre)
        total = float(len(ordre)) or 1.0
    bornes, curseur = {}, 0.0
    for feature, valeur in zip(ordre, valeurs):
        part = 100.0 * valeur / total
        bornes[id(feature)] = (round(curseur, 4), round(curseur + part, 4))
        curseur += part
    # Le dernier atteint exactement 100 : un reste d'arrondi laisserait une
    # bande vide en haut du polygone.
    if ordre:
        debut = bornes[id(ordre[-1])][0]
        bornes[id(ordre[-1])] = (debut, 100.0)
    return bornes


def enrichir(features, cle_station="id_station", typologie=None):
    """Ajouter les champs de style aux entités (mute et renvoie la liste).

    Un seul parcours par station : l'habitat dominant reçoit `est_dominant`, et
    lui seul sera dessiné — les autres lignes restent dans la table attributaire,
    car l'export ne doit rien perdre de ce que le serveur a rendu.
    """
    features = [f for f in features or [] if isinstance(f, dict)]
    stations = {}
    for feature in features:
        stations.setdefault(_proprietes(feature).get(cle_station), []).append(feature)

    for lot in stations.values():
        # `max` rend le PREMIER maximum : à recouvrements égaux, l'ordre du
        # serveur tranche, donc le résultat ne change pas d'un chargement à
        # l'autre.
        # Ordre décroissant de recouvrement : le rang 0 est l'habitat dominant,
        # qui reçoit l'aplat ; les suivants se superposent en hachures.
        classement = sorted(lot, key=_recouvrement, reverse=True)
        dominant = classement[0]
        texte = composition(lot)
        mosaique = len([f for f in lot if _nom_habitat(f)]) > 1
        bornes = _bandes(classement)
        for feature in lot:
            props = feature.setdefault("properties", {})
            props[CHAMP_DEBUT], props[CHAMP_FIN] = bornes[id(feature)]
            classe, source = classe_habitat(props)
            _declaree, libelle_declare = classe_declaree(props)
            props[CHAMP_CLASSE] = classe
            # Libellé de HABREF s'il est fourni : c'est le mot officiel du
            # référentiel, pas notre traduction maison.
            props[CHAMP_LIBELLE] = libelle_declare or libelle_classe(classe)
            # Sur quelle typologie la couleur a été décidée : indispensable pour
            # relire une carte dont les habitats viennent de référentiels
            # différents, et pour repérer ce qui n'a pu être rattaché.
            props[CHAMP_SOURCE] = source
            props[CHAMP_CLE] = cle_habitat(feature, typologie) or CLASSE_INCONNUE
            props[CHAMP_DOMINANT] = 1 if feature is dominant else 0
            props[CHAMP_RANG] = classement.index(feature)
            props[CHAMP_MOSAIQUE] = 1 if mosaique else 0
            props[CHAMP_COMPOSITION] = texte
    _rattacher_les_homonymes(features)
    _rattacher_par_classe_pvf(features)
    return features


#: Colonne portant le code du syntaxon dans sa typologie (« 51.0.2.0.2 »).
COLONNE_CODE = "code_habref"
#: Milieu déduit de la classe du Prodrome des végétations de France.
SOURCE_PVF = "classe PVF"


def classe_pvf(props):
    """Numéro de classe du Prodrome, tiré du code du syntaxon, ou None.

    Le code d'un syntaxon commence par le numéro de sa CLASSE
    phytosociologique : « 51.0.2.0.2 » (Caricion gracilis) et « 51.0.1.0.1 »
    (Phragmition communis) sont deux alliances de la même classe. Une classe de
    végétation est une unité écologique — c'est ce qui rend le rapprochement
    légitime.

    Seuls les codes NUMÉRIQUES sont retenus : « C1.6 » ou « E2.12 » sont des
    codes EUNIS, dont le milieu se lit directement.
    """
    code = str((props or {}).get(COLONNE_CODE) or "").strip()
    tete = code.split(".")[0]
    return tete if tete.isdigit() else None


def _rattacher_par_classe_pvf(features):
    """Dernier recours : le milieu des autres alliances de la même classe.

    HABREF ne donne à certains syntaxons aucune correspondance vers EUNIS,
    CORINE ou l'annexe I. Ils restent gris, alors que le référentiel sait
    parfaitement où les ranger : leur CLASSE phytosociologique le dit.

    Trois cas relevés sur une carto ariégeoise, tous justes :

    - `Caricion gracilis` (51.0.2.0.2) rejoint le `Phragmition communis`
      (51.0.1.0.1) dans les **tourbières et bas-marais** ;
    - `Cynosurion cristati` (6.0.2.0.1) rejoint le `Brachypodio
      rupestris-Centaureion nemoralis` (6.0.1.0.2) dans les **prairies** ;
    - `Lonicerion periclymeni` (20.0.2.0.4) rejoint le `Prunetalia spinosae`
      (20.0.2) dans les **landes et fruticées**.

    Comme pour les homonymes, la propagation ne va que dans un sens, et seules
    les alliances PRÉSENTES SUR LA CARTE votent : on ne rattache jamais un
    habitat à partir d'un référentiel qu'on n'aurait pas sous les yeux.
    """
    connues = {}
    for feature in features:
        props = _proprietes(feature)
        classe = props.get(CHAMP_CLASSE)
        pvf = classe_pvf(props)
        if not pvf or classe in (None, CLASSE_INCONNUE):
            continue
        connues.setdefault(pvf, {})
        connues[pvf][classe] = connues[pvf].get(classe, 0) + 1

    ordre = list(CLASSES_EUNIS)
    for feature in features:
        props = feature.setdefault("properties", {})
        if props.get(CHAMP_CLASSE) != CLASSE_INCONNUE:
            continue
        candidats = connues.get(classe_pvf(props))
        if not candidats:
            continue
        classe = max(candidats, key=lambda c: (
            candidats[c], -ordre.index(c) if c in ordre else 0))
        props[CHAMP_CLASSE] = classe
        props[CHAMP_LIBELLE] = libelle_classe(classe)
        props[CHAMP_SOURCE] = SOURCE_PVF
    return features


def _rattacher_les_homonymes(features):
    """Donner aux habitats non rattachés le milieu de leur homonyme.

    HABREF porte la même alliance sous plusieurs entrées, dont les
    correspondances diffèrent : « Mentho longifoliae-Juncion inflexi » ressort
    d'EUNIS et de CORINE sous un `cd_hab`, et de la seule annexe I sous un autre.
    Le premier est rattaché aux prairies, le second à rien du tout depuis qu'on
    écarte les milieux littoraux mal fondés.

    Or c'est la MÊME végétation, et la légende la regroupe déjà sous une seule
    entrée. Lui laisser deux milieux la ferait apparaître deux fois, dans deux
    groupes. On propage donc le milieu connu à ses homonymes muets — jamais
    l'inverse : une classe établie n'est pas remise en cause par un silence.
    """
    connues = {}
    for feature in features:
        props = _proprietes(feature)
        classe = props.get(CHAMP_CLASSE)
        cle = props.get(CHAMP_CLE)
        if not cle or classe in (None, CLASSE_INCONNUE):
            continue
        connues.setdefault(cle, {})
        connues[cle][classe] = connues[cle].get(classe, 0) + 1

    for feature in features:
        props = feature.setdefault("properties", {})
        if props.get(CHAMP_CLASSE) != CLASSE_INCONNUE:
            continue
        candidats = connues.get(props.get(CHAMP_CLE))
        if not candidats:
            continue
        # À plusieurs milieux possibles, le plus souvent constaté ; à égalité,
        # l'ordre d'EUNIS, pour que le résultat ne dépende pas du parcours.
        ordre = list(CLASSES_EUNIS)
        classe = max(candidats, key=lambda c: (
            candidats[c], -ordre.index(c) if c in ordre else 0))
        props[CHAMP_CLASSE] = classe
        props[CHAMP_LIBELLE] = libelle_classe(classe)
        props[CHAMP_SOURCE] = SOURCE_HOMONYME
    return features


def palette(features, typologie=None):
    """Couleurs à poser, groupées par grand milieu.

    Returns:
        [(classe, libellé du milieu, [(clé, libellé habitat, couleur)])] —
        classes dans l'ordre d'EUNIS (l'inconnue en dernier), habitats triés par
        code EUNIS pour que deux codes voisins reçoivent deux nuances voisines.

    **Tous** les habitats entrent en légende, dominants ou non : une mosaïque
    partage son polygone entre ses habitats, un habitat secondaire est donc bel
    et bien dessiné, avec sa propre couleur. Chaque entité reçoit d'ailleurs sa
    couleur en attribut (`couleur`), ce dont le rendu se sert sans avoir à créer
    une règle par habitat et par rang.
    """
    par_classe = {}
    for feature in features or []:
        props = _proprietes(feature)
        cle = props.get(CHAMP_CLE) or CLASSE_INCONNUE
        classe = props.get(CHAMP_CLASSE) or CLASSE_INCONNUE
        habitats = par_classe.setdefault(classe, {})
        libelle = libelle_habitat(feature, typologie)
        ancien = habitats.get(cle)
        # Plusieurs entrées HABREF derrière une même clé : on affiche la plus
        # RENSEIGNÉE. « Brachypodio rupestris-Centaureion nemoralis (6.0.1.0.2) »
        # dit l'épithète et le code ; « Brachypodio-Centaureion nemoralis », sa
        # forme abrégée, n'apprend rien de plus.
        if ancien is None or len(libelle) > len(ancien[0]):
            habitats[cle] = (
                libelle,
                str(props.get("habitat_code_eunis") or (ancien[1] if ancien else "")),
            )

    ordre = [c for c in CLASSES_EUNIS if c in par_classe]
    if CLASSE_INCONNUE in par_classe:
        ordre.append(CLASSE_INCONNUE)

    resultat, couleur_par_cle = [], {}
    for classe in ordre:
        habitats = par_classe[classe]
        # Tri par code EUNIS puis libellé : déterministe, et sans code (habitat
        # non rattaché) les entrées se rangent quand même toujours pareil.
        cles = sorted(habitats, key=lambda c: (habitats[c][1], habitats[c][0], c))
        couleurs = gamme(classe, len(cles))
        resultat.append((
            classe,
            libelle_classe(classe),
            [(cle, habitats[cle][0], couleur) for cle, couleur in zip(cles, couleurs)],
        ))
        couleur_par_cle.update(zip(cles, couleurs))

    # La couleur est reportée sur chaque entité : le rendu des habitats
    # secondaires la lit en attribut, ce qui évite une règle par habitat ET par
    # rang dans la mosaïque.
    for feature in features or []:
        props = _proprietes(feature)
        couleur = couleur_par_cle.get(props.get(CHAMP_CLE))
        if couleur:
            props[CHAMP_COULEUR] = couleur
    return resultat
