# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Client de l'API REST GeoNature (module OccHab).

API station-centrée : les habitats et observateurs sont imbriqués dans la
station. L'update d'une station se fait en POST (et non PUT).

NB : `requests` n'est pas toujours présent dans le Python de QGIS. Ce module
n'est donc importé que lorsque la synchronisation est réellement utilisée
(import différé côté appelant).
"""
import requests


class GeoNatureAPIError(Exception):
    """Erreur renvoyée par l'API GeoNature."""


def _error_detail(response):
    """Extraire un message lisible du corps d'une réponse d'erreur."""
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "").strip()[:300] or "réponse vide"
    if isinstance(payload, dict):
        for key in ("msg", "message", "description", "detail", "error"):
            if payload.get(key):
                return str(payload[key])
    return str(payload)[:300]


class GeoNatureAPIClient:
    """Client minimal pour l'API OccHab de GeoNature."""

    def __init__(self, api_url, token=None, verify_ssl=True):
        # api_url = base de l'API GeoNature, ex. 'https://serveur/geonature/api'
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        # NE PAS fixer Content-Type globalement : un GET sans corps mais avec
        # Content-Type: application/json fait échouer request.get_json() côté
        # Flask (400 Bad Request). requests pose lui-même le bon Content-Type
        # quand un corps est envoyé via json=.
        self.session.headers.update({"Accept": "application/json"})
        self.user = None
        if token:
            self.session.headers.update({"Authorization": "Bearer %s" % token})

    # --------------------------------------------------------------- auth
    def login(self, login, password, id_application=3):
        """S'authentifier auprès de GeoNature.

        GeoNature pose un cookie de session `token` conservé par la session
        `requests`. `id_application` dépend de l'instance (souvent 3 pour
        l'application GEONATURE).
        """
        body = {"login": login, "password": password}
        if id_application:  # optionnel : le serveur déduit l'application par défaut
            body["id_application"] = id_application
        data = self._make_request("POST", "auth/login", data=body)
        if isinstance(data, dict):
            self.user = data.get("user", data)
        return data

    @property
    def is_authenticated(self):
        return self.user is not None or bool(self.session.cookies)

    def _make_request(self, method, endpoint, data=None, params=None):
        """Requête HTTP. `endpoint` est RELATIF à api_url (ex. 'occhab/stations/').

        Concaténation manuelle : urljoin() écraserait le sous-chemin de api_url
        dès que endpoint commence par '/'.
        """
        url = "%s/%s" % (self.api_url, endpoint.lstrip("/"))
        try:
            response = self.session.request(
                method, url, json=data, params=params, verify=self.verify_ssl
            )
        except requests.exceptions.RequestException as exc:
            raise GeoNatureAPIError("Connexion impossible : %s" % exc)

        if response.status_code >= 400:
            raise GeoNatureAPIError(
                "HTTP %s — %s" % (response.status_code, _error_detail(response))
            )
        if not response.text:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # ------------------------------------------------------------ stations
    def get_stations(self, params=None, geojson=False):
        params = dict(params or {})
        if geojson:
            params["format"] = "geojson"
        return self._make_request("GET", "occhab/stations/", params=params)

    def get_station(self, id_station):
        return self._make_request("GET", "occhab/stations/%s/" % id_station)

    def create_station(self, data):
        """Créer une station + ses habitats + observateurs (payload imbriqué)."""
        return self._make_request("POST", "occhab/stations/", data=data)

    def update_station(self, id_station, data):
        """Mettre à jour une station (⚠ POST, pas PUT)."""
        return self._make_request("POST", "occhab/stations/%s/" % id_station, data=data)

    def delete_station(self, id_station):
        return self._make_request("DELETE", "occhab/stations/%s/" % id_station)

    def export_stations(self, export_format, data=None):
        return self._make_request(
            "POST", "occhab/export_stations/%s" % export_format, data=data
        )

    # ---------------------------------------------- nomenclatures & référentiels
    def get_default_nomenclatures(self, params=None):
        return self._make_request("GET", "occhab/defaultNomenclatures", params=params)

    def get_nomenclature_values(self, code_type):
        """Valeurs actives d'un type de nomenclature (par mnémonique).

        GET /nomenclatures/nomenclature/<code_type> → objet avec une liste 'values'.
        """
        data = self._make_request("GET", "nomenclatures/nomenclature/%s" % code_type)
        if isinstance(data, dict):
            return data.get("values", [])
        return data if isinstance(data, list) else []

    def get_datasets(self, params=None):
        return self._make_request("GET", "meta/datasets", params=params)

    def search_habref(self, search_name, cd_typo=None, limit=20):
        """Autocomplétion HABREF (recherche d'habitat par nom ou code)."""
        params = {"search_name": search_name, "limit": limit}
        if cd_typo:
            params["cd_typo"] = cd_typo
        result = self._make_request("GET", "habref/habitats/autocomplete", params=params)
        return result if isinstance(result, list) else []

    def get_habref(self, cd_hab):
        """Détail HABREF d'un habitat par cd_hab (GET habref/habitat/<cd_hab>).

        Renvoie le dict de l'habitat (`lb_hab_fr`, `lb_hab_fr_complet`, `lb_code`…).
        Un cd_hab inexistant fait renvoyer une erreur par l'API → GeoNatureAPIError.
        """
        return self._make_request("GET", "habref/habitat/%s" % int(cd_hab))

    def get_habref_typologies(self, params=None):
        """Typologies HABREF (/habref/typo) : cd_typo + lb_nom_typo (Corine, EUNIS…)."""
        result = self._make_request("GET", "habref/typo", params=params)
        return result if isinstance(result, list) else []

    def get_observers(self, id_menu):
        """Utilisateurs d'une liste d'observateurs (/users/menu/<id_menu>)."""
        result = self._make_request("GET", "users/menu/%s" % id_menu)
        return result if isinstance(result, list) else []

    def get_altitude(self, geom_geojson):
        """Altitude min/max d'une géométrie via le MNT serveur (POST /geo/altitude).

        Retourne {'altitude_min': …, 'altitude_max': …}.
        """
        return self._make_request("POST", "geo/altitude", data={"geometry": geom_geojson})

    def test_connection(self):
        """Ping léger pour vérifier connexion/authentification."""
        try:
            self._make_request("GET", "occhab/stations/", params={"limit": 1})
            return True
        except GeoNatureAPIError:
            return False
