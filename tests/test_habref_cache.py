# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du cache des libellés HABREF (base locale).

Il a d'abord vécu dans `config.json` — un fichier de PRÉFÉRENCES. Rafraîchir un
nom d'habitat demandait alors d'éditer ce fichier à la main, et une valeur
bancale y restait pour toujours. Sa place est dans la base, avec le reste des
données.
"""
import os
import tempfile

import sqlite_local


def _base():
    chemin = os.path.join(tempfile.mkdtemp(), "occhab.db")
    return sqlite_local.OccHabDatabase(chemin)


def test_ecrire_et_relire():
    db = _base()
    assert db.enregistrer_libelles_habref({5130: "Fruticées à Juniperus"}) == 1
    assert db.libelles_habref([5130]) == {5130: "Fruticées à Juniperus"}


def test_relire_tout_ou_une_selection():
    db = _base()
    db.enregistrer_libelles_habref({1: "Un", 2: "Deux", 3: "Trois"})
    assert db.libelles_habref() == {1: "Un", 2: "Deux", 3: "Trois"}
    assert db.libelles_habref([2, 3]) == {2: "Deux", 3: "Trois"}
    assert db.libelles_habref([99]) == {}


def test_un_libelle_vide_n_est_pas_retenu():
    """Mieux vaut redemander que garder une valeur incomplète."""
    db = _base()
    assert db.enregistrer_libelles_habref({1: "", 2: "   ", 3: None, 4: 12}) == 0
    assert db.libelles_habref() == {}


def test_mise_a_jour_d_un_libelle():
    """Un habitat renommé dans HABREF doit pouvoir écraser l'ancien nom."""
    db = _base()
    db.enregistrer_libelles_habref({7: "Ancien nom"})
    db.enregistrer_libelles_habref({7: "Nouveau nom"})
    assert db.libelles_habref([7]) == {7: "Nouveau nom"}


def test_oublier_pour_redemander():
    db = _base()
    db.enregistrer_libelles_habref({1: "Un", 2: "Deux"})
    db.oublier_libelles_habref([1])
    assert db.libelles_habref() == {2: "Deux"}
    db.oublier_libelles_habref()
    assert db.libelles_habref() == {}


def test_codes_non_numeriques_ignores():
    db = _base()
    assert db.libelles_habref(["abc", None, ""]) == {}
    assert db.enregistrer_libelles_habref({}) == 0
