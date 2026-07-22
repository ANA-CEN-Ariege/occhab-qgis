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
`t_sync_log`. Chaque station porte un `sync_status`
(`pending` / `synced` / `conflict` / `to_delete`) et un indicateur `mine` (données
créées par l'utilisateur, seules supprimables via le plugin).

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
  **État**). **Au-dessus** du tableau, une barre d'action agit sur la **ligne
  sélectionnée** (grisée sans sélection) : *Éditer*, *Géométrie ▾* (redessiner /
  éditer, ou copier une entité d'une couche), *Zoom*, et *Supprimer* (isolé à
  droite). Les mêmes actions sont dans un **menu clic-droit** sur la ligne, et
  **double-cliquer** une ligne l'ouvre. En dessous : *＋ Nouvelle station ▾*.
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
   *Copier l'entité sélectionnée (autre couche)* (reprend la géométrie d'une entité
   sélectionnée dans une autre couche, reprojetée en 4326), ou *Sans géométrie*
   (à tracer plus tard). Surface et altitude se calculent automatiquement pour un
   polygone.
2. Remplir le **formulaire station**, à **deux niveaux** : l'**Essentiel** (JDD,
   nom, **observateurs**, dates, enjeu, état, commentaire) est visible ; le reste
   (altitude, profondeur, surface, exposition, type de sol, type de mosaïque,
   nature d'objet) est sous **« Détails »** (replié, déplié auto en édition s'il
   est rempli). Le champ **Observateur(s)** est à **autocomplétion** (déroulez ou
   tapez ; les retenus s'affichent dessous, retirables). **Ajouter un ou plusieurs
   habitats** (recherche HABREF sur le nom cité → remplit `cd_hab` ; la liste
   affiche le **% de recouvrement** de chacun). La technique de collecte est
   **« In situ »** par défaut, la sensibilité **« Non sensible »**.
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
**« Supprimer »** (une station à la fois) distingue **deux gestes** — base
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
  libellés résolus — habitat, recouvrement, enjeu, état, observateurs…) en
  **GeoPackage** *et* **Shapefile** (une couche / un fichier par type de géométrie).

---

## 6. Champs métier ANA (enjeu, état de conservation, recouvrement)

OccHab n'a pas de champ natif exposé pour ces notions. On les stocke, de façon
**normalisée**, dans les champs libres OccHab — `comment` (station) et
`technical_precision` (habitat) — via un **bloc balisé non destructif** :

```
Texte libre saisi par l'utilisateur.

[ANA-EVAL] enjeu=fort | etat_conservation=moyen | recouvrement=3 [/ANA-EVAL]
```

- `enjeu` / `etat_conservation` : codes issus de référentiels fermés.
- `recouvrement` : pourcentage 0-100 ; il **pré-sélectionne automatiquement**
  l'Abondance (< 5 % → « très faible », 5-25 %, 25-50 %, 50-75 %, > 75 %) **et**
  alimente le champ natif OccHab `recovery_percentage` (en plus de l'encodage).
- Le texte humain est **préservé** ; le bloc est remplacé (jamais dupliqué) ;
  une clé vide n'est pas écrite. Code : `src/processing/eval_fields.py`.

**Limite assumée** : pas de contrainte au niveau base (la normalisation est
garantie par la saisie + la convention). Ré-extraction côté PostgreSQL via **une
seule vue à plat**  : **une ligne par habitat** (les stations sans habitat apparaissent aussi), toutes les données station + habitat, **identifiants résolus en libellés** (JDD, habitat HABREF, observateurs, numérisateur, nomenclatures) et champs ANA-EVAL extraits. La géométrie (`geom`) est incluse → la vue est chargeable telle quelle dans QGIS.

```sql

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
    (regexp_match(s.comment, 'enjeu=([a-z_]+)'))[1]             AS station_niveau_enjeu,
    (regexp_match(s.comment, 'etat_conservation=([a-z_]+)'))[1] AS station_etat_conservation,
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
    coalesce(
        (regexp_match(h.technical_precision, 'recouvrement=([0-9.]+)'))[1]::numeric,
        h.recovery_percentage
    )                                                           AS recouvrement_pct,
    (regexp_match(h.technical_precision, 'enjeu=([a-z_]+)'))[1]             AS habitat_niveau_enjeu,
    (regexp_match(h.technical_precision, 'etat_conservation=([a-z_]+)'))[1] AS habitat_etat_conservation,
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
) obs ON true;
```

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
    ├── processing/   eval_fields.py             # enjeu/état/recouvrement (pur, testé)
    │                 geometry.py                # WKT/GeoJSON, reprojection 4326
    └── ui/           dock_widget.py             # dock principal
                      station_form.py · habitat_form.py · station_dialog.py
                      connection_dialog.py
                      map_tools.py               # capture + édition de géométrie
                      station_layers.py · server_layers.py   # couches carte
```

---

## 10. Développement

- Recharger : extension **Plugin Reloader**.
- Modules purs testables hors QGIS (aucune dépendance PyQGIS) :
  `eval_fields`, `payload`, `sqlite_local`. Les modules `ui/*`, `geometry`,
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
- Les couches locales/serveur sont des **couches mémoire/temporaires** :
  reconstruites à l'ouverture du dock, non persistées dans le `.qgz`.

---

## Auteur & licence

- **Auteur** : Cédric Roy (ANA-CEN Ariège) — it@ariegenature.fr
- **Licence** : **GPL-3.0-or-later** (GNU GPL v3 ou ultérieure). Texte complet dans [LICENSE](LICENSE).

© 2026 Cédric Roy. Logiciel libre distribué **SANS AUCUNE GARANTIE**, redistribuable et
modifiable selon les termes de la GNU GPL v3 ou ultérieure. Chaque fichier source porte
l'en-tête `SPDX-License-Identifier: GPL-3.0-or-later`.
