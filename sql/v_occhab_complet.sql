-- SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- ============================================================================
--  OccHab GeoNature — vue d'export « v_occhab_complet »
-- ============================================================================
--
--  À QUOI ÇA SERT
--  Le plugin QGIS range ses champs métier (enjeu, état de conservation, zone
--  humide, recouvrement, champs Natura 2000) dans un bloc JSON inséré au
--  commentaire de la station ou à la précision technique de l'habitat. Ce
--  script rend ces champs lisibles en SQL, y ajoute les libellés des
--  nomenclatures et les équivalents CORINE / EUNIS / Cahiers d'habitats, et
--  publie le tout dans UNE vue à plat — une ligne par habitat, les stations
--  sans habitat comprises.
--
--  C'est cette vue, et elle seule, que le plugin sait recharger : menu
--  « Charger un export du serveur ». Déclarez-la dans l'administration
--  GeoNature (module Exports) avec `id_ligne` comme colonne clé primaire.
--
--  OÙ L'EXÉCUTER
--  Sur la base GeoNature, avec un rôle capable de créer dans `gn_exports` et
--  d'indexer `ref_habitats`. DBeaver, psql, pgAdmin : d'un seul tenant, les
--  étapes s'enchaînent dans l'ordre.
--
--  COMPATIBILITÉ — écrit et vérifié pour PostgreSQL 15
--  Rejoué d'un bout à l'autre sur PostgreSQL 15, deux fois de suite, sur des
--  tables HABREF et OccHab conformes au module Habref-api-module.
--
--  Le décodage du bloc passe par une FONCTION plpgsql et non par le prédicat
--  `IS JSON` : celui-ci n'existe qu'à partir de PostgreSQL 16, et sur une
--  version antérieure la requête échoue sur un `syntax error at or near
--  "JSON"` — sans rapport visible avec la cause. Rien ici ne demande mieux que
--  PostgreSQL 12. Le README (§6) donne la variante en ligne, sans fonction,
--  pour qui tourne en 16 ou plus.
--
--  RELANCER LE SCRIPT
--  Il est fait pour être rejoué tel quel : tout est en `CREATE OR REPLACE` ou
--  en `IF NOT EXISTS`. La vue, elle, est supprimée d'abord — `CREATE OR
--  REPLACE VIEW` refuse de changer le TYPE d'une colonne, ce qui bloquerait la
--  mise à jour d'une vue créée quand `zone_humide` était encore un booléen.
--
--  Le détail de chaque étape, et le pourquoi, sont dans le README (§6).
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Étape 1 — Deux index sur HABREF
--
-- Les correspondances se lisent dans les DEUX sens et remontent la hiérarchie ;
-- une instance GeoNature n'indexe en général que `cd_hab_entre`. Sans ces deux
-- index, chaque lecture inverse balaie la table entière, à chaque nœud et à
-- chaque saut.
-- ----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS habref_corresp_hab_cd_hab_sortie_idx
    ON ref_habitats.habref_corresp_hab (cd_hab_sortie);
CREATE INDEX IF NOT EXISTS habref_cd_hab_sup_idx
    ON ref_habitats.habref (cd_hab_sup);


-- ----------------------------------------------------------------------------
-- Étape 2 — Décoder le bloc ANA-EVAL
--
-- Le bloc est du JSON depuis la 0.5, mais les stations synchronisées plus tôt
-- portent encore l'ancien format `clé=valeur | clé=valeur`. La fonction lit les
-- deux et rend toujours un `jsonb`, jamais NULL : une station sans bloc, ou
-- avec un bloc abîmé, donne un objet vide plutôt qu'une erreur qui ferait
-- tomber l'export entier.
-- ----------------------------------------------------------------------------

-- Extraction du bloc ANA-EVAL en jsonb : accepte le format courant (JSON) ET
-- l'ancien (clé=valeur|…). Renvoie NULL — jamais une erreur — si le bloc est
-- absent ou a été trituré à la main dans l'interface web GeoNature : une vue qui
-- casse sur une donnée mal formée serait pire que l'absence d'information.
CREATE OR REPLACE FUNCTION gn_exports.ana_eval_json(txt text)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $fn$
DECLARE
    raw    text;
    parsed jsonb;
    pair   text;
    kv     text[];
    acc    jsonb := '{}'::jsonb;
BEGIN
    raw := trim(substring(txt from '\[ANA-EVAL\](.*)\[/ANA-EVAL\]'));
    IF raw IS NULL OR raw = '' THEN
        RETURN NULL;
    END IF;
    BEGIN                                   -- format courant : du JSON
        parsed := raw::jsonb;
        IF jsonb_typeof(parsed) = 'object' THEN
            RETURN parsed;
        END IF;
    EXCEPTION WHEN others THEN
        NULL;                               -- pas du JSON → ancien format
    END;
    FOREACH pair IN ARRAY string_to_array(raw, '|') LOOP
        kv := string_to_array(pair, '=');
        IF array_length(kv, 1) = 2 AND trim(kv[1]) <> '' AND trim(kv[2]) <> '' THEN
            acc := acc || jsonb_build_object(trim(kv[1]), trim(kv[2]));
        END IF;
    END LOOP;
    RETURN nullif(acc, '{}'::jsonb);
END $fn$;


-- ----------------------------------------------------------------------------
-- Étape 3 — Résoudre les correspondances entre typologies
--
-- HABREF ne relie pas tout à tout : d'un syntaxon PVF1 vers EUNIS, il faut
-- passer par les Cahiers d'habitats, et parfois remonter d'un niveau. Cette
-- fonction fait ces sauts, en gardant la trace du chemin parcouru (`rang`) pour
-- qu'on sache ce qu'on lit — une correspondance directe et une correspondance
-- en deux sauts n'ont pas la même valeur.
-- ----------------------------------------------------------------------------

-- Tout ce qui désigne le MÊME objet que `p_cd_hab` : sa lignée hiérarchique et
-- ses alias. Les alias sont les arêtes de correspondance qui ne changent pas de
-- typologie — un renvoi de synonymie ne traduit rien, il ne doit donc rien
-- coûter. Sans eux, les entrées PVF1 en double, celles sans code (« Mentho-
-- Juncion inflexi » à côté de « Mentho longifoliae-Juncion inflexi 3.0.1.0.5 »),
-- ne trouvent jamais rien.
-- Profondeurs : 2 crans vers le haut, 3 vers le bas. Trois, parce qu'un ordre
-- PVF2 n'atteint ses associations — qui seules portent les correspondances —
-- qu'au deuxième cran, et qu'un cran de marge coûte peu.
-- `o_dist` = éloignement hiérarchique, 0 pour l'habitat lui-même et ses alias.
CREATE OR REPLACE FUNCTION gn_exports.habref_famille(p_cd_hab integer)
RETURNS TABLE(o_cd_hab integer, o_dist integer)
LANGUAGE sql STABLE PARALLEL SAFE AS $fn$
    -- Les colonnes de sortie sont nommées `o_*` à dessein : un `RETURNS TABLE`
    -- déclare des paramètres OUT, et une sortie nommée `cd_hab` rendrait
    -- ambiguë chaque référence à `habref.cd_hab` dans le corps.
    WITH RECURSIVE haut AS (
        SELECT r.cd_hab, r.cd_hab_sup, 0 AS d
        FROM ref_habitats.habref r WHERE r.cd_hab = p_cd_hab
      UNION ALL
        SELECT s.cd_hab, s.cd_hab_sup, haut.d + 1
        FROM haut JOIN ref_habitats.habref s ON s.cd_hab = haut.cd_hab_sup
        WHERE haut.d < 2
    ), bas AS (
        SELECT r.cd_hab, 0 AS d
        FROM ref_habitats.habref r WHERE r.cd_hab = p_cd_hab
      UNION ALL
        SELECT f.cd_hab, bas.d + 1
        FROM bas JOIN ref_habitats.habref f ON f.cd_hab_sup = bas.cd_hab
        WHERE bas.d < 3
    ), noyau AS (
        SELECT cd_hab, d FROM haut
      UNION ALL
        SELECT cd_hab, d FROM bas
    )
    SELECT u.cd_hab, min(u.d)::int
    FROM (
        SELECT n.cd_hab, n.d FROM noyau n
      UNION ALL
        -- alias : l'arête existe, mais elle reste dans la typologie de départ
        SELECT b.cd_hab, n.d
        FROM noyau n
        JOIN ref_habitats.habref a ON a.cd_hab = n.cd_hab
        JOIN ref_habitats.habref_corresp_hab c
          ON (c.cd_hab_entre = n.cd_hab OR c.cd_hab_sortie = n.cd_hab)
         AND coalesce(c.validite, true)
        JOIN ref_habitats.habref b
          ON b.cd_hab = CASE WHEN c.cd_hab_entre = n.cd_hab THEN c.cd_hab_sortie
                             ELSE c.cd_hab_entre END
         AND b.cd_typo = a.cd_typo
    ) u
    GROUP BY u.cd_hab;
$fn$;

-- Équivalents d'un habitat dans une typologie donnée, avec un RANG qui dit ce
-- qu'ils valent. Le graphe des correspondances est parcouru dans les DEUX SENS
-- (`cd_hab_entre` comme `cd_hab_sortie`) et sur deux sauts au plus.
--   rang 10     correspondance directe, portée par le code saisi lui-même
--   rang 11/12  héritée d'un parent ou d'un descendant, à 1 ou 2 crans
--   rang 2x     obtenue en traversant une typologie intermédiaire
-- Seul le meilleur rang trouvé est rendu : on ne mélange pas dans une même
-- colonne une correspondance exacte et une déduction à deux sauts.
CREATE OR REPLACE FUNCTION gn_exports.habref_equivalents(p_cd_hab integer, p_typo text)
RETURNS TABLE(o_code character varying, o_nom character varying, o_rang integer)
LANGUAGE sql STABLE PARALLEL SAFE AS $fn$
    WITH RECURSIVE saut AS (
        SELECT f.o_cd_hab AS cd, f.o_dist AS dh, 0 AS n
        FROM gn_exports.habref_famille(p_cd_hab) f
      UNION ALL
        SELECT CASE WHEN c.cd_hab_entre = s.cd THEN c.cd_hab_sortie
                    ELSE c.cd_hab_entre END, s.dh, s.n + 1
        FROM saut s
        JOIN ref_habitats.habref_corresp_hab c
          ON (c.cd_hab_entre = s.cd OR c.cd_hab_sortie = s.cd)
         AND coalesce(c.validite, true)
        WHERE s.n < 2                       -- borne : sans elle, le parcours boucle
    )
    SELECT q.lb_code, q.lb_hab_fr, q.rang
    FROM (
        SELECT cible.lb_code, cible.lb_hab_fr,
               min(s.n * 10 + s.dh)::int              AS rang,
               -- `min()` de fenêtre par-dessus le `min()` d'agrégat : le meilleur
               -- rang de TOUT le résultat. Le cast se met autour du OVER, pas
               -- entre l'agrégat et lui — sinon « syntax error at or near OVER ».
               (min(min(s.n * 10 + s.dh)) OVER ())::int AS meilleur
        FROM saut s
        JOIN ref_habitats.habref cible  ON cible.cd_hab = s.cd
        JOIN ref_habitats.typoref t_cib ON t_cib.cd_typo = cible.cd_typo
        -- `s.n > 0` est indispensable : sans lui, la famille elle-même ressort.
        -- Un habitat CORINE se verrait attribuer son propre code parent comme
        -- « équivalent CORINE », ce qui n'a aucun sens — et que le CASE de la vue
        -- masquerait sans le corriger.
        WHERE s.n > 0
          AND s.cd <> p_cd_hab
          AND t_cib.lb_nom_typo = p_typo
          AND cible.lb_code IS NOT NULL     -- une cible sans code n'est pas restituable
        GROUP BY cible.lb_code, cible.lb_hab_fr
    ) q
    WHERE q.rang = q.meilleur;
$fn$;


-- ----------------------------------------------------------------------------
-- Étape 5 — Matérialiser les correspondances
--
-- Les fonctions de l'étape 3 sont évaluées PAR LIGNE et enchaînent deux
-- récursions. Mesuré sur une base à l'échelle du réel (41 000 habitats HABREF,
-- 2 000 habitats saisis) : 63 s sans les index de l'étape 1, 2,5 s avec eux,
-- 12 ms en joignant cette table. Sa construction coûte 5 s, une fois.
--
-- Ce n'est donc PAS une optimisation facultative : sans elle, l'export dépasse
-- la limite de temps d'un reverse-proxy dès que le jeu de données grossit, et
-- l'échec se présente en « 502 Proxy Error » sans rapport visible avec la cause.
-- Elle vivait dans le README, et le script s'arrêtait à l'étape 4 : qui exécutait
-- le script héritait de la version lente sans que rien ne le lui dise.
--
-- ⚠ ELLE SE PÉRIME. Elle est bâtie sur les `cd_hab` PRÉSENTS dans t_habitats :
-- un habitat saisi avec un code nouveau ressortira SANS correspondance tant
-- qu'elle n'est pas rafraîchie. D'où le REFRESH ci-dessous, à rejouer après une
-- campagne de saisie ou une mise à jour de HABREF — et la requête de contrôle
-- qui dit s'il y a des codes non couverts.
-- ----------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS gn_exports.mv_habref_equivalents CASCADE;
CREATE MATERIALIZED VIEW gn_exports.mv_habref_equivalents AS
SELECT h.cd_hab, typo.nom AS typologie,
       string_agg(e.o_code, ' ; ' ORDER BY e.o_code) AS codes,
       string_agg(e.o_nom,  ' ; ' ORDER BY e.o_code) AS noms,
       min(e.o_rang)                                 AS rang
FROM (SELECT DISTINCT cd_hab FROM pr_occhab.t_habitats WHERE cd_hab IS NOT NULL) h
CROSS JOIN (VALUES ('CORINE_biotopes'), ('EUNIS'),
                   ('Habitats_d''intérêt_communautaire'), ('Cahiers_d''habitats')) AS typo(nom)
CROSS JOIN LATERAL gn_exports.habref_equivalents(h.cd_hab, typo.nom) e
GROUP BY h.cd_hab, typo.nom;
-- UNIQUE, pour autoriser un jour REFRESH … CONCURRENTLY (sans verrou exclusif)
CREATE UNIQUE INDEX ON gn_exports.mv_habref_equivalents (cd_hab, typologie);

-- À REJOUER après une campagne de saisie ou une mise à jour de HABREF :
--     REFRESH MATERIALIZED VIEW CONCURRENTLY gn_exports.mv_habref_equivalents;
-- CONCURRENTLY ne pose aucun verrou sur les lecteurs, grâce à l'index unique
-- ci-dessus — un export en cours n'est pas interrompu. Il ne s'exécute PAS
-- dans une transaction : `psql -c`, jamais un bloc DO. Mesuré 9 s sur la base
-- de l'ANA. Le README §5 donne la tâche planifiée qui ne reconstruit que si un
-- code nouveau est apparu.
--
-- CONTRÔLE — codes saisis absents de la table (donc sans correspondance) :
--     SELECT DISTINCT h.cd_hab FROM pr_occhab.t_habitats h
--     WHERE h.cd_hab IS NOT NULL
--       AND NOT EXISTS (SELECT 1 FROM gn_exports.mv_habref_equivalents m
--                       WHERE m.cd_hab = h.cd_hab);


-- ----------------------------------------------------------------------------
-- Étape 6 — La vue
--
-- Une ligne par habitat, les stations sans habitat comprises. `id_ligne` est la
-- clé stable, unique et non nulle à déclarer côté GeoNature : l'API d'export
-- s'en sert pour ordonner la pagination, et sans elle des lignes se dupliquent
-- ou disparaissent d'une page à l'autre.
-- ----------------------------------------------------------------------------

-- `CREATE OR REPLACE` refuse de changer le TYPE d'une colonne existante. Une vue
-- créée avant que `zone_humide` passe de booléen à texte doit donc être
-- supprimée d'abord — l'export qui s'appuie dessus n'en est pas affecté, il
-- pointe sur le nom.
DROP VIEW IF EXISTS gn_exports.v_occhab_complet;
CREATE OR REPLACE VIEW gn_exports.v_occhab_complet AS
SELECT
    -- Clé stable, unique et NON NULLE : c'est elle à déclarer comme « colonne
    -- clé primaire » de l'export GeoNature. La vue n'en avait aucune —
    -- `id_habitat` est NULL pour une station sans habitat, `id_station` se
    -- répète en mosaïque — or l'API d'export s'en sert pour ordonner la
    -- pagination : sans clé unique, des lignes se dupliquent ou disparaissent
    -- d'une page à l'autre, sans le moindre message.
    s.id_station::text || '-' || coalesce(h.id_habitat::text, '0') AS id_ligne,
    -- ---- Station (libellés, pas d'id) ----
    s.id_station,
    s.station_name                                              AS nom_station,
    -- Gardé en plus du libellé : l'API d'export filtre sur les colonnes de la
    -- vue, et `id_dataset=<id>` est exact là où le nom du JDD demanderait un
    -- ILIKE approximatif.
    s.id_dataset,
    jdd.dataset_name                                            AS jeu_de_donnees,
    s.date_min,
    s.date_max,
    obs.observateurs,
    trim(coalesce(dig.prenom_role,'') || ' ' || coalesce(dig.nom_role,'')) AS numerisateur,
    s.altitude_min, s.altitude_max, s.depth_min, s.depth_max,
    s.area                                                      AS surface_m2,
    n_expo.label_default                                        AS exposition,
    n_surf.label_default                                        AS methode_calcul_surface,
    n_geo.label_default                                         AS nature_objet_geographique,
    n_sol.label_default                                         AS type_sol,
    n_mos.label_default                                         AS type_mosaique,
    -- ---- Station : bloc ANA-EVAL ----
    -- État MÉTIER : les brouillons sont synchronisés (la synchro sert aussi de
    -- sauvegarde), donc GeoNature contient du travail en cours. Filtrer sur
    -- `statut = 'valide'` pour ne consommer que des données abouties.
    coalesce(es.j ->> 'statut', 'brouillon')                    AS statut,
    -- Codes hérités convertis au vol, en miroir de `referentiels.ALIAS_*`.
    CASE es.j ->> 'enjeu' WHEN 'majeur' THEN 'tres_fort'
                          ELSE es.j ->> 'enjeu' END             AS station_niveau_enjeu,
    CASE es.j ->> 'etat_conservation' WHEN 'nd' THEN 'inconnu'
                          ELSE es.j ->> 'etat_conservation' END AS station_etat_conservation,
    -- Trois états depuis que « à vérifier » existe ; les stations antérieures
    -- portent encore le booléen de la case à cocher.
    CASE lower(es.j ->> 'zone_humide')
         WHEN 'true'  THEN 'oui'
         WHEN 'false' THEN 'non'
         ELSE es.j ->> 'zone_humide' END                        AS station_zone_humide,
    es.j ->> 'unite_vegetale'                                   AS station_unite_vegetale,
    es.j ->> 'nature_observation'                               AS station_nature_observation,
    -- ---- Habitat (libellés, pas d'id) ----
    h.id_habitat,
    h.cd_hab,
    h.nom_cite,
    hab.lb_hab_fr                                               AS habitat,
    hab.lb_code                                                 AS code_habref,
    t_hab.lb_nom_typo                                           AS typologie_habitat,
    -- Équivalents dans quatre typologies de référence. La correspondance part
    -- du `cd_hab`, JAMAIS du nom cité : celui-ci est du texte libre, que le
    -- botaniste peut avoir adapté au terrain. Si l'habitat est DÉJÀ dans la
    -- typologie visée, son propre code fait foi — la table de correspondance ne
    -- se référence pas elle-même — et le rang vaut alors 0.
    -- Le code SAISI prime sur le calculé. `habref_equivalents` ne connaît que le
    -- référentiel ; le botaniste, lui, tranche station par station — une même
    -- alliance ne se traduit pas pareil d'un polygone à l'autre. La colonne
    -- `habitat_*_source` dit d'où vient la valeur retenue :
    --   manuel        arbitré par un botaniste — le SEUL qui atteste d'un contrôle
    --   catalogue     repris du catalogue des végétations de l'Ariège
    --   habref        proposé par HABREF et accepté tel quel
    --   determination l'habitat est DÉJÀ dans cette typologie : son code fait foi
    --   (vide)        rien de saisi : c'est `habref_equivalents` qui a parlé, et
    --                 `habitat_*_rang` dit ce que vaut sa déduction
    -- `habitat_*_rang` ne vaut QUE pour une valeur calculée : dès qu'une valeur
    -- saisie l'emporte, il est mis à NULL. Le laisser rendre la distance de saut
    -- d'un code écarté ferait noter la qualité d'une valeur qui n'est pas celle
    -- de la colonne d'à côté.
    --
    -- ⚠ `habitat_nom_*` est NULL quand le code vient de la saisie. Ce n'est pas
    -- un oubli : résoudre ce libellé demanderait d'interroger `ref_habitats`
    -- pour chaque habitat, et c'est précisément ce qui a fait s'effondrer
    -- l'export en 0.8.0. La vue ne lit donc QUE ce que le bloc contient déjà —
    -- extractions jsonb sur `eh.j`, aucune table, aucune fonction à retour
    -- d'ensemble, aucune jointure de plus qu'en 0.7.1. Le code suffit à
    -- identifier l'habitat, et `habitat_*_source` dit d'où il vient.
    CASE WHEN eh.j -> 'corresp' -> 'CORINE_biotopes' ->> 'code' IS NOT NULL THEN eh.j -> 'corresp' -> 'CORINE_biotopes' ->> 'code'
         WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN hab.lb_code
         ELSE corine.codes END                                    AS habitat_code_corine,
    CASE WHEN eh.j -> 'corresp' -> 'CORINE_biotopes' ->> 'code' IS NOT NULL THEN NULL
         WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN hab.lb_hab_fr
         ELSE corine.noms END                                     AS habitat_nom_corine,
    CASE WHEN eh.j -> 'corresp' -> 'CORINE_biotopes' ->> 'code' IS NOT NULL
              THEN coalesce(eh.j -> 'corresp' -> 'CORINE_biotopes' ->> 'src', 'saisi')
         WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN 'determination'
         WHEN corine.codes IS NOT NULL THEN 'habref'
    END                                                         AS habitat_corine_source,
    CASE WHEN eh.j -> 'corresp' -> 'CORINE_biotopes' ->> 'code' IS NOT NULL THEN NULL
         WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN 0
         ELSE corine.rang END                                     AS habitat_corine_rang,
    CASE WHEN eh.j -> 'corresp' -> 'EUNIS' ->> 'code' IS NOT NULL THEN eh.j -> 'corresp' -> 'EUNIS' ->> 'code'
         WHEN t_hab.lb_nom_typo = 'EUNIS' THEN hab.lb_code
         ELSE eunis.codes END                                    AS habitat_code_eunis,
    CASE WHEN eh.j -> 'corresp' -> 'EUNIS' ->> 'code' IS NOT NULL THEN NULL
         WHEN t_hab.lb_nom_typo = 'EUNIS' THEN hab.lb_hab_fr
         ELSE eunis.noms END                                     AS habitat_nom_eunis,
    CASE WHEN eh.j -> 'corresp' -> 'EUNIS' ->> 'code' IS NOT NULL
              THEN coalesce(eh.j -> 'corresp' -> 'EUNIS' ->> 'src', 'saisi')
         WHEN t_hab.lb_nom_typo = 'EUNIS' THEN 'determination'
         WHEN eunis.codes IS NOT NULL THEN 'habref'
    END                                                         AS habitat_eunis_source,
    CASE WHEN eh.j -> 'corresp' -> 'EUNIS' ->> 'code' IS NOT NULL THEN NULL
         WHEN t_hab.lb_nom_typo = 'EUNIS' THEN 0
         ELSE eunis.rang END                                     AS habitat_eunis_rang,
    -- Natura 2000. Deux typologies, que « N2000 » confond souvent : le code de
    -- l'annexe I (`6510`) et sa déclinaison en Cahiers d'habitats (`6510-1`).
    -- ⚠ Ce sont des CANDIDATS À ARBITRER, pas une détermination : un code CORINE
    -- se décline fréquemment en plusieurs codes N2000 que seule la `lb_condition`
    -- distingue (« en situation montagnarde »…), et cette condition n'est pas
    -- ici : elle se demande au cas par cas, cf. « Et la condition qui distingue
    -- deux codes N2000 ? » en fin de section correspondances. À croiser avec
    -- `interet_communautaire` plus bas, qui est la nomenclature SAISIE : un
    -- désaccord entre les deux signale une erreur ou un cas à regarder.
    CASE WHEN eh.j -> 'corresp' -> 'Habitats_d''intérêt_communautaire' ->> 'code' IS NOT NULL THEN eh.j -> 'corresp' -> 'Habitats_d''intérêt_communautaire' ->> 'code'
         WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN hab.lb_code
         ELSE n2000.codes END                                    AS habitat_code_n2000,
    CASE WHEN eh.j -> 'corresp' -> 'Habitats_d''intérêt_communautaire' ->> 'code' IS NOT NULL THEN NULL
         WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN hab.lb_hab_fr
         ELSE n2000.noms END                                     AS habitat_nom_n2000,
    CASE WHEN eh.j -> 'corresp' -> 'Habitats_d''intérêt_communautaire' ->> 'code' IS NOT NULL
              THEN coalesce(eh.j -> 'corresp' -> 'Habitats_d''intérêt_communautaire' ->> 'src', 'saisi')
         WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN 'determination'
         WHEN n2000.codes IS NOT NULL THEN 'habref'
    END                                                         AS habitat_n2000_source,
    CASE WHEN eh.j -> 'corresp' -> 'Habitats_d''intérêt_communautaire' ->> 'code' IS NOT NULL THEN NULL
         WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN 0
         ELSE n2000.rang END                                     AS habitat_n2000_rang,
    CASE WHEN eh.j -> 'corresp' -> 'Cahiers_d''habitats' ->> 'code' IS NOT NULL THEN eh.j -> 'corresp' -> 'Cahiers_d''habitats' ->> 'code'
         WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN hab.lb_code
         ELSE cahiers.codes END                                    AS habitat_code_cahiers,
    CASE WHEN eh.j -> 'corresp' -> 'Cahiers_d''habitats' ->> 'code' IS NOT NULL THEN NULL
         WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN hab.lb_hab_fr
         ELSE cahiers.noms END                                     AS habitat_nom_cahiers,
    CASE WHEN eh.j -> 'corresp' -> 'Cahiers_d''habitats' ->> 'code' IS NOT NULL
              THEN coalesce(eh.j -> 'corresp' -> 'Cahiers_d''habitats' ->> 'src', 'saisi')
         WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN 'determination'
         WHEN cahiers.codes IS NOT NULL THEN 'habref'
    END                                                         AS habitat_cahiers_source,
    CASE WHEN eh.j -> 'corresp' -> 'Cahiers_d''habitats' ->> 'code' IS NOT NULL THEN NULL
         WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN 0
         ELSE cahiers.rang END                                     AS habitat_cahiers_rang,
    h.determiner                                                AS determinateur,
    n_tech.label_default                                        AS technique_collecte,
    n_det.label_default                                         AS type_determination,
    n_abond.label_default                                       AS abondance,
    n_sens.label_default                                        AS sensibilite,
    n_com.label_default                                         AS interet_communautaire,
    -- ---- Habitat : bloc ANA-EVAL ----
    -- `->>` rend du texte quel que soit le format d'origine (nombre en JSON,
    -- chaîne dans l'ancien format) : un seul cast couvre les deux.
    coalesce((eh.j ->> 'recouvrement')::numeric, h.recovery_percentage)
                                                                AS recouvrement_pct,
    CASE eh.j ->> 'enjeu' WHEN 'majeur' THEN 'tres_fort'
                          ELSE eh.j ->> 'enjeu' END             AS habitat_niveau_enjeu,
    CASE eh.j ->> 'etat_conservation' WHEN 'nd' THEN 'inconnu'
                          ELSE eh.j ->> 'etat_conservation' END AS habitat_etat_conservation,
    eh.j ->> 'dynamique'                                        AS habitat_dynamique,
    eh.j ->> 'restauration'                                     AS habitat_restauration,
    eh.j ->> 'typicite'                                         AS habitat_typicite,
    eh.j ->> 'critere'                                          AS habitat_critere,
    eh.j ->> 'remarque'                                         AS habitat_remarque,
    -- PEE : 3 taxons au plus, restitués en une chaîne « a, b, c ».
    (SELECT string_agg(t, ', ') FROM jsonb_array_elements_text(
        CASE WHEN jsonb_typeof(eh.j -> 'pee') = 'array'
             THEN eh.j -> 'pee' ELSE '[]'::jsonb END) AS t)     AS habitat_pee,
    -- Détermination hors HABREF : renseignée SEULEMENT quand `cd_hab` est une
    -- ANCRE — un code CORINE ou EUNIS emprunté faute d'entrée HABREF pour
    -- l'alliance déterminée. Vide ne veut donc pas dire « pas d'alliance », mais
    -- « le cd_hab est lui-même la détermination ».
    eh.j -> 'determination' ->> 'nom'                           AS habitat_alliance,
    eh.j -> 'determination' ->> 'ancre'                         AS habitat_ancre_typologie,
    s.geom_4326                                                 AS geom
FROM pr_occhab.t_stations s
LEFT JOIN pr_occhab.t_habitats h   ON h.id_station  = s.id_station
LEFT JOIN gn_meta.t_datasets   jdd ON jdd.id_dataset = s.id_dataset
LEFT JOIN utilisateurs.t_roles dig ON dig.id_role    = s.id_digitiser
LEFT JOIN ref_habitats.habref  hab ON hab.cd_hab     = h.cd_hab
LEFT JOIN ref_habitats.typoref t_hab ON t_hab.cd_typo = hab.cd_typo
LEFT JOIN ref_nomenclatures.t_nomenclatures n_expo  ON n_expo.id_nomenclature  = s.id_nomenclature_exposure
LEFT JOIN ref_nomenclatures.t_nomenclatures n_surf  ON n_surf.id_nomenclature  = s.id_nomenclature_area_surface_calculation
LEFT JOIN ref_nomenclatures.t_nomenclatures n_geo   ON n_geo.id_nomenclature   = s.id_nomenclature_geographic_object
LEFT JOIN ref_nomenclatures.t_nomenclatures n_sol   ON n_sol.id_nomenclature   = s.id_nomenclature_type_sol
LEFT JOIN ref_nomenclatures.t_nomenclatures n_mos   ON n_mos.id_nomenclature   = s.id_nomenclature_type_mosaique_habitat
LEFT JOIN ref_nomenclatures.t_nomenclatures n_tech  ON n_tech.id_nomenclature  = h.id_nomenclature_collection_technique
LEFT JOIN ref_nomenclatures.t_nomenclatures n_det   ON n_det.id_nomenclature   = h.id_nomenclature_determination_type
LEFT JOIN ref_nomenclatures.t_nomenclatures n_abond ON n_abond.id_nomenclature = h.id_nomenclature_abundance
-- ⚠ colonne réellement nommée « id_nomenclature_sensitvity » côté BDD (faute de frappe GeoNature)
LEFT JOIN ref_nomenclatures.t_nomenclatures n_sens  ON n_sens.id_nomenclature  = h.id_nomenclature_sensitvity
LEFT JOIN ref_nomenclatures.t_nomenclatures n_com   ON n_com.id_nomenclature   = h.id_nomenclature_community_interest
LEFT JOIN LATERAL (
    SELECT string_agg(
        trim(coalesce(r.prenom_role,'') || ' ' || coalesce(r.nom_role,'')),
        ', ' ORDER BY r.nom_role
    ) AS observateurs
    FROM pr_occhab.cor_station_observer cso
    JOIN utilisateurs.t_roles r ON r.id_role = cso.id_role
    WHERE cso.id_station = s.id_station
) obs ON true
-- Correspondances HABREF. Toute la logique est dans `habref_equivalents` ; il ne
-- reste ici qu'à agréger. Un habitat peut avoir PLUSIEURS équivalents : ils sont
-- joints par « ; ». Codes et noms sont tous deux ordonnés PAR LE CODE, donc la
-- 2ᵉ valeur d'une colonne correspond bien à la 2ᵉ de l'autre — ce que
-- `string_agg(DISTINCT …)` ne permettrait pas, Postgres n'acceptant alors
-- d'ordonner que sur l'expression agrégée elle-même.
--
-- Le libellé de typologie est comparé en ÉGALITÉ STRICTE dans la fonction,
-- jamais en ILIKE : `typoref` contient à la fois les typologies et les tables de
-- correspondance de HABREF, si bien qu'un `ILIKE '%eunis%'` ramasserait
-- ATL_EUNIS, BARCELONE_EUNIS, CB_EUNIS, CH_EUNIS, EUNIS_ATL, EUNIS_HIC,
-- HIC_EUNIS, MED_EUNIS, OSPAR_EUNIS, PVF2_EUNIS… soit une quinzaine de tables au
-- lieu de la typologie. De même, '%corine%' attraperait
-- « Habitats_CORINE_biotopes_de_La_Réunion ».
-- On filtre sur le nom plutôt que sur `cd_typo`, qui varie d'une instance à
-- l'autre — et dont un numéro recopié ne se relit pas.
-- ⚠ Les apostrophes des libellés se DOUBLENT : 'Cahiers_d''habitats'.
LEFT JOIN gn_exports.mv_habref_equivalents corine
       ON corine.cd_hab = h.cd_hab AND corine.typologie = 'CORINE_biotopes'
LEFT JOIN gn_exports.mv_habref_equivalents eunis
       ON eunis.cd_hab = h.cd_hab AND eunis.typologie = 'EUNIS'
LEFT JOIN gn_exports.mv_habref_equivalents n2000
       ON n2000.cd_hab = h.cd_hab AND n2000.typologie = 'Habitats_d''intérêt_communautaire'
LEFT JOIN gn_exports.mv_habref_equivalents cahiers
       ON cahiers.cd_hab = h.cd_hab AND cahiers.typologie = 'Cahiers_d''habitats'
-- Bloc ANA-EVAL décodé UNE SEULE FOIS par ligne, station puis habitat.
--
-- ⚠ `OFFSET 0` n'est pas décoratif : c'est une BARRIÈRE D'OPTIMISATION. Sans
-- elle, PostgreSQL aplatit ces sous-requêtes triviales et recopie l'appel de
-- fonction à CHAQUE référence — `eh.j` apparaît une quarantaine de fois dans la
-- vue, donc `ana_eval_json()` (plpgsql, expression régulière, boucle d'analyse)
-- serait exécutée autant de fois par ligne. Le commentaire ci-dessus promettait
-- « une seule fois par ligne » ; seule cette barrière le rend vrai. C'est la
-- part la plus coûteuse de la vue, et elle croît avec chaque champ ajouté au
-- bloc : la 0.8.0 est passée de 12 à 39 références sans que rien ne le signale.
LEFT JOIN LATERAL (
    SELECT gn_exports.ana_eval_json(s.comment) AS j OFFSET 0
) es ON true
LEFT JOIN LATERAL (
    SELECT gn_exports.ana_eval_json(h.technical_precision) AS j OFFSET 0
) eh ON true;
