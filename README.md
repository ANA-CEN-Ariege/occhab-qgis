# OccHab GeoNature — extension QGIS de saisie d'habitats

Extension QGIS pour saisir les données du module **OccHab** de GeoNature
directement depuis QGIS : saisie **hors-ligne** dans une base SQLite locale, puis
**synchronisation** (création / mise à jour / suppression) avec l'API GeoNature.
Développée par l'**ANA-CEN Ariège**.

- **Guide utilisateur** (installation + usage pas à pas) : [GUIDE_UTILISATEUR.md](GUIDE_UTILISATEUR.md)
- Dépôt : `https://github.com/ANA-CEN-Ariege/occhab-qgis`
- Modèle réel : `PnX-SI/GeoNature`, module `gn_module_occhab`, schéma `pr_occhab`.

---

## 1. Ce que fait le plugin

- **Saisie hors-ligne** de stations (spatiales) et de leurs habitats, stockée en
  SQLite local — utilisable sans connexion.
- **Numérisation native QGIS** de la géométrie (polygone / point), **reprise**
  d'une géométrie depuis une autre couche, avec accrochage ; **édition des
  sommets** d'une géométrie existante ; **ouverture d'une station au clic sur la
  carte** (double-clic ou outil *Identifier*).
- **Formulaires alignés** sur le formulaire web OccHab : `cd_hab` (recherche
  HABREF), nom cité, nomenclatures (technique de collecte, détermination,
  abondance, intérêt communautaire, exposition, méthode de calcul de surface,
  nature d'objet géographique), observateurs (multi-sélection d'utilisateurs).
- **Calculs automatiques** : surface du polygone (m², ellipsoïdal) et altitude
  min/max (MNT serveur, `POST /geo/altitude`).
- **Champs métier ANA-CEN Ariège** absents d'OccHab — niveau d'enjeu, état de conservation, recouvrement — saisis de façon normalisée et encodés dans les champs libres (voir §6).
- **Champs Natura 2000** de l'annexe 2 du cahier des charges d'Occitanie :
  typicité, dynamique, restauration, critère et PEE (habitat) ; unité végétale,
  nature de l'observation, échelle de numérisation (station). Voir §6.
- **Table attributaire** : toutes les stations d'un JDD, **une ligne par
  habitat**, éditable, avec application en masse sur une sélection (§6 bis).
- **Travail en brouillon** : chaque station porte un état métier
  *brouillon / validée*, distinct de son état de synchronisation (§6 bis).
- **Sélection partagée** entre les tableaux du plugin et la carte, dans les
  deux sens.
- **Synchronisation** : création (`POST /occhab/stations/`), mise à jour
  (`POST /occhab/stations/<id>/`) et **suppression** (`DELETE …`) avec garde-fous.
- **Contexte serveur** : affichage en lecture seule des stations déjà présentes
  dans un JDD, et **récupération** d'une station serveur en local pour l'éditer.
- **Carte** : les stations locales et serveur s'affichent sur le canevas, dans des
  groupes distincts, colorées par état.
- **Stockage & export** : emplacement du fichier SQLite visible, sauvegarde,
  export GeoPackage des saisies locales, et **export cartographie d'habitats** d'un
  JDD (vue à plat, une ligne par habitat, en GeoPackage + Shapefile).

---

## 2. Modèle de données

Aligné sur le schéma `pr_occhab` réel :

- **Station** (`t_stations`, spatiale) : géométrie (`geom_4326`), `id_dataset`
  (JDD, **obligatoire**), dates, observateurs, altitude/profondeur, surface,
  nomenclatures, commentaire.
- **Habitat** (`t_habitats`, **non-spatial**, 1..N par station) : `cd_hab`
  (référentiel **HABREF**, **obligatoire**), `nom_cite` (**obligatoire**),
  déterminateur, nomenclatures (technique de collecte **obligatoire**, type de
  détermination, abondance, sensibilité, intérêt communautaire), précision
  technique.
- **Observateurs** : relation N-N station ↔ utilisateurs (`cor_station_observer`).

> Il n'existe **pas** de champs `code_corine` / `code_eunis` libres : Corine
> Biotopes et EUNIS sont des typologies **au sein de HABREF**, référencées par
> `cd_hab`. La typologie est indiquée à la recherche (« CORINE biotopes 41.2 - … »).

### Base SQLite locale (miroir)

`occhab_local.db` : `t_stations`, `t_habitats`, `cor_station_observer`,
`t_sync_log`. Chaque station porte **deux états distincts** —
`sync_status` (`pending` / `synced` / `conflict` / `to_delete`, **technique**) et
`validation_status` (`brouillon` / `valide`, **métier**, cf. §6 bis) — plus un
indicateur `mine` (données créées par l'utilisateur, seules supprimables via le
plugin).

