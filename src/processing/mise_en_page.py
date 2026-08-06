# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Réglages d'une planche cartographique (module pur, testable sans QGIS).

La géométrie de la planche vient des **gabarits maison** de l'ANA (`.qpt`), dont
le bandeau, le logo, l'adresse et les mentions sont déjà à leur place. Ce module
ne s'occupe que de ce que le gabarit ne peut pas savoir d'avance.

Il ne calcule PAS l'encombrement de la légende. On a essayé : compter les
caractères et les multiplier par un corps de texte donne un résultat plausible et
faux, parce que la hauteur d'une entrée dépend du symbole, des marges de groupe
et du rendu de la police. C'est QGIS qui mesure (`print_layout._essayer`), en
appliquant chaque combinaison et en lisant la taille obtenue. Ne restent ici que
les deux calculs qu'aucune mesure ne donne : la place libre autour d'un cadre, et
le corps d'un bloc de mentions converti depuis du HTML.
"""

#: Corps de texte de la légende, en points, du plus confortable au plus serré.
#: En deçà de 5 pt un nom de syntaxon n'est plus lisible à l'impression : mieux
#: vaut alors passer en colonnes que descendre davantage. Les combinaisons sont
#: ESSAYÉES, pas estimées — c'est QGIS qui mesure (cf. `print_layout._essayer`).
TAILLES = (9.0, 8.0, 7.0, 6.5, 6.0, 5.5, 5.0)
#: Colonnes envisagées pour une légende en pleine page, de la plus lisible à la
#: plus dense. Au-delà de cinq, une colonne devient plus étroite qu'un nom de
#: syntaxon.
COLONNES = (1, 2, 3, 4, 5)
#: Hauteur d'une ligne rapportée au corps du texte, pour les blocs de mentions.
INTERLIGNE = 1.45
#: Un point vaut 0,3528 mm.
MM_PAR_POINT = 25.4 / 72.0


#: Marge gardée libre autour du cadre de légende, en millimètres.
GOUTTIERE = 3.0


def espace_libre(cadre, voisins, page):
    """(largeur, hauteur) réellement disponibles pour un cadre, en millimètres.

    Le cadre de légende d'un gabarit ne mesure que quelques millimètres : il
    **grandit à son contenu**. Sa taille déclarée ne dit donc rien de la place
    dont il dispose, et s'y fier reviendrait à réduire le texte à 5 pt pour tenir
    dans 8 mm de haut alors que la colonne en offre 130.

    On regarde donc jusqu'où il peut s'étendre avant de buter sur un voisin —
    vers la droite, puis vers le bas — ou sur le bord de la page. Les cadres qui
    l'ENGLOBENT (fond de page, carte pleine page) ne le bornent pas : ils sont
    sous lui, pas devant.

    `cadre` et chaque voisin : (x, y, largeur, hauteur). `page` : (largeur, hauteur).
    """
    x, y, largeur, hauteur = cadre
    largeur_page, hauteur_page = page
    droite, bas = largeur_page, hauteur_page
    for vx, vy, vl, vh in voisins or []:
        if vx <= x and vy <= y and vx + vl >= x + largeur and vy + vh >= y + hauteur:
            continue  # cadre englobant : c'est un fond, pas une butée
        if vx < x + largeur and vx + vl > x and vy >= y + hauteur:
            bas = min(bas, vy)
        if vy < y + hauteur and vy + vh > y and vx >= x + largeur:
            droite = min(droite, vx)
    return (max(0.0, droite - x - GOUTTIERE), max(0.0, bas - y - GOUTTIERE))


#: Tailles admissibles pour un bloc de mentions converti, du confortable au ras.
#: Le plancher descend plus bas que pour la légende : ce sont des mentions
#: légales en petits caractères, et le cadre que le gabarit leur réserve est
#: parfois plus petit que leur contenu. Mieux vaut une adresse minuscule mais
#: entière qu'une adresse à cheval sur le bandeau de pied.
TAILLES_MENTION = (9.0, 8.0, 7.0, 6.5, 6.0, 5.5, 5.0, 4.5, 4.0, 3.5, 3.0)
#: Part de la hauteur du cadre qu'on s'autorise. L'estimation par comptage de
#: caractères sous-évalue le gras et les longs mots ; viser le ras du cadre
#: laisse les dernières lignes passer par-dessus le voisin — sur le bandeau de
#: pied, pour l'adresse.
MARGE_MENTION = 0.85
#: Largeur d'un caractère pour ces blocs : plus large que pour la légende, car
#: les mentions sont en gras sur la moitié de leurs lignes.
LARGEUR_CARACTERE_MENTION = 0.62


def texte_nu(html):
    """Texte visible d'un fragment HTML, sauts de ligne conservés.

    Approximation volontaire : on ne cherche pas à rendre le HTML, seulement à
    mesurer combien de place il prendra. `<br>` et `</p>` valent un saut, les
    autres balises ne pèsent rien.
    """
    import re

    texte = re.sub(r"<\s*br\s*/?\s*>", "\n", html or "", flags=re.IGNORECASE)
    texte = re.sub(r"</\s*(p|div|li|tr)\s*>", "\n", texte, flags=re.IGNORECASE)
    texte = re.sub(r"<[^>]*>", "", texte)
    return texte


def taille_pour_bloc(html, largeur_mm, hauteur_mm):
    """Corps de texte pour qu'un bloc de mentions tienne dans son cadre.

    Une étiquette de mise en page **ne réduit pas** son texte : elle le laisse
    déborder sur ses voisins. Un bloc d'adresse converti depuis un cadre HTML,
    dont la feuille de style disait 6 pt, s'afficherait à la taille par défaut —
    trois fois trop gros, à cheval sur le pied de page.
    """
    lignes_texte = [l for l in texte_nu(html).split("\n")]
    if not any(l.strip() for l in lignes_texte) or largeur_mm <= 0 or hauteur_mm <= 0:
        return TAILLES_MENTION[0]

    for taille in TAILLES_MENTION:
        par_ligne = max(1, int(largeur_mm
                               / (taille * LARGEUR_CARACTERE_MENTION
                                  * MM_PAR_POINT)))
        total = sum(max(1, -(-len(ligne) // par_ligne)) for ligne in lignes_texte)
        if total * taille * INTERLIGNE * MM_PAR_POINT <= hauteur_mm * MARGE_MENTION:
            return taille
    return TAILLES_MENTION[-1]

