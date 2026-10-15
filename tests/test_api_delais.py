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
    assert client.session.dernier["timeout"] == (gc.DELAI_CONNEXION, gc.DELAI_MAX)


def test_une_page_d_export_prend_le_delai_long():
    """L'export est bâti sur `v_occhab_complet` : la demi-minute ne suffit pas."""
    client = _client()
    client.get_export_page(9, offset=0)
    assert client.session.dernier["timeout"] == (gc.DELAI_CONNEXION, gc.DELAI_LONG)


def test_le_delai_long_reste_supportable_pour_l_interface():
    """L'appel a lieu dans le fil de l'interface : le délai EST la durée du gel.

    L'allonger ne sert d'ailleurs à rien — un reverse-proxy rend un 502 bien
    avant. Deux minutes est un plafond, pas une cible.
    """
    assert gc.DELAI_LONG <= 120


def test_les_pages_d_export_sont_grandes():
    """Le coût d'une requête d'export est FIXE, mesuré : 5 ou 250 entités, 9 s.

    Réduire la taille de page ne fait donc que multiplier les allers-retours —
    et chacun gèle l'interface, le chargement étant synchrone. La tentative à
    250 avait quadruplé le temps total sans rien résoudre.
    """
    assert gc.TAILLE_PAGE_EXPORT >= 1000
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
    assert client.session.dernier["timeout"] == (gc.DELAI_CONNEXION, gc.DELAI_LONG)


def test_la_creation_d_une_station_prend_le_delai_long():
    """Une création qui dépasse le délai a souvent abouti côté serveur : la
    renvoyer ensuite créait un doublon."""
    client = _client()
    client.create_station({"type": "Feature"})
    assert client.session.dernier["timeout"] == (gc.DELAI_CONNEXION, gc.DELAI_LONG)


def test_aucune_requete_ne_part_sans_delai():
    """Le défaut du transport doit être un délai, jamais l'attente infinie."""
    client = _client()
    for appel in (lambda: client.get_datasets(),
                  lambda: client.get_habref_typologies(),
                  lambda: client.list_exports()):
        client.session.dernier = {}
        appel()
        assert client.session.dernier.get("timeout"), "requête sans délai"


def test_la_mise_a_jour_d_une_station_prend_le_delai_long():
    """Appliquée mais confirmée après 30 s, une mise à jour restait « à
    synchroniser » et revenait en faux conflit à la synchro suivante."""
    client = _client()
    client.update_station(42, {"type": "Feature"})
    assert client.session.dernier["timeout"] == (gc.DELAI_CONNEXION, gc.DELAI_LONG)


def test_un_serveur_injoignable_echoue_vite():
    """Établir la connexion a son propre délai, court : sur un réseau muet,
    chaque appel attendait 30 s et QGIS restait figé des minutes."""
    assert gc.DELAI_CONNEXION <= 5 < gc.DELAI_MAX


class _SessionExpiree(_SessionEspionne):
    """Répond 401 tant que `login` n'a pas rouvert la session."""

    def __init__(self):
        super().__init__()
        self.ouverte = False
        self.appels = []

    def request(self, method, url, **kwargs):
        self.appels.append(url.rsplit("/api/", 1)[1])
        reponse = _Reponse()
        if not self.ouverte:
            reponse = type("R401", (), {"status_code": 401, "text": "",
                                        "json": staticmethod(lambda: {})})()
        return reponse


def test_une_session_expiree_est_rouverte_puis_la_requete_rejouee():
    client = _client()
    client.session = _SessionExpiree()

    def reconnexion():
        client.session.ouverte = True
        return True

    client.reconnexion = reconnexion
    assert client.get_station(42) == []
    assert client.session.appels == ["occhab/stations/42/", "occhab/stations/42/"]


def test_sans_reconnexion_possible_le_401_remonte_et_la_session_est_oubliee():
    client = _client()
    client.session = _SessionExpiree()
    client.user = {"id_role": 1}
    client.reconnexion = lambda: False
    try:
        client.get_station(42)
    except gc.GeoNatureAPIError as exc:
        assert exc.status_code == 401
    else:  # pragma: no cover
        raise AssertionError("le 401 doit remonter")
    assert client.user is None and not client.is_authenticated


def test_une_reponse_perdue_peut_avoir_abouti():
    """Requête partie, réponse jamais arrivée : le serveur a pu l'appliquer."""
    import requests

    class _Muette(_SessionEspionne):
        def __init__(self, exc):
            super().__init__()
            self.exc = exc

        def request(self, method, url, **kwargs):
            raise self.exc

    client = _client()
    for exc, attendu in ((requests.exceptions.ReadTimeout("lent"), True),
                         (requests.exceptions.ConnectTimeout("muet"), False),
                         (requests.exceptions.ConnectionError("coupé"), False)):
        client.session = _Muette(exc)
        try:
            client.update_station(42, {})
        except gc.GeoNatureAPIError as erreur:
            assert erreur.reseau and erreur.peut_avoir_abouti is attendu


class _ServeurPlafonne(_SessionEspionne):
    """Rend des pages de 500 au plus, quelle que soit la taille demandée
    (`max_page_size_api`), sur 1 200 lignes."""

    def request(self, method, url, **kwargs):
        page = kwargs["params"]["offset"]
        debut = page * 500
        lot = [{"type": "Feature", "geometry": None, "properties": {"n": n}}
               for n in range(debut, min(debut + 500, 1200))]
        corps = {"total": 1200, "total_filtered": 1200, "limit": 500,
                 "items": {"type": "FeatureCollection", "features": lot}}
        return type("R", (), {"status_code": 200, "text": "x",
                              "json": staticmethod(lambda: corps)})()


def test_un_export_plafonne_par_l_instance_est_lu_jusqu_au_bout():
    """Une page pleine à 500 passait pour la dernière (1 000 demandées) : 500
    lignes sur 1 200, sans un mot."""
    client = _client()
    client.session = _ServeurPlafonne()
    features, total_filtre, _total = client.iter_export_features(9)
    assert total_filtre == 1200 and len(features) == 1200
