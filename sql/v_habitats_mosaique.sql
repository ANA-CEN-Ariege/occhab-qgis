-- SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- ============================================================================
--  OccHab GeoNature — vue d'export « v_habitats_mosaique »
-- ============================================================================
--
--  À QUOI ÇA SERT
--  Restituer les habitats au gabarit à COLONNES PLATES attendu par les
--  donneurs d'ordre : une ligne par STATION, et la mosaïque dépliée en autant
--  de blocs `Syntaxon_n / CodeEUNIS_n / NomEUNIS_n / CodeCB_n / NomCB_n /
--  CodeN2000_n / NomN2000_n / Rec_n` qu'il y a d'habitats. Géométrie en
--  MultiPolygon Lambert 93 (2154), prête pour un shapefile ou un GeoPackage.
--
--  Le pivot reste `v_occhab_complet` — une ligne par habitat — et la présente
--  vue la relit : poser `sql/v_occhab_complet.sql` d'abord.
--
--  Le plugin sait la charger (« Cartographier… ▸ Charger un export du
--  serveur »), mais TELLE QUELLE : couche brute, sans découpe des mosaïques
--  ni couleur par habitat. Ces représentations lisent les colonnes de
--  `v_occhab_complet`, que l'aplatissement en colonnes fait disparaître — il
--  n'y a plus une ligne par habitat à colorier. Pour cartographier, prenez
--  l'autre vue ; celle-ci sert à LIVRER.
--
--  POURQUOI ELLE RELIT `v_occhab_complet` AU LIEU D'ÊTRE AUTONOME
--  Parce que la partie coûteuse à écrire n'est pas l'aplatissement en colonnes
--  — c'est ce qu'il y a DANS les colonnes. Un `CodeEUNIS_n` juste suppose de
--  savoir que l'arbitrage manuel prime sur la correspondance calculée, que le
--  bloc ANA-EVAL ne porte plus que le `cd_hab` depuis la 0.11.0 (les 500
--  caractères de `technical_precision` ne suffisaient plus à quatre
--  typologies), qu'un habitat déjà dans la typologie visée est son propre
--  équivalent, et que HABREF ne se joint JAMAIS sur autre chose que sa clé
--  primaire — sous peine du hachage de table entière qui avait effondré
--  l'export en 0.8.0. Recopier tout cela ici en ferait une seconde source de
--  vérité, qui dériverait de la première au premier correctif, et la copie
--  fautive serait celle que personne ne relit. Une vue autonome serait plus
--  courte à lire, pas plus propre.
--
--  Ce qu'on paie en échange se limite à un ordre de pose (`v_occhab_complet`
--  d'abord) — et non à du temps de calcul : la CTE ci-dessous n'énumère que
--  les vingt colonnes utiles, ce qui suffit à faire disparaître du plan tout
--  ce que le gabarit n'exporte pas.
--
--  POURQUOI UN SCRIPT QUI SE GÉNÈRE
--  Le nombre d'habitats par station est DYNAMIQUE, alors qu'une vue SQL a un
--  nombre de colonnes figé. Écrire 5 blocs en dur perdrait les mosaïques plus
--  riches, sans le moindre message ; en écrire 30 noierait le gabarit sous des
--  colonnes vides. Le bloc `DO` ci-dessous compte donc le maximum réellement
--  saisi et fabrique la vue à cette taille — plancher `MIN_BLOCS` pour que le
--  gabarit reste stable quand la base est encore pauvre, plafond `MAX_BLOCS`
--  pour qu'une station aberrante ne fasse pas exploser la vue.
--
--  ⚠ À RELANCER quand une station plus riche que le maximum précédent est
--  saisie. Rien ne le signale tout seul : la colonne `Nb_Habitat` porte le
--  compte RÉEL des habitats de la station, comparez-la au nombre de blocs.
--  Cette requête dit s'il est temps de rejouer le script :
--
--      SELECT max("Nb_Habitat") FROM gn_exports.v_habitats_mosaique;
--
--  OÙ L'EXÉCUTER
--  Sur la base GeoNature, avec un rôle capable de créer dans `gn_exports`.
--  DBeaver, psql, pgAdmin : d'un seul tenant. Se rejoue tel quel.
--
--  COMPATIBILITÉ — PostgreSQL 12 et plus (`CTE ... AS MATERIALIZED`).
--
--  DÉCLARATION DANS L'ADMIN GEONATURE (module Exports)
--  Schéma `gn_exports`, vue `v_habitats_mosaique`, colonne clé primaire
--  `fid`, champ géométrie `geom_local` (SRID 2154).
--
--  NOMS DE COLONNES : ceux du gabarit, à la lettre et à la casse — d'où les
--  guillemets doubles partout. Plusieurs dépassent les 10 caractères d'un
--  shapefile (`Observateur`, `Description`, `CodeEUNIS_1`…) : exportez en
--  GeoPackage, ou acceptez la troncature d'ESRI. Le gabarit reçu oubliait
--  `Rec_2` entre `NomN2000_2` et `Syntaxon_3` ; la vue le produit, un
--  recouvrement manquant sur le seul 2ᵉ habitat n'ayant pas de sens.
-- ============================================================================


