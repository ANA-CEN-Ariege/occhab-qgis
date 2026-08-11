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


#: Limite de temps des requêtes INTERACTIVES (autocomplétion, nomenclatures,
#: fiche d'un habitat), en secondes. Sans limite, une connexion suspendue
#: (portail captif, serveur qui n'achève pas sa réponse) fige QGIS indéfiniment :
#: `requests` attend sans fin par défaut, et ces appels ont lieu dans le fil de
#: l'interface. 30 s y est confortable — au-delà, l'utilisateur croit déjà que
#: l'extension a planté.
DELAI_MAX = 30
#: Limite des requêtes LOURDES (export, liste des stations du serveur). Plus
#: généreuse que l'interactive, mais PAS de plusieurs minutes : ces appels ont
#: lieu dans le fil de l'interface, donc le délai est aussi la durée pendant
#: laquelle QGIS reste figé. Et l'allonger ne sert de toute façon à rien — un
#: reverse-proxy coupe avant (502) : ce qui n'a pas répondu en deux minutes ne
#: répondra pas. La vraie réponse à un export trop lent est de le demander par
#: plus petits morceaux (cf. `TAILLE_PAGE_EXPORT`) et de matérialiser les
#: correspondances côté serveur (README §5), pas d'attendre plus longtemps.
DELAI_LONG = 120

#: Entités demandées par page d'export. MESURÉ sur le serveur de l'ANA : une
#: page de 5 entités et une page de 250 coûtent le MÊME temps, environ 9
#: secondes. Le coût est donc fixe par requête — construction de l'export,
#: comptage, sérialisation — et non proportionnel au nombre de lignes.
#:
#: Il faut par conséquent des pages GRANDES, pas petites : réduire la taille ne
#: fait que multiplier les allers-retours à 9 secondes, et comme le chargement
#: est synchrone dans le fil de l'interface, chacun est autant de gel de QGIS.
#: Une tentative à 250 avait quadruplé le temps total sans rien résoudre.
TAILLE_PAGE_EXPORT = 1000


class GeoNatureAPIError(Exception):
    """Erreur renvoyée par l'API GeoNature.

    `status_code` porte le code HTTP quand la requête a abouti (None pour une
    erreur réseau) : l'appelant peut ainsi distinguer un 404 (ressource absente
    du serveur) d'une simple panne de connexion.
    """

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


#: Codes rendus par un reverse-proxy quand c'est LUI qui abandonne, et non
#: GeoNature : le corps est alors une page HTML, illisible dans une boîte de
#: dialogue, et surtout trompeuse — elle laisse croire à un défaut de l'extension
#: alors que la requête est simplement trop lourde pour le serveur.
_CODES_PROXY = {502: "réponse invalide", 504: "délai dépassé"}


def _error_detail(response):
    """Extraire un message lisible du corps d'une réponse d'erreur."""
    if response.status_code in _CODES_PROXY:
        return (
            "le serveur intermédiaire a abandonné (%s). La requête est trop "
            "lourde ou trop longue pour lui : réduisez la période ou le jeu de "
            "données demandé. Côté serveur, matérialiser les correspondances "
            "(README §5) est ce qui change le plus."
            % _CODES_PROXY[response.status_code]
        )
    try:
        payload = response.json()
    except ValueError:
        texte = (response.text or "").strip()
        if texte[:200].lstrip().lower().startswith(("<!doctype", "<html")):
            return "réponse HTML du serveur, pas une erreur GeoNature"
        return texte[:300] or "réponse vide"
    if isinstance(payload, dict):
        for key in ("msg", "message", "description", "detail", "error"):
            if payload.get(key):
                return str(payload[key])
    return str(payload)[:300]