Le chargement d'une liste de stations avec leurs habitats et observateurs passe
par `get_stations_full()` : **3 requêtes au total**, et non 3 par station.

---

## 3. Architecture

**Offline-first.** Tout est d'abord écrit en SQLite local (connecté ou non). La
synchronisation pousse vers GeoNature à la demande (bouton **Synchroniser**).
Être « connecté » (authentifié) débloque le chargement des JDD, nomenclatures,
HABREF, observateurs, l'altitude, la couche serveur et la synchro.

```
Formulaires (PyQt)  ──►  SQLite local  ──►  Synchronisation  ──►  API GeoNature
       ▲                     │                                        │
       └──── récupération ◄──┴──────── couche serveur (contexte) ◄────┘
```

- **Couche « OccHab (local) »** : miroir éditable de la base locale, coloré par
  `sync_status`.
- **Couche « OccHab (serveur) »** : stations déjà sur GeoNature pour le JDD
  sélectionné, en **lecture seule** (bleu), placée sous le groupe local.

---

## 4. Installation

Ce dossier est dans le répertoire des extensions du profil QGIS
(`…/QGIS3/profiles/default/python/plugins/occhab`).

1. QGIS ▸ *Extensions ▸ Installer/Gérer les extensions ▸ Installées*.
2. Activer **OccHab GeoNature**.
3. Cliquer l'icône dans la barre d'outils pour ouvrir le dock.

Dépendance runtime : `requests` (fournie par QGIS sur la plupart des installations
OSGeo4W ; sinon `pip install requests` dans le Python de QGIS). PyQGIS/PyQt sont
fournis par QGIS — **ne pas** les installer via pip.

Pendant le développement : extension **Plugin Reloader** pour recharger sans
redémarrer QGIS.

---

## 5. Utilisation

### Organisation du dock
- **Connexion + JDD** : une barre compacte **repliable** (« changer » pour la
  déplier) ; elle se replie une fois le JDD choisi.
- **Mes stations** : le tableau de vos saisies locales (Habitat(s) / Date /
  **Statut · synchro**, ce dernier affichant **deux pastilles empilées** : l'état
  métier au-dessus, la synchronisation en dessous). **Au-dessus** du tableau, une
  barre d'action agit sur la **ligne sélectionnée** (grisée sans sélection) :
  *Éditer*, *Géométrie ▾* (redessiner / éditer, ou copier une entité d'une
  couche), *Zoom*, *Tableau* (toujours actif — ouvre la table attributaire) et
  *Supprimer* (isolé à droite). Les mêmes actions sont dans un **menu clic-droit**
  sur la ligne, et **double-cliquer** une ligne l'ouvre. En dessous :
  *＋ Nouvelle station ▾*.
  La **sélection est partagée avec la carte**, dans les deux sens.
- **Serveur** : *Synchroniser (N)*, *Rafraîchir*, et *Récupérer une station du
  serveur…* (depuis la carte, ou par recherche texte).
- Le panneau **défile** si son contenu dépasse la hauteur du dock.

Le bouton **Zoom** est adaptatif : station sélectionnée → zoom dessus ; sans
sélection → emprise du JDD (stations serveur, sinon locales).

**Depuis la carte** : double-cliquer une station locale (ou cliquer dessus avec
l'outil *Identifier des entités*) ouvre directement son formulaire.

### Connexion
Bouton **« Connexion GeoNature… »** : renseigner l'URL de l'API et choisir une
**configuration d'authentification QGIS** (méthode *Basic* : identifiant + mot de
passe GeoNature, stockés chiffrés par QGIS). Le plugin ne mémorise que l'URL et
l'`authcfg`, jamais le mot de passe.

### Choisir un JDD
La combo **JDD** liste les jeux de données ; elle est **éditable** : tapez pour
**filtrer par autocomplétion** (recherche « contient », insensible à la casse),
pratique quand les JDD sont nombreux. Elle **filtre** la vue (table + carte) et
sert de JDD par défaut aux nouvelles stations. « — Tous les JDD — » affiche tout.
Une fois connecté, la couche serveur du JDD s'affiche (+ un compteur) et le
canevas **zoome automatiquement** sur ses géométries s'il y en a (stations
serveur en priorité, sinon vos stations locales du JDD).
La case **« mes stations »** restreint la couche serveur aux stations dont vous
êtes le **numérisateur** (`id_digitiser`) ; décochée, elle affiche toutes les
stations du JDD que vos permissions GeoNature vous autorisent à voir.

### Saisir une station
1. **« ＋ Nouvelle station ▾ »** propose : *Dessiner un polygone* / *Dessiner un
   point* (tracé sur la carte, accrochage actif, clic droit pour terminer),
   *Copier la ou les entités sélectionnées (autre couche)* (reprend la géométrie
   d'une entité sélectionnée dans une autre couche, reprojetée en 4326 ;
   **sélection multiple → une station par entité**, métadonnées communes saisies
   une seule fois, nom laissé vide), *Dupliquer la station sélectionnée* (reprend
   attributs, dates, observateurs **et habitats** d'une station existante ;
   géométrie redessinée, jamais copiée — cf. `src/processing/duplicate.py`), ou
   *Sans géométrie* (à tracer plus tard).
   Surface et altitude se calculent automatiquement pour un polygone.
