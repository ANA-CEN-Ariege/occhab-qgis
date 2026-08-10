# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests du formulaire habitat et de ses correspondances, widgets réels.

Ces tests construisent le VRAI `HabitatForm` hors écran (`QT_QPA_PLATFORM=
offscreen`), sans lancer QGIS. Ils existent parce qu'une suite qui ne teste que
les modules purs a laissé passer deux fois de suite ce qui compte le plus :

- une extension **qui ne se charge plus** — un changement de forme d'un
  référentiel a cassé un dépaquetage dans un widget, tous les tests au vert ;
- des **régressions de données invisibles** — re-choisir le même habitat annulait
  les arbitrages, rouvrir une alliance ancrée effaçait sa correspondance CORINE.
  Aucune de ces deux fautes ne touche une fonction pure : elles vivent dans
  l'enchaînement des signaux entre la ligne de saisie, le formulaire et le
  composant de correspondances.

Aucun accès réseau : `habref_search` et `habref_detail` sont des doublures. Le
catalogue, lui, est le VRAI fichier livré — c'est aussi ce qu'on veut vérifier.

Si PyQt/PyQGIS manque, le module s'annonce inutilisable plutôt que d'échouer :
la suite reste exécutable sur un poste sans QGIS.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qgis.PyQt.QtWidgets import QApplication
except ImportError:  # pragma: no cover - poste sans PyQGIS
    QApplication = None

if QApplication is not None:
    _APP = QApplication.instance() or QApplication([])
    from occhab.src.processing import correspondances as co
    from occhab.src.processing.eval_fields import decode_eval
    from occhab.src.processing.export import flatten_cartography
    from occhab.src.ui import habitat_form as hf
    from occhab.src.ui.attribute_table import SANS_CATALOGUE


#: Typologies telles que le serveur les publie (cd_typo, libellé).
TYPOLOGIES = [
    (22, "CORINE_biotopes"),
    (7, "EUNIS"),
    (8, "Habitats_d'intérêt_communautaire"),
    (4, "Cahiers_d'habitats"),
    (18, "Prodrome_des_végétations_de_France_(PVF1)"),
]
#: Fiches HABREF servies par la doublure, par cd_hab.
FICHES = {
    10521: {"cd_hab": 10521, "cd_typo": 7, "lb_code": "A3.112",
            "correspondances": [
                {"cd_typo_sortie": 8, "habref": {"cd_hab": 2865, "lb_code": "1170",
                                                 "lb_hab_fr": "Récifs"}}]},
}


def _detail(cd_hab):
    return FICHES.get(cd_hab, {"cd_hab": cd_hab, "cd_typo": 22, "lb_code": "22.3",
                               "correspondances": []})


def _recherche(_texte, cd_typo=None):
    """Doublure : rend toujours l'habitat EUNIS A3.112, dont `FICHES` a la fiche."""
    return [{"cd_hab": 10521, "lb_code": "A3.112", "cd_typo": 7,
             "lb_nom_typo": "EUNIS",
             "search_name": "A3.112 - Roche infralittorale Roche infralittorale A. 90"}]


def _formulaire(habref_detail=_detail, habref_search=_recherche):
    """Formulaire réel, affiché : sans `show()`, `isVisible()` ment."""
    form = hf.HabitatForm(
        nomenclatures={"technique": [(1, "In situ")]},
        habref_search=habref_search, habref_detail=habref_detail,
        typologies=TYPOLOGIES,
    )
    form.show()
    return form


def _choisir_habref(form, texte="roche infralittorale"):
    """Retenir une proposition HABREF par le VRAI chemin.

    Passer par `_on_habitat_chosen` en direct court-circuiterait la ligne de
    saisie — donc l'oubli de l'alliance précédente, qu'elle seule fait. Un test
    qui appelle les internes ne vérifie pas ce que Qt exécute.

    Le texte est en français : les noms du catalogue sont latins, la liste ne
    contient donc que la proposition HABREF, et l'assertion le garantit.
    """
    edit = form.edit_nom_cite
    edit._pending = texte
    edit._rechercher()
    edit._on_choisi(edit._modele.index(0, 0))
    assert edit.item_choisi is not None, "la proposition retenue doit venir de HABREF"
    return edit.item_choisi


def _ancree():
    """Une alliance du catalogue livré, absente de HABREF, avec un CORINE."""
    return next(a for a in co.catalogue().ancrees()
                if "CORINE_biotopes" in a.correspondances())


