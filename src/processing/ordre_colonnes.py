# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remettre les colonnes du gabarit dans l'ordre du gabarit.

Le module Exports de GeoNature rend les propriétés d'une entité **par ordre
alphabétique**, quel que soit l'ordre des colonnes de la vue. Vérifié : ni QGIS
ni le pilote OGR n'y sont pour rien — ils relisent un GeoJSON dans l'ordre où
il est écrit — et le plugin ne trie rien non plus. C'est la sérialisation du
serveur qui perd l'ordre en route.

Ça n'a aucune importance pour cartographier. Ça en a pour **livrer** : un
gabarit imposé se lit colonne après colonne, et `CodeCB_1` entre `Comment` et
`CodeEUNIS_1` donne un fichier que le destinataire ne reconnaît pas comme le
sien. L'ordre étant connu et stable — c'est le gabarit lui-même —, il se
rétablit ici, avant l'écriture du GeoJSON.

Rien n'est jamais SUPPRIMÉ : une colonne inattendue passe en queue, dans son
ordre d'arrivée. Un gabarit qui gagnerait une colonne côté serveur la verrait
mal placée, jamais perdue.
"""

#: En-tête du gabarit, dans l'ordre. `fid` d'abord : c'est la clé primaire
#: déclarée dans l'admin GeoNature, et une clé se lit en première colonne.
TETE = ("fid", "Date_hab", "Observateur", "Description", "Nb_Habitat")

#: Le bloc répété à chaque rang de la mosaïque, dans l'ordre du gabarit. Ce sont
#: les préfixes : les colonnes réelles portent le rang en suffixe
#: (`Syntaxon_1`, `CodeEUNIS_1`… puis `Syntaxon_2`…).
BLOC = ("Syntaxon", "CodeEUNIS", "NomEUNIS", "CodeCB", "NomCB",
        "CodeN2000", "NomN2000", "Rec")

#: Ce qui suit les blocs, dans l'ordre.
QUEUE = ("EtatConser", "Enjeu", "Comment", "Source", "Ref_Biblio",
         "SHAPE_Leng", "SHAPE_Area")

#: Colonnes techniques de la vue (filtres de l'API), hors gabarit : en dernier,
#: là où elles se décochent d'un geste au moment de livrer.
TECHNIQUES = ("id_dataset", "date_min", "date_max")

#: Sections, dans l'ordre. L'indice de la section est le premier terme de la
#: clé de tri.
_SECTIONS = (TETE, QUEUE, TECHNIQUES)


def _rang(nom):
    """Clé de tri d'une colonne : (section, rang de bloc, position).

    Les colonnes hors gabarit tombent toutes sur la même clé, la plus grande :
    le tri étant stable, elles conservent entre elles l'ordre d'arrivée.
    """
    if nom in TETE:
        return (0, 0, TETE.index(nom))
    prefixe, _, suffixe = nom.rpartition("_")
    if prefixe in BLOC and suffixe.isdigit():
        # Le rang d'abord, la colonne ensuite : tout le bloc 2 suit tout le
        # bloc 1, et non toutes les colonnes « Syntaxon » à la file.
        return (1, int(suffixe), BLOC.index(prefixe))
    for indice, section in ((2, QUEUE), (3, TECHNIQUES)):
        if nom in section:
            return (indice, 0, section.index(nom))
    return (4, 0, 0)


def est_gabarit(proprietes):
    """Ces propriétés ressemblent-elles au gabarit à colonnes plates ?

    Le premier bloc de mosaïque suffit à le reconnaître, et rien d'autre ne le
    porte. La garde importe : réordonner une vue dont l'ordre est déjà bon ne
    ferait aucun mal, mais réordonner une vue INCONNUE en poserait un — ses
    colonnes se retrouveraient toutes en queue, dans un ordre arbitraire.
    """
    return "Syntaxon_1" in (proprietes or {})


def ordonner_proprietes(proprietes):
    """Mêmes couples clé/valeur, remis dans l'ordre du gabarit."""
    proprietes = proprietes or {}
    if not est_gabarit(proprietes):
        return proprietes
    return {nom: proprietes[nom] for nom in sorted(proprietes, key=_rang)}


def ordonner(features):
    """Réordonner les propriétés de chaque entité GeoJSON (mute et renvoie).

    Un dict Python garde son ordre d'insertion et `json.dump` l'écrit tel quel ;
    OGR, lui, relit les champs dans l'ordre du fichier. Réordonner le dict
    suffit donc à ce que la couche QGIS porte les colonnes dans le bon ordre.
    """
    for feature in features or []:
        if not isinstance(feature, dict):
            continue
        proprietes = feature.get("properties")
        if isinstance(proprietes, dict) and est_gabarit(proprietes):
            feature["properties"] = ordonner_proprietes(proprietes)
    return features