2. Remplir le **formulaire station**, à **deux niveaux** : l'**Essentiel** (JDD,
   nom, **observateurs**, dates, enjeu, état, commentaire) est visible ; le reste
   (altitude, profondeur, surface, exposition, type de sol, type de mosaïque,
   nature d'objet) est sous **« Détails »** (replié, déplié auto en édition s'il
   est rempli). Le champ **Observateur(s)** est à **autocomplétion** (déroulez ou
   tapez ; les retenus s'affichent dessous, retirables). **Ajouter un ou plusieurs
   habitats** (**facultatif** — on peut créer la station géométrie d'abord et la
   qualifier plus tard ; recherche HABREF sur le nom cité → remplit `cd_hab` ; la
   liste affiche le **% de recouvrement** de chacun). La technique de collecte est
   **« In situ »** par défaut, la sensibilité **« Non sensible »**.
   **Reprise de la saisie précédente** : les **observateurs** de la dernière station
   créée sont pré-remplis (persistés dans `last_entry.observers` de la
   configuration) et les **dates** reprises *dans la session QGIS courante* — au
   redémarrage on repart d'aujourd'hui, pour ne pas traîner une date périmée. Ce qui
   est repris est signalé sous les dates par une mention « ↺ … ».
3. La station apparaît dans **« Mes stations »**, identifiée par son habitat
   (« 41.2 - Chênaies-charmaies (+N) »), état *À synchroniser*.

### Éditer
Ouvrir une station : **« Éditer »** (barre au-dessus du tableau), **double-clic**
sur la ligne, **clic-droit → Éditer**, ou — sur la carte — **double-clic / clic
avec l'outil *Identifier***. Attributs et habitats modifiables (retirer un habitat
demande confirmation). **« Géométrie ▾ »** propose *Redessiner / éditer sur la
carte* (édition des sommets, ou nouveau tracé si aucune géométrie) ou *Copier
l'entité sélectionnée (autre couche)*. Toute édition repasse la station en
*À synchroniser*.

### Synchroniser
**« Synchroniser »** envoie les créations/mises à jour et applique les
suppressions marquées, puis recharge le contexte serveur. Récapitulatif affiché.

Avant d'envoyer une station déjà synchronisée, le plugin **vérifie qu'elle existe
toujours** sur GeoNature (`GET /occhab/stations/<id>/`) :
- **absente (HTTP 404)** — supprimée côté serveur : la mise à jour est impossible
  (le serveur répondrait HTTP 500). Le plugin propose de la **recréer** comme une
  nouvelle station (question posée **une fois** par synchronisation, valable pour
  toutes les stations concernées). Si vous refusez, elle reste **« à
  synchroniser »** en local et rien n'est envoyé ;
- **modifiée depuis** (empreinte serveur ≠ empreinte mémorisée) : **conflit**, la
  version serveur n'est pas écrasée ;
- **contrôle impossible** (réseau, serveur indisponible) : *fail-open*, l'envoi a
  lieu quand même.

Une suppression serveur portant sur une station **déjà absente** (HTTP 404) n'est
plus comptée en échec : la base locale est simplement nettoyée.

### Récupérer / éditer une station serveur
**« Récupérer une station du serveur… »** offre **deux chemins** :
- **Depuis la carte (sélection)** : sélectionner des stations dans la couche
  « OccHab — stations serveur » (outil de sélection QGIS). Si rien n'est
  sélectionné, le plugin **active la couche + l'outil** et affiche un bouton
  **« Récupérer la sélection »** — vous sélectionnez *après*, puis validez.
- **Chercher une station…** : un dialogue **liste/filtre** les stations serveur du
  JDD ; cochez celles à récupérer.

Elles sont importées en local (avec `id_station`/`id_habitat` → pas de doublon à
la resynchro) et deviennent éditables. Utile si la base locale est perdue ou
depuis une autre machine. Si une station sélectionnée est **déjà en local**, le
plugin propose de **remplacer la copie locale par la version du serveur**
(restauration ; les modifications locales non synchronisées sont alors écrasées).

### Supprimer
**« Supprimer »** distingue **deux gestes** — base
**locale** vs **serveur** — pour ne pas confondre « nettoyer mon poste » et
« supprimer la donnée sur GeoNature » :
- station **non synchronisée** → suppression locale immédiate (confirmation) ;
- station **déjà sur le serveur** → une boîte propose :
  - **Retirer de ma base locale** : enlève seulement la copie SQLite locale,
    **sans toucher GeoNature** (re-récupérable ensuite). Toujours disponible, y
    compris pour une station **créée par quelqu'un d'autre**. Des modifications
    locales non synchronisées seraient perdues (signalé).
  - **Supprimer sur GeoNature** : marque *À supprimer* (réversible en
    re-cliquant), appliquée à la synchro (`DELETE`). **Uniquement vos données**
    (`id_digitiser`) — masqué pour les stations d'autres utilisateurs.

