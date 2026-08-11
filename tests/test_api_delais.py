# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Délais des requêtes vers l'API GeoNature.

Deux fautes symétriques, toutes deux vues en production :

- **aucun délai** — `requests` attend sans fin par défaut, et ces appels ont lieu
  dans le fil de l'interface : un serveur qui n'achève pas sa réponse fige QGIS
  pour de bon, sans message ;
- **un délai unique, court** — appliqué aux routes lourdes, il faisait échouer un
  chargement d'export qui n'avait besoin que de patienter (« Read timed out »
  alors que rien n'était cassé).

D'où deux délais, et ce test pour que la distinction ne se perde pas : ce sont
des valeurs qu'on ne voit jamais à l'œuvre tant que le réseau va bien.

Aucun accès réseau : la session HTTP est remplacée par un espion.
"""
import geonature_client as gc


class _Reponse:
    status_code = 200
    text = "[]"

    @staticmethod
    def json():
        return []


class _SessionEspionne:
    """Retient les paramètres du dernier appel, sans rien émettre."""

    def __init__(self):
        self.headers = {}
        self.cookies = {}
        self.dernier = {}

    def request(self, method, url, **kwargs):
        self.dernier = dict(kwargs, method=method, url=url)
        return _Reponse()


def _client():
    client = gc.GeoNatureAPIClient("https://exemple.test/geonature/api")
    client.session = _SessionEspionne()
    return client


def test_les_deux_delais_sont_distincts():
    """Un seul délai ne peut pas convenir aux deux usages."""
    assert gc.DELAI_MAX < gc.DELAI_LONG


def test_une_requete_interactive_prend_le_delai_court():
    """L'autocomplétion doit rendre la main vite : au-delà, l'utilisateur croit
    que l'extension a planté."""
    client = _client()
    client.search_habref("nitellion")
    assert client.session.dernier["timeout"] == gc.DELAI_MAX


def test_une_page_d_export_prend_le_delai_long():
    """L'export est bâti sur `v_occhab_complet` : jointures HABREF et
    correspondances, 1000 entités par page. La demi-minute ne suffit pas."""
    client = _client()
    client.get_export_page(9, limit=1000, offset=0)
    assert client.session.dernier["timeout"] == gc.DELAI_LONG


def test_les_stations_du_serveur_prennent_le_delai_long():
    """La route peut rendre un jeu de données entier, géométries comprises."""
    client = _client()
    client.get_stations()
    assert client.session.dernier["timeout"] == gc.DELAI_LONG


def test_aucune_requete_ne_part_sans_delai():
    """Le défaut du transport doit être un délai, jamais l'attente infinie."""
    client = _client()
    for appel in (lambda: client.get_datasets(),
                  lambda: client.get_habref_typologies(),
                  lambda: client.list_exports()):
        client.session.dernier = {}
        appel()
        assert client.session.dernier.get("timeout"), "requête sans délai"
