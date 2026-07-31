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

Ce module ne dépend que de la bibliothèque standard.
"""

# Identité locale, identité serveur et état de synchronisation : jamais copiés.
STATION_DROP = (
    "id", "id_station", "unique_id_sinp_station", "server_snapshot",
    "sync_status", "sync_date", "date_creation", "date_update",
    "prev_geom", "prev_geom_type",
    # L'état métier ne se copie pas : une station qu'on vient de créer est un
    # travail en cours, même si celle dont elle s'inspire était validée.
    "validation_status",
)
# Géométrie et valeurs qui en sont déduites : recalculées pour la nouvelle
# géométrie (une copie garderait la surface et l'altitude de l'original).
STATION_GEOM = ("geom", "geom_type", "area", "altitude_min", "altitude_max")
HABITAT_DROP = (
    "id", "id_habitat", "id_station_local", "unique_id_sinp_hab", "sync_status",
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
