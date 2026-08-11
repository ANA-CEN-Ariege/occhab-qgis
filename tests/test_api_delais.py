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
    """L'export est bâti sur `v_occhab_complet` : la demi-minute ne suffit pas."""
    client = _client()
    client.get_export_page(9, offset=0)
    assert client.session.dernier["timeout"] == gc.DELAI_LONG


def test_le_delai_long_reste_supportable_pour_l_interface():
    """L'appel a lieu dans le fil de l'interface : le délai EST la durée du gel.

    L'allonger ne sert d'ailleurs à rien — un reverse-proxy rend un 502 bien
    avant. Deux minutes est un plafond, pas une cible.
    """
    assert gc.DELAI_LONG <= 120


def test_les_pages_d_export_sont_courtes():
    """Une page de 1000 entités sur cette vue déclenche un 502 côté proxy."""
    assert gc.TAILLE_PAGE_EXPORT <= 250
    client = _client()
    client.get_export_page(9)
    assert client.session.dernier["params"]["limit"] == gc.TAILLE_PAGE_EXPORT


def test_une_erreur_de_proxy_est_traduite():
    """Le corps d'un 502 est une page HTML : l'afficher tel quel fait croire à un
    défaut de l'extension, et ne dit pas quoi faire."""
    class _Proxy:
        status_code = 502
        text = "<!DOCTYPE HTML><html><title>502 Proxy Error</title>"

        @staticmethod
        def json():
            raise ValueError

    detail = gc._error_detail(_Proxy())
    assert "serveur intermédiaire" in detail
    assert "<" not in detail


def test_une_page_html_inattendue_n_est_pas_recopiee():
    class _Html:
        status_code = 500
        text = "<html><body>Internal Server Error</body></html>"

        @staticmethod
        def json():
            raise ValueError

    assert "<" not in gc._error_detail(_Html())


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
