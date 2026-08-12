# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de la colonne « Habitat (HABREF) » de la table attributaire.

Ces tests existent à cause d'un bug **du serveur**, pas du plugin : sur
l'instance de l'ANA, `GET /habref/habitat/<cd_hab>` répond 500 pour 87 des 181
alliances du catalogue, parce que la table de correspondances du référentiel
pointe vers des `cd_hab` absents de `habref` (`AttributeError: 'NoneType' object
has no attribute 'as_dict'` dans `pypn_habref_api`). Le plugin ne peut pas le
réparer, mais il ne doit pas rendre une colonne vide alors que l'autocomplétion,
elle, répond parfaitement.

Deux règles sont vérifiées ici, et toutes deux ont laissé la colonne inutilisable
en conditions réelles :

- **chercher sur le nom quand il n'y a pas de code.** Une alliance du Prodrome
  est citée « Cynosurion cristati », sans code en tête. Le repli exigeait un
  code et abandonnait donc sans rien tenter ;
- **couper le nom répété.** L'autocomplétion rend « 6.0.2.0.1 - Cynosurion
  cristati Cynosurion cristati Tüxen 1947 » : le nom y figure deux fois, et
  c'est ce doublon qui s'affichait.

Le module d'interface ne s'importe qu'avec PyQGIS. Sans lui, le fichier
s'annonce inutilisable plutôt que d'échouer.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qgis.PyQt.QtWidgets import QApplication
except ImportError:  # pragma: no cover - poste sans PyQGIS
    QApplication = None

if QApplication is not None:
    _APP = QApplication.instance() or QApplication([])
    from occhab.src.ui import dock_widget as dw


#: Ce que l'autocomplétion rend vraiment pour une alliance PVF1 : ni `lb_hab_fr`
#: ni `lb_nom`, seulement `search_name` et un code de rang.
AUTOCOMPLETE_PVF1 = {
    "cd_hab": 16417, "cd_typo": 18, "lb_code": "6.0.2.0.1",
    "lb_nom_typo": "Prodrome_des_végétations_de_France_(PVF1)",
    "search_name": "6.0.2.0.1 - Cynosurion cristati Cynosurion cristati Tüxen 1947",
}


class _Client:
    """Doublure : la fiche tombe, l'autocomplétion répond — le cas réel."""

    is_authenticated = True

    def __init__(self, items=(), fiche=None):
        self.items = list(items)
        self.fiche = fiche
        self.recherches = []

    def get_habref(self, cd_hab):
        if self.fiche is None:
            raise RuntimeError("HTTP 500 — AttributeError côté serveur")
        return self.fiche

    def search_habref(self, terme, cd_typo=None, limit=20):
        self.recherches.append(terme)
        return self.items


class _Journal:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def _dock(client):
    """Le dock sans le construire : `_libelle_habref` n'a besoin que du client.

    Instancier le vrai widget demanderait une base locale, une configuration et
    une fenêtre QGIS — pour une méthode qui ne touche à rien de tout cela.
    """
    objet = dw.OccHabDockWidget.__new__(dw.OccHabDockWidget)
    objet.client = client
    objet.logger = _Journal()
    return objet


# --------------------------------------------------- le libellé d'une réponse
def test_le_nom_repete_est_coupe():
    """« Cynosurion cristati Cynosurion cristati Tüxen 1947 » n'est pas un nom."""
    assert dw._libelle_de_fiche(AUTOCOMPLETE_PVF1) == "Cynosurion cristati"


def test_la_fiche_directe_garde_ses_champs():
    assert dw._libelle_de_fiche({"lb_hab_fr": "Prairies de fauche"}) == \
        "Prairies de fauche"
    assert dw._libelle_de_fiche({"data": {"lb_nom": "Enveloppé"}}) == "Enveloppé"
    assert dw._libelle_de_fiche(None) == ""
    assert dw._libelle_de_fiche({}) == ""