**Multi-sélection** : sélectionnez plusieurs lignes (Ctrl/Maj) puis *Supprimer* →
une boîte groupée récapitule la sélection et propose *Retirer de ma base locale*
(toutes) ou *Supprimer sur GeoNature* (vos stations synchronisées uniquement, les
autres non touchées). Dans le formulaire station, la liste d'habitats accepte
aussi la multi-sélection (Ctrl/Maj) pour en **retirer plusieurs** d'un coup.

Ainsi, importer la station d'un collègue pour s'y référer puis la retirer de son
poste n'a aucun effet sur GeoNature. Garde-fous à la synchro : confirmation avec le nombre + les libellés,
**confirmation renforcée** (taper `SUPPRIMER`) au-delà de 3, et permissions
serveur. Retirer un habitat d'une station est déjà supprimé côté serveur à la
mise à jour.

### Stockage / export
Le pied du dock affiche l'emplacement de `occhab_local.db`. Bouton **« Base
locale… »** :
- **Ouvrir le dossier**, **Sauvegarder (copie .db)**, **Exporter en GeoPackage**
  (vos couches locales).
- **Exporter la cartographie du JDD (serveur)** : récupère **toutes** les stations
  du JDD sur GeoNature et les écrit en **vue à plat** (une ligne par habitat, avec
  libellés résolus — **nom d'habitat officiel HABREF** (`GET habref/habitat/<cd_hab>`)
  + code + nom cité, recouvrement, enjeu, état, observateurs, nomenclatures…) en
  **GeoPackage** *et* **Shapefile** (une couche / un fichier par type de géométrie).
- **Nettoyer les stations synchronisées anciennes** : retire du local les stations
  **synchronisées et non modifiées depuis plus de 6 mois** (`RETENTION_MONTHS`),
  puis `VACUUM`. Elles restent sur GeoNature et sont récupérables ; les stations
  **non synchronisées / en conflit / à supprimer** ne sont **jamais** touchées.
  Confirmation demandée, et rappel discret après une synchro si beaucoup
  s'accumulent. But : garder la liste locale courte et rapide.

---

## 6. Champs métier ANA (enjeu, état de conservation, zone humide, recouvrement)

OccHab n'a pas de champ natif exposé pour ces notions, et **le module ne gère pas
les champs additionnels de GeoNature**. Le seul canal d'écriture reste donc les
champs texte — `comment` (station) et `technical_precision` (habitat) — dans
lesquels on insère un **bloc balisé non destructif** contenant du **JSON** :

```
Texte libre saisi par l'utilisateur.

[ANA-EVAL] {"enjeu": "fort", "etat_conservation": "bon", "typicite": "bonne"} [/ANA-EVAL]
```

**Pourquoi JSON** (depuis 0.4.0 — voir « ancien format » plus bas) : les champs
Natura 2000 comprennent du texte libre (critère, remarque) et des listes (taxons
PEE). Le format historique `clé=valeur | clé=valeur` ne survivait pas à un `|`,
un `]` ou un retour à la ligne saisi par l'utilisateur. JSON échappe tout par
construction, et PostgreSQL le relit d'un **seul cast `::jsonb`** au lieu d'une
dizaine de `regexp_match`.

### Clés du bloc

| Clé | Où | Valeurs |
|---|---|---|
| `statut` | station | `brouillon` · `valide` — **état métier**, injecté au moment de l'envoi depuis la colonne locale `validation_status` (cf. §6 bis) |
| `enjeu` | station · habitat | `tres_fort` `fort` `moyen` `faible` `aucun` `inconnu` — extension **ANA**, hors cahier des charges N2000 |
| `etat_conservation` | station · habitat | `inconnu` `excellent` `bon` `moyen` `mauvais` — annexe 2, `id_et_cons` |
| `dynamique` | habitat | `inconnue` `stable` `progressive_lente` `regressive_lente` `progressive_rapide` `regressive_rapide` — `id_dynam` |
| `restauration` | habitat | `inconnu` `difficile` `impossible` `possible` `possible_avec_efforts` — `id_restaur` |
| `typicite` | habitat | `inconnue` `bonne` `moyenne` `mauvaise` — `id_typi` |
| `unite_vegetale` | station | `non_complexe` `mosaique_non_definie` `mosaique_temporelle` `mosaique_topographique` `mixte` — `id_uv` |
| `nature_observation` | station | `inconnu` `directe_avec_releve` `directe_sans_releve` `a_distance` `photo_interpretation` `autre` — `id_nat_obs` |
| `critere` · `remarque` | habitat | texte libre |
| `pee` | habitat | liste de **3 taxons au plus** (plantes exotiques envahissantes) |
| `zone_humide` | station | booléen |
| `recouvrement` | habitat | 0-100 ; **pré-sélectionne** l'Abondance (< 5 %, 5-25 %, 25-50 %, 50-75 %, > 75 %) **et** alimente le champ natif `recovery_percentage` |