def _export_features(items):
    """Normaliser le contenu d'une page d'export en liste.

    La route rend une **FeatureCollection** quand l'export porte une géométrie,
    et une simple liste sinon (`as_geofeature()` vs `return_query()` côté
    GeoNature). Les appelants n'ont pas à connaître cette bascule.
    """
    if isinstance(items, dict):
        return items.get("features") or []
    return items if isinstance(items, list) else []


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

    def _make_request(self, method, endpoint, data=None, params=None,
                      timeout=DELAI_MAX):
        """Requête HTTP. `endpoint` est RELATIF à api_url (ex. 'occhab/stations/').

        Concaténation manuelle : urljoin() écraserait le sous-chemin de api_url
        dès que endpoint commence par '/'.

        `timeout` vaut le délai interactif par défaut : c'est le cas de la
        plupart des routes. Les appels lourds passent `DELAI_LONG` — le choix est
        fait par l'appelant, qui sait ce qu'il demande au serveur.
        """
        url = "%s/%s" % (self.api_url, endpoint.lstrip("/"))
        try:
            response = self.session.request(
                method, url, json=data, params=params, verify=self.verify_ssl,
                timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise GeoNatureAPIError("Connexion impossible : %s" % exc)

        if response.status_code >= 400:
            raise GeoNatureAPIError(
                "HTTP %s — %s" % (response.status_code, _error_detail(response)),
                status_code=response.status_code,
            )
        if not response.text:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # ------------------------------------------------------------ stations
    def get_stations(self, params=None, geojson=False):
        """Stations du serveur. Route LOURDE : elle peut rendre un JDD entier,
        géométries comprises."""
        params = dict(params or {})
        if geojson:
            params["format"] = "geojson"
        return self._make_request("GET", "occhab/stations/", params=params,
                                  timeout=DELAI_LONG)

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
            "POST", "occhab/export_stations/%s" % export_format, data=data,
            timeout=DELAI_LONG,
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

    # ------------------------------------------------- module Exports (EXPORTS)
    def list_exports(self):
        """Exports publiés par le module EXPORTS, visibles par l'utilisateur.

        Liste vide si le module n'est pas installé ou si le droit R manque : ce
        n'est pas une erreur, juste une instance qui ne propose pas d'export.
        """
        result = self._make_request("GET", "exports/")
        if isinstance(result, dict):  # certaines versions enveloppent la liste
            result = result.get("items") or result.get("exports") or []
        return result if isinstance(result, list) else []

    def get_export_page(self, id_export, limit=TAILLE_PAGE_EXPORT, offset=0,
                        filters=None):
        """UNE page d'un export (`GET /exports/api/<id>`).

        ⚠ `offset` est un **numéro de page**, pas un décalage de lignes — c'est
        la convention de cette route, et s'y tromper renverrait dix fois la même
        page sans que rien ne le signale.

        Renvoie le dict complet : `total`, `total_filtered`, `page`, `limit`,
        `items` (FeatureCollection si l'export porte une géométrie, liste de
        dicts sinon).
        """
        params = dict(filters or {})
        params.update(limit=limit, offset=offset)
        return self._make_request("GET", "exports/api/%s" % int(id_export),
                                  params=params, timeout=DELAI_LONG)

    def iter_export_features(self, id_export, filters=None,
                             limit=TAILLE_PAGE_EXPORT,
                             pages_max=500, on_progress=None):
        """Parcourir un export page par page.

        Returns:
            (features, total_filtered, total) — `features` en objets GeoJSON (ou
            dicts si l'export n'a pas de géométrie). Les **deux** totaux sont
            rendus : l'API ignore en silence un filtre portant sur une colonne
            absente de la vue, et seul l'écart entre les deux permet de s'en
            apercevoir.

        `pages_max` est un garde-fou : une API qui renverrait toujours la même
        page ferait tourner la boucle sans fin.
        """
        features, total_filtered, total, page = [], None, None, 0
        while page < pages_max:
            data = self.get_export_page(id_export, limit=limit, offset=page,
                                        filters=filters) or {}
            if total_filtered is None:
                total_filtered = data.get("total_filtered", data.get("total"))
                total = data.get("total")
            lot = _export_features(data.get("items"))
            features.extend(lot)
            if on_progress is not None:
                on_progress(len(features), total_filtered)
            # Page incomplète = dernière page. On s'arrête aussi dès que le
            # compte annoncé est atteint, sans réclamer une page vide de plus.
            if len(lot) < limit or (total_filtered and len(features) >= total_filtered):
                break
            page += 1
        return features, total_filtered, total

    def test_connection(self):
        """Ping léger pour vérifier connexion/authentification."""
        try:
            self._make_request("GET", "occhab/stations/", params={"limit": 1})
            return True
        except GeoNatureAPIError:
            return False