DO $gen$
DECLARE
    -- --- Réglages ---------------------------------------------------------
    -- Nom de la vue : changez-le pour livrer plusieurs gabarits côte à côte
    -- (un par donneur d'ordre) sans qu'ils s'écrasent l'un l'autre.
    NOM_VUE   constant text := 'gn_exports.v_habitats_mosaique';
    -- Plancher : le gabarit reçu montre 5 blocs. En garder au moins autant
    -- évite qu'une base neuve produise un fichier aux colonnes absentes, que
    -- le destinataire lirait comme un fichier non conforme.
    MIN_BLOCS constant int := 5;
    -- Plafond : au-delà, la mosaïque relève de la saisie, pas du gabarit.
    -- Le dépassement est signalé par un WARNING, jamais tu.
    MAX_BLOCS constant int := 15;

    n_reel   int;
    n_blocs  int;
    colonnes text := '';
    jointures text := '';
    i int;
BEGIN
    -- Combien d'habitats porte la station la plus riche ?
    SELECT coalesce(max(c), 0) INTO n_reel
    FROM (SELECT count(*) AS c FROM pr_occhab.t_habitats GROUP BY id_station) t;

    n_blocs := greatest(MIN_BLOCS, least(MAX_BLOCS, n_reel));

    IF n_reel > MAX_BLOCS THEN
        RAISE WARNING 'v_habitats_mosaique : % habitats sur la station la plus '
                      'riche, plafond à % — les habitats les MOINS recouvrants '
                      'des mosaïques concernées ne seront pas exportés. Relevez '
                      'MAX_BLOCS et rejouez le script pour les inclure.',
                      n_reel, MAX_BLOCS;
    END IF;

    -- Un bloc de colonnes par rang de la mosaïque. Le rang 1 est l'habitat le
    -- plus recouvrant : c'est lui qui porte le suffixe `_1` du gabarit — là où
    -- l'export EDF laissait le premier bloc sans suffixe.
    FOR i IN 1..n_blocs LOOP
        colonnes := colonnes || format($c$
    coalesce(h%1$s.habitat_alliance, h%1$s.habitat, h%1$s.nom_cite)          AS "Syntaxon_%1$s",
    nullif(split_part(h%1$s.habitat_code_eunis,  ' ; ', 1), '')              AS "CodeEUNIS_%1$s",
    nullif(split_part(h%1$s.habitat_nom_eunis,   ' ; ', 1), '')              AS "NomEUNIS_%1$s",
    nullif(split_part(h%1$s.habitat_code_corine, ' ; ', 1), '')              AS "CodeCB_%1$s",
    nullif(split_part(h%1$s.habitat_nom_corine,  ' ; ', 1), '')              AS "NomCB_%1$s",
    nullif(split_part(h%1$s.habitat_code_n2000,  ' ; ', 1), '')              AS "CodeN2000_%1$s",
    nullif(split_part(h%1$s.habitat_nom_n2000,   ' ; ', 1), '')              AS "NomN2000_%1$s",
    h%1$s.recouvrement_pct                                                   AS "Rec_%1$s",$c$, i);

        -- Le rang 1 porte la ligne (c'est le FROM) ; les suivants s'y
        -- rattachent en LEFT JOIN, absents pour une station non mosaïquée.
        IF i > 1 THEN
            jointures := jointures || format($j$
     LEFT JOIN hab h%1$s ON h%1$s.id_station = h1.id_station AND h%1$s.rang = %1$s$j$, i);
        END IF;
    END LOOP;

    EXECUTE format('DROP VIEW IF EXISTS %s', NOM_VUE);

    EXECUTE format($v$
CREATE VIEW %1$s AS
-- MATERIALIZED, et pas par hasard : la CTE est relue une fois par bloc de la
-- mosaïque, plus une fois pour les remarques. Sans elle, `v_occhab_complet`
-- — la vue la plus coûteuse de l'export — serait recalculée autant de fois.
WITH hab AS MATERIALIZED (
    -- Les colonnes sont ÉNUMÉRÉES, jamais `v.*`, et ce n'est pas de la
    -- coquetterie. Ce que la CTE ne demande pas, le planificateur ne le calcule
    -- pas : les Cahiers d'habitats (deux jointures), les sept nomenclatures, le
    -- numérisateur et la sous-requête `habitat_pee` — un `jsonb_array_elements`
    -- par ligne — disparaissent du plan, leurs jointures étant toutes prouvées
    -- non duplicantes par un index unique. `v.*` les ramènerait toutes, et les
    -- ferait en plus matérialiser par la CTE, colonnes inutiles comprises.
    SELECT v.id_station,
           v.id_habitat,
           v.id_dataset,
           v.date_min,
           v.date_max,
           v.observateurs,
           v.nom_cite,
           v.habitat,
           v.habitat_alliance,
           v.habitat_code_eunis,
           v.habitat_nom_eunis,
           v.habitat_code_corine,
           v.habitat_nom_corine,
           v.habitat_code_n2000,
           v.habitat_nom_n2000,
           v.recouvrement_pct,
           v.habitat_remarque,
           v.station_etat_conservation,
           v.habitat_etat_conservation,
           v.station_niveau_enjeu,
           v.habitat_niveau_enjeu,
           v.station_nature_observation,
           row_number() OVER (PARTITION BY v.id_station
                              ORDER BY v.recouvrement_pct DESC NULLS LAST,
                                       v.id_habitat)          AS rang,
           -- count(colonne) ignore les NULL : une station SANS habitat compte
           -- 0, tout en gardant sa ligne dans l'export (elle a une géométrie
           -- et un commentaire, qui valent d'être livrés).
           count(v.id_habitat) OVER (PARTITION BY v.id_station) AS nb_habitats
    FROM gn_exports.v_occhab_complet v
)
SELECT
    -- Clé primaire de l'export GeoNature : une ligne par station, donc
    -- `id_station` suffit — contrairement à v_occhab_complet et son id_ligne.
    h1.id_station                                                            AS fid,
    h1.date_min::date                                                        AS "Date_hab",
    left(h1.observateurs, 100)                                               AS "Observateur",
    -- Description : le commentaire de la STATION, débarrassé du bloc ANA-EVAL
    -- que le plugin y range. Sans ce nettoyage, le destinataire recevrait du
    -- JSON technique dans un champ de texte libre.
    left(nullif(btrim(regexp_replace(coalesce(s.comment, ''),
                                     '\[ANA-EVAL\].*\[/ANA-EVAL\]', '', 'g')), ''),
         1000)                                                               AS "Description",
    -- Compte RÉEL des habitats, y compris au-delà du nombre de blocs : c'est
    -- le seul témoin d'une mosaïque tronquée par le plafond.
    h1.nb_habitats::int                                                      AS "Nb_Habitat",%2$s
    -- État de conservation et enjeu : ceux de la STATION d'abord, à défaut
    -- ceux de l'habitat dominant. Libellés du référentiel ANA tels quels
    -- (`processing.referentiels`), pas l'échelle du rapportage N2000 : la
    -- saisie distingue Excellent de Bon, les fondre en « Favorable » perdrait
    -- une information que personne ne peut reconstituer ensuite.
    CASE coalesce(h1.station_etat_conservation, h1.habitat_etat_conservation)
         WHEN 'excellent' THEN 'Excellent'
         WHEN 'bon'       THEN 'Bon'
         WHEN 'moyen'     THEN 'Moyen'
         WHEN 'mauvais'   THEN 'Mauvais'
         WHEN 'inconnu'   THEN 'Inconnu'
         ELSE NULL END                                                       AS "EtatConser",
    CASE coalesce(h1.station_niveau_enjeu, h1.habitat_niveau_enjeu)
         WHEN 'tres_fort' THEN 'Très fort'
         WHEN 'fort'      THEN 'Fort'
         WHEN 'moyen'     THEN 'Moyen'
         WHEN 'faible'    THEN 'Faible'
         WHEN 'aucun'     THEN 'Aucun'
         WHEN 'inconnu'   THEN 'Inconnu'
         ELSE NULL END                                                       AS "Enjeu",
    -- Comment : les remarques des habitats, dans l'ordre de la mosaïque et
    -- préfixées de leur rang — une remarque sans son habitat ne se rattache
    -- plus à rien une fois les colonnes aplaties.
    left(rem.txt, 1000)                                                      AS "Comment",
    -- Source : la nature d'observation ANA traduite dans la liste fermée du
    -- gabarit. « Inconnu », « Autre » et l'absence de saisie tombent tous sur
    -- « Ne sait pas », seule case que la liste leur laisse.
    CASE h1.station_nature_observation
         WHEN 'directe_avec_releve'  THEN 'Terrain - observation directe avec relevé'
         WHEN 'directe_sans_releve'  THEN 'Terrain - observation directe sans relevé'
         WHEN 'a_distance'           THEN 'Terrain - observation à distance'
         WHEN 'photo_interpretation' THEN 'Photo aérienne'
         ELSE 'Ne sait pas' END                                              AS "Source",
    -- Donnée de terrain : aucune référence bibliographique à produire. La
    -- colonne reste, le gabarit l'attend.
    NULL::text                                                               AS "Ref_Biblio",
    round(st_perimeter(gl.g)::numeric, 2)                                    AS "SHAPE_Leng",
    round(st_area(gl.g)::numeric, 2)                                         AS "SHAPE_Area",
    -- ---- Colonnes TECHNIQUES, hors gabarit ----
    -- Elles portent les noms que la route `GET /exports/api/<id>` attend, et
    -- non ceux du gabarit : le module Exports filtre SUR LES COLONNES DE LA
    -- VUE, et un filtre portant sur une colonne absente est ignoré EN SILENCE.
    -- Sans elles, « Charger un export du serveur » croirait tenir le JDD et
    -- l'année demandés alors qu'il aurait rapatrié l'export entier. Trois
    -- colonnes en minuscules à décocher au moment de livrer, contre un
    -- filtrage qui ment : le choix est vite fait.
    h1.id_dataset                                                            AS id_dataset,
    h1.date_min                                                              AS date_min,
    h1.date_max                                                              AS date_max,
    gl.g                                                                     AS geom_local
FROM hab h1
     JOIN pr_occhab.t_stations s ON s.id_station = h1.id_station%3$s
     -- Le gabarit ne connaît que le polygone. Une station saisie en point ou
     -- en ligne est donc tamponnée de 5 m plutôt qu'écartée : mieux vaut une
     -- surface conventionnelle, et signalée comme telle par sa forme, qu'une
     -- station absente du rendu.
     LEFT JOIN LATERAL (
         SELECT CASE WHEN st_dimension(s.geom_local) < 2
                     THEN st_multi(st_buffer(s.geom_local, 5))::geometry(MultiPolygon, 2154)
                     ELSE st_multi(s.geom_local)::geometry(MultiPolygon, 2154)
                END AS g
     ) gl ON true
     LEFT JOIN LATERAL (
         SELECT string_agg(format('%%s. %%s', hr.rang, btrim(hr.habitat_remarque)),
                           ' | ' ORDER BY hr.rang) AS txt
         FROM hab hr
         WHERE hr.id_station = h1.id_station
           AND nullif(btrim(hr.habitat_remarque), '') IS NOT NULL
     ) rem ON true
WHERE h1.rang = 1
$v$, NOM_VUE, colonnes, jointures);

    RAISE NOTICE 'v_habitats_mosaique : % blocs de mosaïque générés '
                 '(maximum saisi : %).', n_blocs, n_reel;
END
$gen$;


-- ----------------------------------------------------------------------------
-- Contrôle — la mosaïque tient-elle encore dans la vue ?
--
-- Rejouez ceci de temps en temps : si le compte dépasse le nombre de blocs
-- `Syntaxon_n` de la vue, des habitats sont sortis du cadre et il faut
-- relancer le script ci-dessus.
-- ----------------------------------------------------------------------------

-- SELECT max("Nb_Habitat") AS habitats_max FROM gn_exports.v_habitats_mosaique;
