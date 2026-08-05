# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modèle de duplication d'une station locale (module pur, testable).

Dupliquer une station, c'est reprendre ses attributs métier **sans son
identité** : identifiants locaux et serveur, état de synchronisation, géométrie
et grandeurs qui en découlent.

Le point critique est l'identité serveur : un `id_habitat` (ou un uuid SINP)
laissé dans la copie ferait *mettre à jour* l'habitat de la station d'origine à
la synchronisation suivante, au lieu d'en créer un nouveau — la donnée d'origine
serait écrasée sans trace. D'où une liste de clés retirées explicite, testée.

Trois usages partagent ce modèle :

- **dupliquer** une station (nouvelle station, géométrie redessinée) ;
- **coller** les renseignements d'une station sur une (ou plusieurs) autre(s)
  déjà tracée(s) : mêmes clés, plus le nom, qui reste propre à chaque station ;
- **reprendre** l'habitat précédent dans le formulaire suivant, sans ce qui
  identifie ou mesure cet habitat-là (`habitat_reprise`).

Ce module ne dépend que de la bibliothèque standard.
"""
try:  # importable dans le paquet (plugin) comme en isolation (tests)
    from .eval_fields import merge_eval
except ImportError:  # pragma: no cover - repli hors paquet
    from eval_fields import merge_eval


# Identité locale, identité serveur et état de synchronisation : jamais copiés.
STATION_DROP = (
    "id", "id_station", "unique_id_sinp_station", "server_snapshot",
    "sync_status", "sync_date", "date_creation", "date_update",
    "prev_geom", "prev_geom_type",
    # L'état métier ne se copie pas : une station qu'on vient de créer est un
    # travail en cours, même si celle dont elle s'inspire était validée.
    "validation_status",
    # `mine` dit « créée par moi sur GeoNature », et commande le droit d'y
    # supprimer la station. Recopié d'une station récupérée du serveur et créée
    # par quelqu'un d'autre, il ferait passer pour non supprimable une station
    # que l'on vient soi-même de créer. Le défaut de la base (1) est le bon.
    "mine",
)
# Géométrie et valeurs qui en sont déduites : recalculées pour la nouvelle
# géométrie (une copie garderait la surface et l'altitude de l'original).
STATION_GEOM = ("geom", "geom_type", "area", "altitude_min", "altitude_max")
HABITAT_DROP = (
    "id", "id_habitat", "id_station_local", "unique_id_sinp_hab", "sync_status",
)
# Coller des renseignements sur une station DÉJÀ tracée : son nom lui reste
# propre (« Soula — pelouse haute » n'a pas de sens sur le polygone voisin),
# et sa géométrie n'est pas concernée — elle est déjà écartée par STATION_GEOM.
PASTE_DROP = ("station_name",)
# Reprise de l'habitat précédent dans le formulaire suivant : tout est repris
# SAUF ce qui identifie et mesure CET habitat-là. Le nom cité et le cd_hab sont
# précisément ce que l'on vient chercher dans HABREF à chaque nouvel habitat ;
# le recouvrement est une mesure propre au polygone décrit, et l'abondance en
# découle (elle est déduite du pourcentage saisi) — reprendre l'une sans l'autre
# donnerait une classe d'abondance qui ne correspond à rien. Les reprendre en
# silence produirait de la donnée fausse : pour recopier un habitat à
# l'identique, il y a « coller les renseignements ».
HABITAT_REPRISE_DROP = (
    "nom_cite", "cd_hab", "recovery_percentage", "id_nomenclature_abundance",
)


def station_template(station):
    """Copie d'une station prête à en créer une nouvelle.

    Args:
        station: dict tel que renvoyé par ``OccHabDatabase.get_station`` (avec
            ses clés ``habitats`` et ``observers``).

    Returns:
        dict des attributs métier (dates, JDD, nomenclatures, commentaire…),
        plus ``habitats`` et ``observers`` eux aussi débarrassés de leurs
        identifiants. Aucune clé de géométrie : l'appelant fournit la nouvelle.
    """
    source = station or {}
    skip = set(STATION_DROP) | set(STATION_GEOM) | {"habitats", "observers"}
    template = {k: v for k, v in source.items() if k not in skip}
    template["habitats"] = [
        {k: v for k, v in habitat.items() if k not in HABITAT_DROP}
        for habitat in source.get("habitats") or []
    ]
    template["observers"] = [
        {"id_role": obs.get("id_role"), "observer_name": obs.get("observer_name")}
        for obs in source.get("observers") or []
        if obs.get("id_role")
    ]
    return template


def paste_fields(template):
    """Colonnes de station à écrire sur une station EXISTANTE.

    Args:
        template: sortie de ``station_template`` (ou dict équivalent).

    Returns:
        dict des seuls attributs métier : ni habitats, ni observateurs (écrits
        à part, table par table), ni nom — chaque station garde le sien.
    """
    skip = set(PASTE_DROP) | {"habitats", "observers"}
    return {k: v for k, v in (template or {}).items() if k not in skip}


def habitat_reprise(habitat):
    """Habitat prêt à pré-remplir le formulaire du SUIVANT.

    Args:
        habitat: dict d'habitat (tel qu'enregistré, ou tel que rendu par le
            formulaire).

    Returns:
        dict sans identifiants, sans nom cité / cd_hab / recouvrement /
        abondance — y compris le recouvrement encodé dans
        ``technical_precision``, qui réapparaîtrait sinon dans le champ du
        formulaire suivant.
    """
    skip = set(HABITAT_DROP) | set(HABITAT_REPRISE_DROP)
    reprise = {k: v for k, v in (habitat or {}).items() if k not in skip}
    precision = reprise.get("technical_precision")
    if precision:
        reprise["technical_precision"] = merge_eval(precision, recouvrement=None) or None
    return reprise
