# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Le script SQL livré et les blocs du README ne doivent pas diverger.

Le même SQL est écrit à deux endroits : `sql/v_occhab_complet.sql`, qu'on
exécute, et le README, qui l'explique pas à pas. Deux copies dérivent toujours,
et celle qui dérive est celle qu'on ne lance pas — l'administrateur suivrait
alors un README qui ne décrit plus ce qu'il a posé sur son serveur.
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, "sql", "v_occhab_complet.sql")
_README = os.path.join(_ROOT, "README.md")

#: Ce que chaque étape du script doit créer.
_OBJETS = (
    "CREATE INDEX IF NOT EXISTS habref_corresp_hab_cd_hab_sortie_idx",
    "CREATE INDEX IF NOT EXISTS habref_cd_hab_sup_idx",
    "CREATE OR REPLACE FUNCTION gn_exports.ana_eval_json",
    "CREATE OR REPLACE FUNCTION gn_exports.habref_famille",
    "CREATE OR REPLACE FUNCTION gn_exports.habref_equivalents",
    "CREATE OR REPLACE VIEW gn_exports.v_occhab_complet AS",
)


def _lire(chemin):
    with open(chemin, encoding="utf-8") as fh:
        return fh.read()


def _blocs_sql(readme):
    return re.findall(r"^```sql\n(.*?)^```$", readme, re.MULTILINE | re.DOTALL)


def test_le_script_existe_et_cree_les_cinq_objets():
    script = _lire(_SCRIPT)
    for objet in _OBJETS:
        assert objet in script, objet


def test_la_vue_est_supprimee_avant_d_etre_recreee():
    """`CREATE OR REPLACE VIEW` refuse de changer le type d'une colonne."""
    script = _lire(_SCRIPT)
    drop = script.index("DROP VIEW IF EXISTS gn_exports.v_occhab_complet")
    create = script.index("CREATE OR REPLACE VIEW gn_exports.v_occhab_complet")
    assert drop < create


def _sans_commentaires(sql):
    """Le SQL exécutable seul : les commentaires citent `IS JSON` pour l'écarter."""
    return "\n".join(re.sub(r"--.*$", "", ligne) for ligne in sql.split("\n"))


def test_pas_de_predicat_is_json():
    """Réservé à PostgreSQL 16 ; le serveur visé est en 15."""
    code = _sans_commentaires(_lire(_SCRIPT))
    assert not re.search(r"\bIS\s+JSON\b", code, re.IGNORECASE)


def test_zone_humide_rendue_en_texte():
    """Le cast en booléen échouait dès qu'une station portait « oui »."""
    code = _sans_commentaires(_lire(_SCRIPT))
    assert "'zone_humide')::boolean" not in code
    assert "station_zone_humide" in code


def test_les_blocs_du_readme_sont_dans_le_script():
    """Chaque bloc SQL d'installation du README se retrouve tel quel."""
    script = _lire(_SCRIPT)
    manquants = [
        bloc for bloc in _blocs_sql(_lire(_README))
        if any(objet in bloc for objet in _OBJETS) and bloc.strip() not in script
    ]
    assert not manquants, [bloc.splitlines()[0] for bloc in manquants]


def test_les_correspondances_saisies_ne_coutent_aucune_jointure():
    """La 0.8.0 a cassé l'export : plus jamais de table pour lire le bloc.

    Pour résoudre le libellé d'une correspondance saisie, la vue joignait
    `ref_habitats.habref` depuis un `jsonb_each`. PostgreSQL ignore la
    cardinalité d'une fonction à retour d'ensemble, choisissait un hachage, et
    construisait une table de hachage sur HABREF entière à chaque habitat.
    L'export s'effondrait et le reverse-proxy rendait un 502.

    La vue ne lit donc plus QUE ce que le bloc contient déjà. Ce test compare
    l'arbre de jointures à celui de la version qui fonctionnait : il doit être
    identique. Aucun test fonctionnel ne peut voir cette propriété, et elle se
    reperd à la première relecture distraite.
    """
    code = _sans_commentaires(_lire(_SCRIPT))
    vue = code[code.index("CREATE OR REPLACE VIEW gn_exports.v_occhab_complet"):]
    assert "jsonb_each" not in vue, (
        "fonction à retour d'ensemble dans la vue : cardinalité inconnue du "
        "planificateur, donc hachage possible sur la table jointe"
    )
    # Les seules occurrences de `ref_habitats` admises sont celles de la version
    # qui fonctionnait : les jointures `hab` et `t_hab` sur le cd_hab de
    # l'habitat lui-même.
    assert vue.count("ref_habitats.habref") == 1, (
        "une seule lecture de habref dans la vue, celle de l'habitat"
    )
    assert "eh.j -> 'corresp'" in vue, "les correspondances saisies se lisent dans le bloc"


def test_le_bloc_ana_eval_est_decode_une_seule_fois_par_ligne():
    """`OFFSET 0` est une barrière d'optimisation, pas une coquetterie.

    Sans elle, PostgreSQL aplatit le LATERAL trivial et recopie l'appel de
    fonction à chaque référence : `ana_eval_json()` — plpgsql, expression
    régulière — serait exécutée une quarantaine de fois par ligne au lieu d'une.
    C'est la part la plus coûteuse de la vue, et elle grossit à chaque champ
    ajouté au bloc sans que rien ne le signale.
    """
    code = _sans_commentaires(_lire(_SCRIPT))
    for alias in ("es", "eh"):
        debut = code.index("ana_eval_json(%s" % ("s.comment" if alias == "es"
                                                 else "h.technical_precision"))
        bloc = code[debut: code.index(") %s ON true" % alias, debut)]
        assert "OFFSET 0" in bloc, (
            "le LATERAL %s doit porter la barrière, sinon la fonction est "
            "réévaluée à chaque référence" % alias
        )