# ------------------------------------- le repli quand la fiche tombe (HTTP 500)
def test_sans_code_en_tete_on_cherche_sur_le_nom():
    """Le cas des 87 alliances : exiger un code laissait la colonne vide."""
    client = _Client(items=[AUTOCOMPLETE_PVF1])
    libelle, raison = _dock(client)._libelle_habref(16417, "Cynosurion cristati")
    assert libelle == "Cynosurion cristati", raison
    assert client.recherches == ["Cynosurion cristati"]


def test_le_code_en_tete_reste_prioritaire():
    """Un code est plus discriminant qu'un nom : il ne rend qu'un habitat."""
    client = _Client(items=[AUTOCOMPLETE_PVF1])
    _dock(client)._libelle_habref(
        16417, "6.0.2.0.1 - Cynosurion cristati")
    assert client.recherches == ["6.0.2.0.1"]


def test_la_fiche_directe_evite_toute_recherche():
    """Tant que le serveur répond, on ne fait qu'un appel."""
    client = _Client(fiche={"lb_hab_fr": "Prairies de fauche"})
    libelle, _raison = _dock(client)._libelle_habref(16417, "Cynosurion cristati")
    assert libelle == "Prairies de fauche"
    assert client.recherches == []


def test_un_autre_habitat_dans_la_recherche_n_est_pas_retenu():
    """Chercher sur un nom rend plusieurs habitats : seul le bon cd_hab compte.

    Sans ce contrôle, la colonne afficherait le libellé du voisin — une erreur
    de donnée invisible, puisqu'elle a l'air d'un nom d'habitat plausible.
    """
    voisin = dict(AUTOCOMPLETE_PVF1, cd_hab=16418,
                  search_name="6.0.2.0.2 - Poion alpinae Poion alpinae Ellmauer")
    client = _Client(items=[voisin])
    libelle, raison = _dock(client)._libelle_habref(16417, "Cynosurion cristati")
    assert libelle == ""
    assert "absent de la recherche" in raison


def test_sans_nom_ni_code_on_renonce_sans_appeler():
    client = _Client(items=[AUTOCOMPLETE_PVF1])
    libelle, raison = _dock(client)._libelle_habref(16417, "")
    assert libelle == "" and raison
    assert client.recherches == []


def test_une_recherche_qui_echoue_ne_remonte_pas():
    """Hors ligne, une colonne partiellement vide vaut mieux qu'une exception."""
    class _Casse(_Client):
        def search_habref(self, terme, cd_typo=None, limit=20):
            raise RuntimeError("réseau coupé")

    libelle, raison = _dock(_Casse())._libelle_habref(16417, "Cynosurion cristati")
    assert libelle == "" and "réseau coupé" in raison


# ------------------------------------- rattraper un cache écrit par une v. antérieure
class _Base:
    """Doublure de base locale : garde ce qu'on lui écrit."""

    def __init__(self, libelles):
        self.libelles = dict(libelles)
        self.ecritures = []

    def libelles_habref(self, cd_habs=None):
        return dict(self.libelles)

    def enregistrer_libelles_habref(self, valeurs):
        self.ecritures.append(dict(valeurs))
        self.libelles.update(valeurs)


def _dock_avec_base(base, client=None):
    objet = dw.OccHabDockWidget.__new__(dw.OccHabDockWidget)
    objet.client = client or _Client()
    objet.db = base
    objet.logger = _Journal()
    return objet