def _a_variantes():
    """Une alliance dont le catalogue propose plusieurs correspondances."""
    return co.catalogue().chercher("Luzulo luzuloidis")[0]


# ------------------------------------------------------- le plugin se charge
def test_le_formulaire_se_construit():
    """Garde-fou de chargement : c'est ici qu'un référentiel changé de forme casse."""
    form = _formulaire()
    assert len(form.corresp_edit._lignes) == 4
    assert form.get_data()["cd_hab"] is None


def test_la_table_attributaire_ne_propose_pas_le_catalogue():
    """Une cellule n'écrit ni détermination ni correspondances : pas de catalogue."""
    assert len(SANS_CATALOGUE) == 0


# --------------------------------------------- une ancre n'est pas une détermination
def test_alliance_ancree_enregistre_sa_determination():
    alliance = _ancree()
    form = _formulaire()
    form.edit_nom_cite._retenir_alliance(alliance)
    donnees = form.get_data()
    assert donnees["cd_hab"] == alliance.ancre_cd_hab
    codes = decode_eval(donnees["technical_precision"])
    assert codes["determination"]["nom"] == alliance.nom
    assert codes["determination"]["ancre"] == alliance.ancre_typologie
    assert "ANCRE" in form.label_catalogue.text()
    assert form.label_catalogue.isVisible()


def test_relire_une_alliance_ancree_preserve_ses_correspondances():
    """Le `cd_hab` étant un code CORINE, la fiche HABREF le dit « CORINE ».

    Verrouiller la ligne CORINE effaçait alors la correspondance enregistrée, et
    affichait « c'est la détermination elle-même » juste sous la mise en garde
    qui dit l'inverse. Une ancre n'est pas une détermination.
    """
    alliance = _ancree()
    saisie = _formulaire()
    saisie.edit_nom_cite._retenir_alliance(alliance)
    donnees = saisie.get_data()
    attendu = decode_eval(donnees["technical_precision"])["corresp"]

    relecture = _formulaire()
    relecture.set_data({"cd_hab": alliance.ancre_cd_hab, "nom_cite": alliance.nom,
                        "technical_precision": donnees["technical_precision"]})
    obtenu = decode_eval(relecture.get_data()["technical_precision"])["corresp"]
    assert obtenu == attendu
    ligne = relecture.corresp_edit._lignes["CORINE_biotopes"]
    assert ligne.pile.currentIndex() != 2, "la ligne d'une ancre ne se verrouille pas"


def test_determination_dans_une_typologie_cible_ne_pose_pas_de_question():
    """Un habitat déterminé en EUNIS EST sa correspondance EUNIS."""
    form = _formulaire()
    _choisir_habref(form)
    ligne = form.corresp_edit._lignes["EUNIS"]
    assert ligne.pile.currentIndex() == 2
    assert "détermination elle-même" in ligne.propre.text()
    # Rien n'est enregistré pour cette typologie : ce serait recopier le cd_hab.
    assert "EUNIS" not in (form.corresp_edit.get_data() or {})


# ------------------------------------------------- l'arbitrage ne s'annule pas
def _arbitrer(form, typologie, index=1):
    ligne = form.corresp_edit._lignes[typologie]
    ligne.choix.setCurrentIndex(index)
    form.corresp_edit._on_choix_liste(typologie)


def test_rechoisir_la_meme_alliance_preserve_l_arbitrage():
    """Corriger une coquille dans le nom cité re-déclenche la sélection.

    Les correspondances étaient alors regarnies : « arbitré ici » redevenait
    « repris du catalogue », sans que rien ne le dise.
    """
    alliance = _a_variantes()
    form = _formulaire()
    form.edit_nom_cite._retenir_alliance(alliance)
    _arbitrer(form, "EUNIS")
    avant = dict(form.corresp_edit.get_data()["EUNIS"])
    assert avant["src"] == "manuel"

    form.edit_nom_cite._retenir_alliance(alliance)  # même alliance re-choisie
    assert dict(form.corresp_edit.get_data()["EUNIS"]) == avant


