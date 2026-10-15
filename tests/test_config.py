# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests de la configuration (`src/utils/config.py`), sans QGIS.

Le guide invite à modifier config.json à la main. Trois façons d'y perdre des
réglages ont été vues : une modification écrasée par le plugin qui réécrivait
sa copie en mémoire, un fichier « UTF-8 avec BOM » refusé, une virgule en trop
qui ramenait tout aux défauts sans un mot.
"""
import importlib.util
import json
import os

import pytest

_CHEMIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "src", "utils", "config.py")


@pytest.fixture
def config_mod(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("config_occhab", _CHEMIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_user_config_dir", lambda: tmp_path)
    return module


def test_aucune_adresse_de_serveur_reel_par_defaut(config_mod):
    """Pré-remplie avec geonature.fr, l'adresse recevait les identifiants."""
    assert config_mod.Config().get("geonature.api_url") == ""


def test_un_fichier_avec_bom_se_lit(config_mod, tmp_path):
    (tmp_path / "config.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"geonature": {"authcfg": "abc1234"}}).encode()
    )
    config = config_mod.Config()
    assert config.get("geonature.authcfg") == "abc1234"
    assert config.avertissement is None


def test_une_modification_a_la_main_survit_au_reglage_suivant(config_mod, tmp_path):
    config = config_mod.Config()
    config.set("id_dataset", 3)
    fichier = tmp_path / "config.json"
    contenu = json.loads(fichier.read_text(encoding="utf-8"))
    contenu["reconnexion_auto"] = False  # édité à la main, QGIS ouvert
    fichier.write_text(json.dumps(contenu), encoding="utf-8")

    config.set("id_dataset", 4)

    relu = json.loads(fichier.read_text(encoding="utf-8"))
    assert relu["reconnexion_auto"] is False and relu["id_dataset"] == 4


def test_un_fichier_illisible_est_garde_de_cote_et_signale(config_mod, tmp_path):
    fichier = tmp_path / "config.json"
    original = '{"geonature": {"authcfg": "abc1234",}}'  # virgule en trop
    fichier.write_text(original, encoding="utf-8")

    config = config_mod.Config()
    assert config.avertissement and "illisible" in config.avertissement
    config.set("id_dataset", 3)  # le premier réglage écrasait l'original

    assert (tmp_path / "config.json.illisible").read_text(encoding="utf-8") == original
    assert json.loads(fichier.read_text(encoding="utf-8"))["id_dataset"] == 3


def test_un_fichier_abime_en_cours_de_session_est_signale_aussitot(config_mod, tmp_path):
    """Une clé ajoutée à la main avec une virgule de trop disparaissait au
    réglage suivant (gardée seulement dans `.illisible`), sans un mot."""
    config = config_mod.Config()
    messages = []
    config.signaler = messages.append
    (tmp_path / "config.json").write_text('{"reconnexion_auto": false,}', encoding="utf-8")

    config.set("id_dataset", 3)

    assert len(messages) == 1 and "illisible" in messages[0]