def test_le_cache_au_nom_repete_est_corrige_et_reecrit():
    """Douze libellés réels portaient le nom répété : le rapprochement échouait.

    Les corriger seulement à l'affichage laisserait la base fausse ; les purger
    obligerait à tout redemander au serveur. On rattrape et on réécrit.
    """
    base = _Base({
        16415: ("Brachypodio rupestris-Centaureion nemoralis Brachypodio "
                "rupestris-Centaureion nemoralis Br.-Bl. 1967"),
        16508: "Caricion gracilis Caricion gracilis Neuhäusl 1959",
        24912: "Bidentetalia",
    })
    propres = _dock_avec_base(base)._rattraper_libelles(base.libelles_habref())
    assert propres[16415] == "Brachypodio rupestris-Centaureion nemoralis"
    assert propres[16508] == "Caricion gracilis"
    assert propres[24912] == "Bidentetalia"
    assert base.ecritures and set(base.ecritures[0]) == {16415, 16508}


def test_un_libelle_a_tiret_espace_n_est_pas_ampute():
    """« Centaurio pulchelli - Blackstonion perfoliatae » est un nom entier."""
    base = _Base({16694: "Centaurio pulchelli - Blackstonion perfoliatae"})
    propres = _dock_avec_base(base)._rattraper_libelles(base.libelles_habref())
    assert propres[16694] == "Centaurio pulchelli - Blackstonion perfoliatae"
    assert base.ecritures == [], "rien n'a changé : rien à réécrire"


def test_une_base_en_lecture_seule_n_empeche_pas_l_affichage():
    class _Refuse(_Base):
        def enregistrer_libelles_habref(self, valeurs):
            raise RuntimeError("base verrouillée")

    base = _Refuse({16508: "Caricion gracilis Caricion gracilis Neuhäusl 1959"})
    propres = _dock_avec_base(base)._rattraper_libelles(base.libelles_habref())
    assert propres[16508] == "Caricion gracilis"


# --------------------- repérer les correspondances arbitrées sans leur libellé
def _bloc_sans_libelle():
    from occhab.src.processing.eval_fields import encode_eval
    return encode_eval("", corresp={"EUNIS": {"cd_hab": 4841, "code": "C1.32",
                                              "src": "manuel"}})


class _BaseStations:
    """Doublure reproduisant la DIFFÉRENCE entre les deux lectures de la base.

    `get_all_stations` ne rend que les lignes de `t_stations` — sans habitats —,
    `get_stations_full` les rend avec. C'est exactement ce piège qui rendait
    l'action inopérante.
    """

    def __init__(self, stations):
        self._stations = stations

    def get_all_stations(self, sync_status=None, id_dataset=None):
        return [{k: v for k, v in s.items() if k != "habitats"}
                for s in self._stations]

    def get_stations_full(self, id_dataset=None):
        return [dict(s, habitats=list(s.get("habitats") or []))
                for s in self._stations]


def test_les_correspondances_sans_libelle_sont_bien_trouvees():
    """L'action annonçait « rien à compléter » sur une base qui en avait vingt.

    Les tests du repérage étaient au vert : ils portaient sur `libelles_manquants`
    seul, et rien ne vérifiait que la donnée lui parvenait.
    """
    base = _BaseStations([
        {"id": 1, "habitats": [{"cd_hab": 4841, "nom_cite": "Lemnion minoris",
                                "technical_precision": _bloc_sans_libelle()}]},
        {"id": 2, "habitats": [{"cd_hab": 651, "nom_cite": "Cultures",
                                "technical_precision": ""}]},
    ])
    stations, a_faire = _dock_avec_base(base)._correspondances_sans_libelle()
    assert len(a_faire) == 1
    station, habitat = a_faire[0]
    assert station["id"] == 1 and habitat["cd_hab"] == 4841
    # Les stations sont rendues AVEC leurs habitats : la réécriture en a besoin.
    assert stations[0]["habitats"], "sans habitats, rien ne pourrait être réécrit"


def test_une_base_sans_correspondance_a_completer_ne_rend_rien():
    base = _BaseStations([
        {"id": 1, "habitats": [{"cd_hab": 651, "nom_cite": "Cultures",
                                "technical_precision": ""}]},
    ])
    _stations, a_faire = _dock_avec_base(base)._correspondances_sans_libelle()
    assert a_faire == []