def test_rechoisir_le_meme_habitat_habref_preserve_l_arbitrage():
    """Même garde-fou, sur l'autre chemin de sélection."""
    form = _formulaire()
    _choisir_habref(form)
    _arbitrer(form, "Habitats_d'intérêt_communautaire")
    avant = dict(form.corresp_edit.get_data()["Habitats_d'intérêt_communautaire"])
    assert avant["src"] == "manuel"

    _choisir_habref(form)
    assert dict(form.corresp_edit.get_data()[
        "Habitats_d'intérêt_communautaire"]) == avant


def test_changer_d_habitat_efface_bien_les_correspondances():
    """Le garde-fou ne doit pas figer : un AUTRE habitat repart de zéro."""
    form = _formulaire()
    form.edit_nom_cite._retenir_alliance(_ancree())
    assert form.get_data()["technical_precision"]
    _choisir_habref(form)
    codes = decode_eval(form.get_data()["technical_precision"] or "")
    assert "determination" not in codes


# --------------------------------------------- rien n'est choisi à notre place
def test_plusieurs_candidats_ne_sont_pas_tranches_d_office():
    alliance = _a_variantes()
    form = _formulaire()
    form.edit_nom_cite._retenir_alliance(alliance)
    assert form.corresp_edit.a_trancher(), "un choix en suspens doit être signalé"
    assert "choisissez-en une" in form.label_catalogue.text()
    assert form.corresp_edit.isVisible()


def test_la_relecture_rappelle_les_choix_en_suspens():
    """Sans regarnir les propositions, la mise en garde ne revenait jamais."""
    alliance = _a_variantes()
    saisie = _formulaire()
    saisie.edit_nom_cite._retenir_alliance(alliance)
    attendu = saisie.corresp_edit.a_trancher()
    donnees = saisie.get_data()

    relecture = _formulaire()
    relecture.set_data({"cd_hab": alliance.cd_hab_a_poser, "nom_cite": alliance.nom,
                        "technical_precision": donnees["technical_precision"]})
    assert relecture.corresp_edit.a_trancher() == attendu
    assert relecture.corresp_edit.isVisible()


def test_la_condition_natura_2000_revient_a_la_relecture():
    """Elle n'est portée par aucune donnée enregistrée, et décide si le code
    s'applique : la relecture doit la revoir."""
    alliance = next(a for a in co.catalogue().alliances
                    if a.condition_n2000 and a.cd_hab)
    FICHES[alliance.cd_hab] = {"cd_hab": alliance.cd_hab, "cd_typo": 18,
                               "lb_code": alliance.code_habref,
                               "correspondances": []}
    saisie = _formulaire()
    saisie.edit_nom_cite._retenir_alliance(alliance)
    donnees = saisie.get_data()

    relecture = _formulaire()
    relecture.set_data({"cd_hab": alliance.cd_hab, "nom_cite": alliance.nom,
                        "technical_precision": donnees["technical_precision"]})
    assert "sous condition" in relecture.label_catalogue.text()


# ------------------------------------------------------ jusqu'à la restitution
def test_l_arbitrage_ressort_a_l_export():
    """Seul « manuel » atteste d'un contrôle : c'est lui que l'export isole."""
    alliance = _a_variantes()
    form = _formulaire()
    form.edit_nom_cite._retenir_alliance(alliance)
    _arbitrer(form, "EUNIS")
    donnees = form.get_data()

    ligne = flatten_cartography([(
        {"id_station": 1, "geom": "POINT(0 0)", "geom_type": "Point"},
        [{"id_habitat": 1, "cd_hab": donnees["cd_hab"], "nom_cite": alliance.nom,
          "technical_precision": donnees["technical_precision"]}],
        [])])[0]
    assert ligne["corresp_manu"] == "EUNIS"
    assert ligne["eunis_cite"]


# ------------------------------------------------------------- hors connexion
def test_hors_connexion_la_saisie_reste_possible():
    """Ni recherche HABREF ni fiche : le catalogue local répond quand même."""
    form = _formulaire(habref_detail=None, habref_search=None)
    edit = form.edit_nom_cite
    edit._pending = "luzulo"
    edit._rechercher()
    assert edit._modele.rowCount() >= 1, "le catalogue est sur le disque"


def test_un_contexte_obtenu_sans_reseau_n_est_pas_mis_en_cache():
    """Sinon l'habitat resterait sans proposition pour toute la session."""
    hf._FICHES.pop(10521, None)
    form = _formulaire(habref_detail=None)
    _choisir_habref(form)
    assert 10521 not in hf._FICHES