Les codes internes sont **textuels** ; leur équivalent **numérique** attendu par
le rendu réglementaire est donné à part (`CDC_*` dans
`src/processing/referentiels.py`). Découpler les deux évite de migrer les données
saisies à chaque ajustement du format de restitution.

> `critere` et `pee` **ne figurent pas** dans le cahier des charges N2000
> d'Occitanie (vérifié sur les 28 pages : aucun champ « critère d'évaluation »,
> aucune mention d'espèce exotique envahissante). Ce sont des extensions ANA :
> aucune colonne ne les accueillera dans le rendu réglementaire.

### Garanties

- Le texte humain est **préservé** ; le bloc est **remplacé, jamais dupliqué**.
- Les valeurs sont validées **à l'écriture comme à la lecture** : un code hors
  référentiel n'est pas écrit et est ignoré à la relecture.
- Les clés sont **triées** : deux enregistrements d'une même saisie produisent le
  même texte, sinon la détection de conflit signalerait une divergence à chaque
  synchronisation.
- **Codes hérités convertis à la relecture** : `enjeu=majeur` → `tres_fort`,
  `etat_conservation=nd` → `inconnu` (`ALIAS_*` dans `referentiels.py`). Sans
  cela, rouvrir une telle station l'aurait affichée « non renseigné » et
  l'enregistrement aurait **effacé** la valeur.

### Ancien format (`clé=valeur`)

Les stations synchronisées avant 0.4.0 portent `[ANA-EVAL] enjeu=fort | … [/ANA-EVAL]`.
Le plugin **continue de le lire** et le convertit en JSON à la première
réécriture. Il n'y a donc **pas de migration à lancer** : la conversion se fait
station par station, au fil des éditions. Corollaire : tant qu'une station n'a
pas été rééditée, PostgreSQL voit encore l'ancien format — la fonction SQL
ci-dessous lit **les deux**.

### Ré-extraction côté PostgreSQL

**Limite assumée** : pas de contrainte au niveau base (la normalisation est
garantie par la saisie + la convention). Ré-extraction via **une seule vue à plat** :
**une ligne par habitat** (les stations sans habitat apparaissent aussi), toutes les
données station + habitat, **identifiants résolus en libellés** (JDD, habitat HABREF,
observateurs, numérisateur, nomenclatures) et champs ANA-EVAL extraits. La géométrie
(`geom`) est incluse → la vue est chargeable telle quelle dans QGIS.

> ⚠️ **Le SQL ci-dessous n'a pas été exécuté** (aucune instance PostgreSQL
> disponible au moment de la rédaction). À passer sur une base de test avant la
> production, en vérifiant en particulier l'échappement de l'expression régulière
> et le comportement de `eval_json` sur un bloc abîmé.

