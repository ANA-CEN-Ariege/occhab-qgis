# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Le gabarit à colonnes plates se GÉNÈRE : ce que fabrique le script compte.

`sql/v_habitats_mosaique.sql` n'est pas une vue écrite à la main mais un bloc
`DO` qui en fabrique une, à autant de blocs `Syntaxon_n` qu'il y a d'habitats
sur la station la plus riche. Relire le script ne dit donc pas ce qui sera
posé sur le serveur ; ces tests rejouent la génération et inspectent le SQL
qui en sort — le seul texte que PostgreSQL verra.
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, "sql", "v_habitats_mosaique.sql")

#: Colonnes du gabarit qui ne dépendent pas du rang, dans l'ordre attendu.
_COLONNES_FIXES = (
    "Date_hab", "Observateur", "Description", "Nb_Habitat",
    "EtatConser", "Enjeu", "Comment", "Source", "Ref_Biblio",
    "SHAPE_Leng", "SHAPE_Area",
)
#: Colonnes du gabarit répétées à chaque rang de la mosaïque. `Rec` en fait
#: partie : le gabarit reçu l'oubliait au rang 2, pas la vue.
_COLONNES_PAR_RANG = (
    "Syntaxon", "CodeEUNIS", "NomEUNIS", "CodeCB", "NomCB",
    "CodeN2000", "NomN2000", "Rec",
)


def _lire():
    with open(_SCRIPT, encoding="utf-8") as fh:
        return fh.read()


def _gabarit(tag, script):
    """Le texte entre deux `$tag$` — un des trois modèles du bloc `DO`."""
    return re.search(r"\$%s\$(.*?)\$%s\$" % (tag, tag), script, re.DOTALL).group(1)


def _format(gabarit, *args):
    """`format()` de PostgreSQL, réduit à ce que le script emploie.

    `%n$s` positionnel et `%%` littéral : rien d'autre n'est utilisé, et une
    approximation plus large donnerait un faux sentiment de couverture.
    """
    rendu = re.sub(r"%(\d+)\$s", lambda m: str(args[int(m.group(1)) - 1]), gabarit)
    return rendu.replace("%%", "%")


def _vue_generee(n_blocs, script=None):
    """Rejoue la boucle du bloc `DO` et rend le CREATE VIEW qu'il exécuterait."""
    script = script or _lire()
    colonnes, jointures = "", ""
    for i in range(1, n_blocs + 1):
        colonnes += _format(_gabarit("c", script), i)
        if i > 1:
            jointures += _format(_gabarit("j", script), i)
    return _format(_gabarit("v", script),
                   "gn_exports.v_habitats_mosaique", colonnes, jointures)


def test_la_vue_est_supprimee_avant_d_etre_recreee():
    """Le nombre de colonnes change d'une génération à l'autre.

    C'est la raison d'être du DROP, et elle est propre à cette vue : quand une
    station plus riche apparaît, la vue régénérée a huit colonnes de plus.
    `CREATE OR REPLACE VIEW` refuse d'en ajouter ailleurs qu'à la fin — il
    échouerait sur toute mosaïque insérée avant les colonnes de queue.
    """
    script = _lire()
    assert script.index("DROP VIEW IF EXISTS") < script.index("CREATE VIEW %1$s AS")


def test_le_gabarit_est_complet_a_chaque_rang():
    vue = _vue_generee(7)
    for i in range(1, 8):
        for colonne in _COLONNES_PAR_RANG:
            assert '"%s_%d"' % (colonne, i) in vue, (colonne, i)
    for colonne in _COLONNES_FIXES:
        assert '"%s"' % colonne in vue, colonne
    assert " AS fid," in vue, "clé primaire de l'export GeoNature"
    assert " AS geom_local" in vue


def test_le_nombre_de_blocs_suit_le_parametre():
    """Ni colonne de trop, ni colonne manquante : le gabarit est exact."""
    vue = _vue_generee(5)
    assert '"Syntaxon_5"' in vue
    assert '"Syntaxon_6"' not in vue
    assert vue.count("LEFT JOIN hab h") == 4, "un JOIN par rang, sauf le rang 1"


