# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Le gabarit livré doit sortir dans l'ordre du gabarit.

Le module Exports de GeoNature rend les propriétés PAR ORDRE ALPHABÉTIQUE, quel
que soit l'ordre des colonnes de la vue. Ni QGIS ni OGR n'y sont pour rien — le
dernier test de ce fichier le vérifie sur le vrai pilote — et le plugin ne trie
rien : c'est la sérialisation du serveur qui perd l'ordre en route.

Sans importance pour cartographier ; décisif pour livrer, un gabarit imposé se
lisant colonne après colonne.
"""
import json
import os
import tempfile

import ordre_colonnes as oc  # `src/processing` est au chemin (cf. conftest)

try:
    from osgeo import ogr
except ImportError:  # pragma: no cover - poste sans GDAL
    ogr = None

#: Le gabarit tel que l'API le rend : alphabétique, donc mélangé.
_ALPHABETIQUE = {
    "CodeCB_1": "34.32", "CodeCB_2": "38.2", "CodeEUNIS_1": "E1.26",
    "CodeEUNIS_2": "E2.2", "CodeN2000_1": "6210", "CodeN2000_2": None,
    "Comment": "1. sec", "Date_hab": "2026-06-12", "Description": "coteau",
    "Enjeu": "Fort", "EtatConser": "Bon", "Nb_Habitat": 2, "NomCB_1": "Pelouses",
    "NomCB_2": "Prairies", "NomEUNIS_1": "Pelouses", "NomEUNIS_2": "Prairies",
    "NomN2000_1": "Pelouses sèches", "NomN2000_2": None, "Observateur": "Roy",
    "Rec_1": 70, "Rec_2": 30, "Ref_Biblio": None, "SHAPE_Area": 1234.5,
    "SHAPE_Leng": 145.2, "Source": "Terrain - observation directe avec relevé",
    "Syntaxon_1": "Mesobromion", "Syntaxon_2": "Arrhenatherion",
    "date_max": "2026-06-12", "date_min": "2026-06-12", "fid": 42,
}

#: Ce que le gabarit attend, dans l'ordre.
_ATTENDU = [
    "fid", "Date_hab", "Observateur", "Description", "Nb_Habitat",
    "Syntaxon_1", "CodeEUNIS_1", "NomEUNIS_1", "CodeCB_1", "NomCB_1",
    "CodeN2000_1", "NomN2000_1", "Rec_1",
    "Syntaxon_2", "CodeEUNIS_2", "NomEUNIS_2", "CodeCB_2", "NomCB_2",
    "CodeN2000_2", "NomN2000_2", "Rec_2",
    "EtatConser", "Enjeu", "Comment", "Source", "Ref_Biblio",
    "SHAPE_Leng", "SHAPE_Area",
    "id_dataset", "date_min", "date_max",
]


def _feature(proprietes):
    return {"type": "Feature", "properties": dict(proprietes),
            "geometry": {"type": "Point", "coordinates": [1.9, 43.0]}}


def test_l_ordre_du_gabarit_est_retabli():
    props = dict(_ALPHABETIQUE, id_dataset=7)
    assert list(oc.ordonner_proprietes(props)) == _ATTENDU


def test_les_blocs_se_suivent_par_rang_et_non_par_colonne():
    """Tout le bloc 2 après tout le bloc 1.

    Trier sur le nom seul rangerait `Syntaxon_1, Syntaxon_2, CodeEUNIS_1…` —
    l'habitat 2 se lirait alors en sautant une colonne sur huit.
    """
    ordre = list(oc.ordonner_proprietes(dict(_ALPHABETIQUE, id_dataset=7)))
    assert ordre.index("Rec_1") < ordre.index("Syntaxon_2")


def test_rien_n_est_perdu_ni_inventé():
    """Une colonne ajoutée côté serveur doit être mal placée, jamais perdue."""
    props = dict(_ALPHABETIQUE, Colonne_Inattendue="?", Autre_Surprise="!")
    ordonne = oc.ordonner_proprietes(props)
    # Deux dicts sont égaux quel que soit leur ordre : seul l'ordre a changé.
    assert ordonne == props
    ordre = list(ordonne)
    # En queue, et dans leur ordre d'arrivée : le tri est stable.
    assert ordre[-2:] == ["Colonne_Inattendue", "Autre_Surprise"]


def test_une_couche_qui_n_est_pas_le_gabarit_n_est_pas_touchee():
    """Réordonner une vue inconnue mettrait TOUTES ses colonnes en queue.

    Ce serait pire que le désordre alphabétique : un ordre arbitraire, et qui
    change avec la réponse du serveur.
    """
    autre = {"id_ligne": "1-2", "nom_station": "S", "cd_hab": 5130}
    assert not oc.est_gabarit(autre)
    assert list(oc.ordonner_proprietes(autre)) == list(autre)


def test_ordonner_ne_touche_que_les_entites_du_gabarit():
    features = [_feature(_ALPHABETIQUE), _feature({"cd_hab": 5130, "b": 1}),
                "pas un dict", {"type": "Feature"}]
    oc.ordonner(features)
    assert list(features[0]["properties"])[:2] == ["fid", "Date_hab"]
    assert list(features[1]["properties"]) == ["cd_hab", "b"]


def test_le_fichier_ecrit_porte_les_champs_dans_cet_ordre():
    """Le contrat externe sur lequel repose toute la correction.

    `json.dump` écrit un dict dans son ordre d'insertion, et OGR relit les
    champs dans l'ordre du fichier. Si l'un des deux changeait, la couche
    ressortirait mélangée sans que rien d'autre ne le signale — d'où ce test
    sur le vrai pilote, celui-là même qu'utilise `ExportLayerManager`.
    """
    if ogr is None:  # pragma: no cover - poste sans GDAL
        return
    features = [_feature(dict(_ALPHABETIQUE, id_dataset=7))]
    oc.ordonner(features)
    with tempfile.TemporaryDirectory() as dossier:
        chemin = os.path.join(dossier, "gabarit.geojson")
        with open(chemin, "w", encoding="utf-8") as handle:
            json.dump({"type": "FeatureCollection", "features": features}, handle)
        source = ogr.Open(chemin)
        definition = source.GetLayer(0).GetLayerDefn()
        champs = [definition.GetFieldDefn(i).GetName()
                  for i in range(definition.GetFieldCount())]
        source = None
    # À la lettre, colonnes vides comprises : une propriété toujours nulle
    # (`Ref_Biblio`) donne quand même son champ, à sa place.
    assert champs == _ATTENDU