```sql
-- Extraction du bloc ANA-EVAL en jsonb : accepte le format courant (JSON) ET
-- l'ancien (clé=valeur|…). Renvoie NULL — jamais une erreur — si le bloc est
-- absent ou a été trituré à la main dans l'interface web GeoNature : une vue qui
-- casse sur une donnée mal formée serait pire que l'absence d'information.
CREATE SCHEMA IF NOT EXISTS ana_occhab;

CREATE OR REPLACE FUNCTION ana_occhab.eval_json(txt text)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
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
END $$;

-- Conversion des codes hérités, en miroir de `referentiels.ALIAS_*`.
CREATE OR REPLACE FUNCTION ana_occhab.enjeu_courant(code text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CASE code WHEN 'majeur' THEN 'tres_fort' ELSE code END $$;

CREATE OR REPLACE FUNCTION ana_occhab.etat_courant(code text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT CASE code WHEN 'nd' THEN 'inconnu' ELSE code END $$;

CREATE OR REPLACE VIEW gn_exports.v_occhab_complet AS
SELECT
    -- ---- Station (libellés, pas d'id) ----
    s.id_station,
    s.station_name                                              AS nom_station,
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
    ana_occhab.enjeu_courant(es.j ->> 'enjeu')                  AS station_niveau_enjeu,
    ana_occhab.etat_courant(es.j ->> 'etat_conservation')       AS station_etat_conservation,
    (es.j ->> 'zone_humide')::boolean                           AS station_zone_humide,
    es.j ->> 'unite_vegetale'                                   AS station_unite_vegetale,
    es.j ->> 'nature_observation'                               AS station_nature_observation,
    -- ---- Habitat (libellés, pas d'id) ----
    h.id_habitat,
    h.cd_hab,
    hab.lb_hab_fr                                               AS habitat,
    hab.lb_code                                                 AS code_habref,
    h.nom_cite,
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
    ana_occhab.enjeu_courant(eh.j ->> 'enjeu')                  AS habitat_niveau_enjeu,
    ana_occhab.etat_courant(eh.j ->> 'etat_conservation')       AS habitat_etat_conservation,
    eh.j ->> 'dynamique'                                        AS habitat_dynamique,
    eh.j ->> 'restauration'                                     AS habitat_restauration,
    eh.j ->> 'typicite'                                         AS habitat_typicite,
    eh.j ->> 'critere'                                          AS habitat_critere,
    eh.j ->> 'remarque'                                         AS habitat_remarque,
    -- PEE : 3 taxons au plus, restitués en une chaîne « a, b, c ».
    (SELECT string_agg(t, ', ') FROM jsonb_array_elements_text(
        CASE WHEN jsonb_typeof(eh.j -> 'pee') = 'array'
             THEN eh.j -> 'pee' ELSE '[]'::jsonb END) AS t)     AS habitat_pee,
    s.geom_4326                                                 AS geom
FROM pr_occhab.t_stations s
LEFT JOIN pr_occhab.t_habitats h   ON h.id_station  = s.id_station
LEFT JOIN gn_meta.t_datasets   jdd ON jdd.id_dataset = s.id_dataset
LEFT JOIN utilisateurs.t_roles dig ON dig.id_role    = s.id_digitiser
LEFT JOIN ref_habitats.habref  hab ON hab.cd_hab     = h.cd_hab
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
-- Bloc ANA-EVAL décodé une seule fois par ligne.
LEFT JOIN LATERAL (SELECT ana_occhab.eval_json(s.comment)             AS j) es ON true
LEFT JOIN LATERAL (SELECT ana_occhab.eval_json(h.technical_precision) AS j) eh ON true;
```

Si le volume l'exigeait un jour, `eval_json` étant `IMMUTABLE`, un index
d'expression GIN est possible :
`CREATE INDEX ON pr_occhab.t_habitats USING gin (ana_occhab.eval_json(technical_precision));`
Inutile à l'échelle de quelques milliers de stations — à ne poser que sur constat
de lenteur.

---

## 6 bis. Brouillon / validé, et la table attributaire

### Deux états, à ne pas confondre

- **`sync_status`** — état **technique** vis-à-vis du serveur (`pending`,
  `synced`, `conflict`, `to_delete`).
- **`validation_status`** — état **métier** du travail : `brouillon` ou `valide`
  (colonne locale `t_stations.validation_status`).

Ils sont **orthogonaux**. Les botanistes reviennent plusieurs fois sur une
station avant de la figer ; la synchronisation sert entre-temps de **sauvegarde
de fin de journée**, donc **un brouillon est bien envoyé sur GeoNature**.

Conséquence à connaître : **GeoNature contient du travail en cours**. La colonne
`statut` de la vue (§6) est là pour permettre de filtrer.

Comme OccHab n'a ni champ natif ni champs additionnels, le statut voyage dans le
bloc ANA-EVAL. La **colonne locale fait foi** ; le commentaire n'est que son
transport : il est injecté à la construction du payload et retiré à la relecture
(`api/payload.py`), pour éviter un stockage en double qui divergerait.

Reprise des bases existantes : à l'ajout de la colonne, les stations `synced`
deviennent `valide`, les autres `brouillon`. Une station **dupliquée** repart
toujours en brouillon.

### Table attributaire