def test_chaque_rang_lit_bien_son_propre_alias():
    """Un rang qui lirait l'alias d'un autre recopierait ses habitats.

    L'erreur ne se voit pas à la relecture — les colonnes sont remplies, mais
    d'une valeur juste au mauvais rang — et se propage telle quelle dans le
    livrable.
    """
    for ligne in _vue_generee(9).splitlines():
        alias = set(re.findall(r"\bh(\d+)\.", ligne))
        rang = re.search(r'AS "(?:\w+?)_(\d+)"\s*,?$', ligne)
        if rang and alias:
            assert alias == {rang.group(1)}, ligne.strip()


def test_le_rang_1_est_l_habitat_dominant():
    """La troncature par le plafond doit sacrifier les MOINS recouvrants."""
    vue = _vue_generee(5)
    assert "ORDER BY v.recouvrement_pct DESC NULLS LAST" in vue


def test_les_stations_sans_habitat_restent_exportees():
    """Elles portent une géométrie et un commentaire : elles valent d'être livrées.

    `count(colonne)` ignore les NULL là où `count(*)` compterait 1 : c'est ce
    qui distingue « aucun habitat » de « un habitat ».
    """
    vue = _vue_generee(5)
    assert "count(v.id_habitat) OVER (PARTITION BY v.id_station)" in vue
    assert "count(*)" not in vue


def test_la_cte_n_emporte_que_les_colonnes_qu_elle_utilise():
    """`v.*` ferait payer le gabarit pour tout ce qu'il n'exporte pas.

    Ce que la CTE ne demande pas, le planificateur ne le calcule pas : les
    Cahiers d'habitats, les sept nomenclatures, le numérisateur et la
    sous-requête `habitat_pee` sortent du plan. La liste explicite est donc
    fonctionnelle, pas cosmétique — mais elle ne tient que si personne n'y
    ajoute une colonne « au cas où », d'où la vérification en deux sens.
    """
    vue = _vue_generee(5)
    # Les commentaires citent `v.*` pour dire pourquoi il est écarté.
    code = "\n".join(re.sub(r"--.*$", "", l) for l in vue.split("\n"))
    cte = code[code.index("WITH hab AS MATERIALIZED"):code.index("row_number() OVER")]
    assert "v.*" not in cte

    projetees = re.findall(r"\bv\.(\w+),", cte)
    assert len(projetees) > 15, "la projection explicite a disparu"
    for colonne in projetees:
        usages = len(re.findall(r"\.%s\b" % colonne, vue))
        assert usages > 1, "colonne projetée mais jamais lue : %s" % colonne


def test_la_cte_est_materialisee():
    """Elle est relue une fois par bloc : sans cela, `v_occhab_complet` aussi.

    C'est la vue la plus coûteuse de l'export ; la recalculer huit fois par
    ligne l'a déjà fait tomber en 502 derrière le reverse-proxy (cf.
    `test_sql_script`).
    """
    assert "WITH hab AS MATERIALIZED (" in _vue_generee(5)


def test_le_bloc_ana_eval_ne_fuit_pas_dans_le_livrable():
    """Le destinataire recevrait du JSON technique dans un champ de texte libre."""
    vue = _vue_generee(5)
    assert r"'\[ANA-EVAL\].*\[/ANA-EVAL\]'" in vue


def test_le_depassement_du_plafond_est_signale():
    """Tronquer une mosaïque en silence livrerait un fichier faux sans le dire."""
    script = _lire()
    assert "RAISE WARNING" in script
    assert '"Nb_Habitat"' in _vue_generee(5), (
        "le compte réel des habitats est le seul témoin d'une troncature"
    )


def test_la_geometrie_est_surfacique_et_en_lambert_93():
    """Le gabarit ne connaît que le polygone ; une station ponctuelle est tamponnée."""
    vue = _vue_generee(5)
    assert "st_buffer(s.geom_local, 5)" in vue
    assert vue.count("geometry(MultiPolygon, 2154)") == 2, "les deux branches du CASE"


def test_les_libelles_sont_ceux_du_referentiel_ana():
    """Fondre Excellent et Bon en « Favorable » perdrait une information.

    L'échelle du rapportage N2000 est plus grossière que la saisie : la
    conversion est à faire par qui restitue, pas par la vue, car elle ne se
    remonte pas.
    """
    import referentiels as ref  # `src/processing` est au chemin (cf. conftest)

    vue = _vue_generee(5)
    for code, libelle in ref.ETATS_CONSERVATION + ref.NIVEAUX_ENJEU:
        assert "WHEN '%s'" % code in vue, code
        assert "'%s'" % libelle in vue, libelle
