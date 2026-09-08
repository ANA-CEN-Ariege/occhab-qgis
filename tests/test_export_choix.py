# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deux vues d'export, et une seule qui se cartographie.

`v_occhab_complet` rend une ligne par habitat : bandes, damier, enjeux et
typologie de restitution y ont un sens. Le gabarit à colonnes plates
`v_habitats_mosaique` n'a plus qu'une ligne par station — lui proposer ces
options serait promettre une carte qui n'arriverait jamais, et lui appliquer le
pipeline de style rendrait une couche grise qu'on prendrait pour une donnée
manquante côté serveur.

Si PyQt/PyQGIS manque, le module s'annonce inutilisable plutôt que d'échouer :
la suite reste exécutable sur un poste sans QGIS.
"""
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from qgis.PyQt.QtWidgets import QApplication
except ImportError:  # pragma: no cover - poste sans PyQGIS
    QApplication = None

if QApplication is not None:
    _APP = QApplication.instance() or QApplication([])
    from occhab.src.ui import export_dialog as ed
    from occhab.src.ui.export_layers import MODE_BRUT, MODE_DEFAUT

#: Ce que publie une instance : les deux vues du plugin, et le reste.
_EXPORTS = [
    {"id": 1, "label": "OccHab consolidé", "view_name": "v_occhab_complet"},
    {"id": 2, "label": "Gabarit habitats", "view_name": "v_habitats_mosaique"},
    {"id": 3, "label": "Synthèse SINP", "view_name": "v_synthese_sinp"},
]


def _picker(exports):
    return ed.ExportPicker(exports, datasets=[(7, "JDD test")], id_dataset=7)


def test_les_deux_vues_sont_retenues_les_autres_non():
    """Une vue de structure inconnue n'a ni les filtres ni la couche promis."""
    if QApplication is None:  # pragma: no cover
        return
    assert [e["id"] for e in ed.exports_occhab(_EXPORTS)] == [1, 2]


def test_la_vue_se_devine_du_libelle_quand_le_modele_ne_la_donne_pas():
    """Anciennes versions du module Exports : `view_name` manquait.

    Le repli décide de l'affichage des options de carte, pas seulement de la
    présence dans la liste : le deviner faux les proposerait sur une couche qui
    ne peut pas les honorer.
    """
    if QApplication is None:  # pragma: no cover
        return
    vieux = {"id": 9, "label": "export bâti sur v_habitats_mosaique"}
    assert ed.vue_de(vieux) == ed.VUE_GABARIT
    assert not ed.est_cartographiable(ed.vue_de(vieux))
    assert ed.est_cartographiable(ed.VUE_EXPORT)


def test_le_gabarit_se_charge_brut_et_sans_options_de_carte():
    if QApplication is None:  # pragma: no cover
        return
    picker = _picker([_EXPORTS[1]])
    try:
        assert not picker.cartographiable()
        assert picker.mode() == MODE_BRUT
        # Ni mode ni typologie dans le nom de la couche : il n'y en a pas.
        assert picker.libelle_mode() == ""
        assert picker.typologie() is None
        assert picker.libelle_typologie() == ""
        for widget in (picker.combo_mode, picker.combo_typologie,
                       picker.label_mosaiques, picker.label_typologie):
            assert widget.isHidden(), widget
    finally:
        picker.deleteLater()


def test_la_vue_pivot_garde_ses_options():
    if QApplication is None:  # pragma: no cover
        return
    picker = _picker([_EXPORTS[0]])
    try:
        assert picker.cartographiable()
        assert picker.mode() == MODE_DEFAUT
        assert picker.libelle_mode()
        for widget in (picker.combo_mode, picker.combo_typologie):
            assert not widget.isHidden(), widget
    finally:
        picker.deleteLater()


def test_les_options_suivent_l_export_choisi():
    """Deux exports dans la même liste : changer de ligne change le dialogue."""
    if QApplication is None:  # pragma: no cover
        return
    picker = _picker(_EXPORTS[:2])
    try:
        picker.combo_export.setCurrentIndex(1)
        assert picker.mode() == MODE_BRUT
        assert picker.combo_mode.isHidden()
        picker.combo_export.setCurrentIndex(0)
        assert picker.mode() == MODE_DEFAUT
        assert not picker.combo_mode.isHidden()
    finally:
        picker.deleteLater()


def test_les_filtres_sont_les_memes_sur_les_deux_vues():
    """Le gabarit est filtré comme l'autre : c'est tout l'objet de l'intégration.

    Sans filtre de JDD ni de période, on rapatrierait l'export entier pour en
    livrer une année — et la route ne dirait rien.
    """
    if QApplication is None:  # pragma: no cover
        return
    picker = _picker([_EXPORTS[1]])
    try:
        filtres = picker.filtres()
        assert filtres[ed.COLONNE_JDD] == 7
        assert "filter_d_up_%s" % ed.COLONNE_DATE_DEBUT in filtres
        assert "filter_d_lo_%s" % ed.COLONNE_DATE_FIN in filtres
    finally:
        picker.deleteLater()


def test_le_gabarit_porte_les_colonnes_sur_lesquelles_le_plugin_filtre():
    """Le lien entre les deux fichiers, et le plus fragile de l'intégration.

    `GET /exports/api/<id>` filtre SUR LES COLONNES DE LA VUE et ignore EN
    SILENCE un filtre portant sur une colonne absente. Renommer une constante
    ici, ou retirer une colonne technique du SQL, rendrait le filtrage
    silencieusement inopérant — le plugin ne le devinerait qu'en comparant
    `total` et `total_filtered`, c'est-à-dire trop tard.
    """
    if QApplication is None:  # pragma: no cover
        return
    with open(os.path.join(_ROOT, "sql", "v_habitats_mosaique.sql"),
              encoding="utf-8") as fh:
        script = fh.read()
    # Le SQL exécutable seul : les commentaires citent ces noms pour expliquer.
    code = "\n".join(re.sub(r"--.*$", "", ligne) for ligne in script.split("\n"))
    for colonne in (ed.COLONNE_JDD, ed.COLONNE_DATE_DEBUT, ed.COLONNE_DATE_FIN):
        assert re.search(r"AS %s,\s*$" % colonne, code, re.MULTILINE), colonne