**« Tableau »** (barre d'action du dock) ouvre une fenêtre listant les stations
du JDD courant, **une ligne par habitat** — la géométrie et les champs station
étant répétés sur les lignes sœurs.

- **Jeux de colonnes** : *Essentiel* / *Natura 2000* / *Tout* (25 colonnes ne
  tiennent pas à l'écran).
- **Filtres** statut, synchro, texte libre ; tri par colonne.
- **Sélection partagée avec la carte**, dans les deux sens (dock et table). La
  fenêtre est donc **non modale** : modale, elle bloquerait le canevas et rendrait
  la sélection carte impossible. Les boucles sont coupées par un verrou unique
  dans `StationLayerManager` — une sélection posée par le code ne notifie pas.
- **Édition en place**, éditeur adapté au type déclaré dans le registre de champs.
- Un champ **station** modifié sur une ligne l'est **pour toutes ses lignes
  sœurs** : les colonnes station sont teintées et le signalent en infobulle.
- **« Modifier les lignes sélectionnées… »** pousse les mêmes valeurs sur un lot ;
  chaque champ a une case à cocher, sinon valider écraserait tout avec du vide.
  Le bouton porte le nombre de lignes visées et reste grisé sans sélection : le
  libellé « Appliquer à la sélection… » ne disait pas ce qu'il appliquait.
  L'**identité de l'habitat** (`cd_hab` + `nom_cite`) s'y modifie via une
  **recherche HABREF** (composant `ui/habref_widget.py`, partagé avec le
  formulaire) : choisir un habitat coche et renseigne **les deux champs**, un
  code qui ne correspondrait plus à son nom étant une donnée incohérente.
  En revanche, l'édition **cellule par cellule** du nom cité reste du texte
  libre — c'est le champ « nom *cité* », qui peut légitimement s'écarter du
  libellé HABREF.
- **« Marquer comme validées »** passe les stations de brouillon à validé.
- Le registre distingue **`cellule`** (saisissable dans une cellule) de
  **`masse`** (modifiable en lot) : les observateurs, liste multi-valuée, sont
  `cellule=False` mais bien modifiables en masse. Les confondre les rendait
  intouchables partout.

**Garde-fous** — les modifications sont accumulées **en mémoire** ; rien n'est
écrit avant « Enregistrer ». Avant l'écriture : récapitulatif comptant les
**valeurs écrasées** (le seul chiffre qui signale une perte), contrôle des
recouvrements (somme = 100 % par polygone, exigence N2000 — avertissement, pas
blocage) et **copie horodatée de la base** (`*.avant-lot-*.db`), qui est
l'annulation réelle d'une modification portant sur des dizaines de stations.

**Retoucher une station validée la repasse en brouillon** — sauf si le statut a
été changé explicitement dans la même passe, sans quoi valider la remettrait
aussitôt en brouillon. ⚠️ Cette règle vaut dans la **table** ; dans le formulaire
station, la liste « Statut » est **autoritaire** (ce qu'elle affiche est
enregistré), pour ne pas empêcher de conserver une station validée qu'on rouvre.

**Architecture** — toute la logique risquée (propagation, suivi des
modifications, application en masse, rétrogradation) est dans
`processing/grille.py`, **pur et testé sans Qt** ; `ui/attribute_table.py` n'en
est qu'un adaptateur.

---

## 7. API GeoNature utilisée

| Besoin | Endpoint |
|---|---|
| Authentification | `POST /auth/login` (identifiants issus de l'auth QGIS) |
| JDD | `GET /meta/datasets?active=true&fields=modules` |
| Nomenclatures | `GET /nomenclatures/nomenclature/<code_type>`, `GET /occhab/defaultNomenclatures` |
| HABREF | `GET /habref/habitats/autocomplete?search_name=…`, `GET /habref/typo` |
| Observateurs | `GET /users/menu/<OBSERVER_LIST_ID>` |
| Altitude (MNT) | `POST /geo/altitude` |
| Stations (liste/contexte) | `GET /occhab/stations/?format=geojson&id_dataset=…` |
| Station (détail) | `GET /occhab/stations/<id>/` |
| Créer / mettre à jour | `POST /occhab/stations/` · `POST /occhab/stations/<id>/` |
| Supprimer | `DELETE /occhab/stations/<id>/` |

**Format de payload validé de bout en bout contre une vraie instance**
(demo.geonature.fr) : GeoJSON **Feature** (`geometry` GeoJSON + `properties`),
dates `%Y-%m-%d`, `observers = [{"id_role": …}]`, habitats imbriqués,
`id_station`/`id_habitat` préservés pour les mises à jour. Création, mise à jour,
suppression et récupération (aller-retour) confirmées.

---

## 8. Configuration (`config.json`)

Stocké dans le répertoire du profil QGIS (`…/occhab/config.json`). Réglages
avancés (non exposés dans l'UI) :

| Clé | Défaut | Rôle |
|---|---|---|
| `geonature.api_url` | — | URL de l'API (mémorisée à la connexion) |
| `geonature.authcfg` | — | id de config d'auth QGIS (mémorisée) |
| `geonature.verify_ssl` | `true` | Vérifier le certificat SSL |
| `geonature.id_application` | `0` | `id_application` au login (0 = auto) |
| `geonature.observer_list_id` | `1` | Menu d'observateurs (`OBSERVER_LIST_ID`) |
| `geonature.occhab_module_code` | `OCCHAB` | Code du module OccHab |
| `id_dataset` | — | JDD courant |
| `last_entry.observers` | `[]` | Observateurs de la dernière saisie (pré-remplissage) |
| `local_db.path` | auto | Chemin de la base SQLite |

---

## 9. Structure du projet

```
occhab/
├── metadata.txt              # métadonnées du plugin (nom, version…)
├── __init__.py               # classFactory (point d'entrée QGIS)
├── plugin.py                 # OccHabPlugin : menu/toolbar + dock
├── resources/icons/occhab.svg
└── src/
    ├── utils/        config.py · logger.py
    ├── database/     sqlite_local.py            # modèle station/habitat + CRUD
    ├── api/          geonature_client.py        # client REST GeoNature
    │                 payload.py                 # payload + parsing serveur (pur, testé)
    ├── processing/   referentiels.py            # vocabulaires fermés ANA + N2000 (pur, testé)
    │                 champs.py                  # registre des champs saisissables (pur, testé)
    │                 eval_fields.py             # bloc ANA-EVAL : encodage JSON (pur, testé)
    │                 grille.py                  # tampon d'édition en masse (pur, testé)
    │                 export.py                  # aplatissement cartographie (pur, testé)
    │                 duplicate.py               # modèle de duplication (pur, testé)
    │                 geometry.py                # WKT/GeoJSON, reprojection 4326
    └── ui/           dock_widget.py             # dock principal
                      attribute_table.py         # table stations × habitats (adaptateur Qt)
                      dialog_size.py             # dialogues défilants, bornés à l'écran
                      station_form.py · habitat_form.py · station_dialog.py
                      connection_dialog.py
                      map_tools.py               # capture + édition de géométrie
                      station_layers.py · server_layers.py   # couches carte
```

---

## 10. Développement

- Recharger : extension **Plugin Reloader**.
- Modules purs testables hors QGIS (aucune dépendance PyQGIS) :
  `referentiels`, `champs`, `eval_fields`, `grille`, `export`, `duplicate`,
  `payload`, `sqlite_local`. La règle : **tout ce qui peut corrompre des données
  en silence vit dans un module pur et testé** — l'interface n'en est qu'un
  adaptateur.
  Les modules `ui/*`, `geometry`,
  `station_layers`, `server_layers` dépendent de PyQGIS (testables dans QGIS).
- Le format d'API a été validé par des scripts contre `demo.geonature.fr`
  (création/màj/suppression/récupération réelles).

---

## 11. Limites connues / à confirmer

- **Surface / export GeoPackage / affichage des couches** : reposent sur des API
  QGIS non testables hors QGIS (`QgsDistanceArea`, `QgsVectorFileWriter`, OGR) —
  à confirmer au premier lancement. L'endpoint **altitude** et la synchro sont
  validés en direct.
- **Habitat saisi hors-ligne** : la technique de collecte (obligatoire côté
  serveur) reste vide jusqu'à la synchro, où elle est comblée par le défaut
  **« In situ »** (`cd_nomenclature = 1`) de la nomenclature GeoNature. Si cette
  valeur n'existe pas dans l'instance, on retombe sur le défaut d'instance.
- **Champs dépendant de l'instance** : « Type de sol » (TYPE_SOL), « Type de
  mosaïque » (MOSAIQUE_HAB) et « Sensibilité » (SENSIBILITE) ne s'affichent que
  si l'instance GeoNature fournit ces nomenclatures. Sur une instance qui ne les
  a pas (ex. TYPE_SOL absent → HTTP 404), le champ est simplement **masqué** (log
  en info, pas d'erreur).
- Une instance OccHab **très ancienne ou fortement personnalisée** pourrait
  diverger du format validé — comparer via `GET /occhab/stations/<id>/`.
- **Couches locales** (« OccHab (local) ») : couches **mémoire** en lecture
  seule, reconstruites à chaque rafraîchissement à partir de la base SQLite
  locale (qui reste la seule source de vérité). QGIS peut néanmoins les
  embarquer dans un `.qgz` sauvegardé ; à la réouverture, le plugin détecte
  les couches de même nom déjà présentes dans le groupe et les réutilise
  (plutôt que d'en recréer des doublons).
- **Couche serveur** (« OccHab (serveur) ») : contrairement à ce qu'indiquait
  une version précédente de cette note, il s'agit d'une **vraie couche
  fichier** (provider OGR, GeoJSON écrit dans le dossier de configuration de
  l'utilisateur), donc normalement persistable dans un `.qgz`. Son contenu
  est toutefois entièrement réécrit à chaque changement de JDD ou
  rafraîchissement ; ne pas s'appuyer sur son état sauvegardé comme source de
  vérité.
- Dans les deux cas, ces couches/groupes sont gérés automatiquement par le
  plugin (un message d'avertissement s'affiche une fois par session à leur
  première apparition) : ne pas les modifier, renommer ou déplacer
  manuellement dans le panneau Couches.

---

## Auteur & licence

- **Auteur** : Cédric Roy (ANA-CEN Ariège) — it@ariegenature.fr
- **Licence** : **GPL-3.0-or-later** (GNU GPL v3 ou ultérieure). Texte complet dans [LICENSE](LICENSE).

© 2026 Cédric Roy. Logiciel libre distribué **SANS AUCUNE GARANTIE**, redistribuable et
modifiable selon les termes de la GNU GPL v3 ou ultérieure. Chaque fichier source porte
l'en-tête `SPDX-License-Identifier: GPL-3.0-or-later`.
