# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Plantes exotiques envahissantes : lecture et couleurs (module pur, testable).

La vue d'export restitue les taxons d'un habitat en une chaîne « a, b, c »
(`habitat_pee`, trois au plus). Une carte des PEE demande l'inverse : la liste
des espèces rencontrées sur tout un jeu de données, et **une couleur par
espèce**, stable d'un chargement à l'autre pour que deux cartes du même secteur
se comparent.

Rien à voir avec la palette des habitats, qui décline les nuances d'un grand
milieu : ici les espèces n'ont aucune parenté à montrer, il faut au contraire
qu'elles se distinguent le plus possible les unes des autres.
"""
import colorsys

#: Séparateur des taxons dans `habitat_pee`, tel que la vue les assemble.
SEPARATEUR = ","
#: Nombre d'or en tours : deux couleurs consécutives sont aussi éloignées que
#: possible sur le cercle des teintes, et le restent quel qu'en soit le nombre.
#: Un pas régulier (360/n) obligerait à recalculer toutes les couleurs dès qu'une
#: espèce s'ajoute ; ici les précédentes ne bougent pas.
_PAS_TEINTE = 0.618033988749895
#: Départ à l'orangé-rouge : la première espèce, souvent la plus fréquente,
#: ressort sur les verts et les gris d'une carte d'habitats.
_TEINTE_INITIALE = 0.03
#: Clarté et saturation alternées : deux teintes voisines se distinguent alors
#: même chez une personne daltonienne, qui ne les sépare pas par la teinte seule.
_CLARTES = (0.45, 0.62, 0.35)
_SATURATIONS = (0.85, 0.60)


def especes(valeur):
    """Taxons d'une chaîne « a, b, c », nettoyés, sans doublon, dans l'ordre."""
    if not isinstance(valeur, str):
        return []
    vus, retenus = set(), []
    for morceau in valeur.split(SEPARATEUR):
        nom = " ".join(morceau.split())
        if nom and nom.casefold() not in vus:
            vus.add(nom.casefold())
            retenus.append(nom)
    return retenus


def inventaire(features, colonne="habitat_pee"):
    """Espèces rencontrées dans ces entités, triées par nom.

    Triées, et non par ordre d'apparition : la couleur d'une espèce ne doit pas
    dépendre de l'ordre dans lequel le serveur a rendu les lignes, sinon deux
    chargements du même export donnent deux cartes différentes.
    """
    trouvees = {}
    for feature in features or []:
        proprietes = (feature or {}).get("properties") or {}
        for nom in especes(proprietes.get(colonne)):
            trouvees.setdefault(nom.casefold(), nom)
    return [trouvees[cle] for cle in sorted(trouvees)]


def couleur(rang):
    """Couleur du rang donné (0, 1, 2…) dans la palette des espèces."""
    teinte = (_TEINTE_INITIALE + rang * _PAS_TEINTE) % 1.0
    clarte = _CLARTES[rang % len(_CLARTES)]
    saturation = _SATURATIONS[(rang // len(_CLARTES)) % len(_SATURATIONS)]
    rvb = colorsys.hls_to_rgb(teinte, clarte, saturation)
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in rvb)


def palette(features, colonne="habitat_pee"):
    """[(espèce, couleur)] pour tout ce qui est présent, dans l'ordre des noms."""
    return [(nom, couleur(rang))
            for rang, nom in enumerate(inventaire(features, colonne))]


def repartir(especes_station, points):
    """{espèce: [points]} en alternant, pour que les couleurs se mêlent.

    Alterner plutôt que découper en blocs : trois espèces réparties par tiers
    dessineraient trois taches contiguës, qu'on lirait comme une localisation à
    l'intérieur de la station. Or la donnée ne dit pas où chaque espèce se
    trouve — seulement qu'elle est là.
    """
    if not especes_station or not points:
        return {}
    parts = {nom: [] for nom in especes_station}
    for rang, point in enumerate(points):
        parts[especes_station[rang % len(especes_station)]].append(point)
    return {nom: liste for nom, liste in parts.items() if liste}
