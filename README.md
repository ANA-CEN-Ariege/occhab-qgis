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
   géométrie redessinée, jamais copiée — cf. `src/processing/duplicate.py`),
   *Dessiner un polygone avec les renseignements copiés* (voir « Recopier une
   station » ci-dessous), ou *Sans géométrie* (à tracer plus tard).
   Surface et altitude se calculent automatiquement pour un polygone.
2. Remplir le **formulaire station**, à **deux niveaux** : l'**Essentiel** (JDD,
   nom, **observateurs**, dates, unité végétale, nature de l'observation, enjeu,
   état, commentaire) est visible ; le reste (altitude, profondeur, surface,
   exposition, type de sol, type de mosaïque, nature d'objet, échelle de
   numérisation) est sous **« Détails »** (replié, déplié auto en édition s'il
   est rempli). Le champ **Observateur(s)** est à **autocomplétion** (déroulez ou
   tapez ; les retenus s'affichent dessous, retirables). **Ajouter un ou plusieurs
   habitats** (**facultatif** — on peut créer la station géométrie d'abord et la
   qualifier plus tard ; recherche HABREF sur le nom cité → remplit `cd_hab` ; la
   liste affiche le **% de recouvrement** de chacun). Le formulaire d'habitat
   présente d'abord ce qui se saisit à chaque fois (détermination, technique,
   recouvrement, enjeu, état de conservation, **critère d'évaluation** et
   **PEE**) ; **abondance** et **sensibilité** sont repliées en bas, la section
   s'ouvrant d'elle-même quand une valeur s'écarte du défaut d'instance. La
   technique de collecte est **« In situ »** par défaut, la sensibilité
   **« Non sensible »**.
   **Reprise de la saisie précédente** : les **observateurs** de la dernière station
   créée sont pré-remplis (persistés dans `last_entry.observers` de la
   configuration) et les **dates** reprises *dans la session QGIS courante* — au
   redémarrage on repart d'aujourd'hui, pour ne pas traîner une date périmée. Ce qui
   est repris est signalé sous les dates par une mention « ↺ … ». De même pour
   l'**habitat** (`last_entry.habitat`) : chaque nouvel habitat reprend les champs
   du dernier saisi — **sauf** nom cité, `cd_hab`, recouvrement et abondance, qui
   lui sont propres (`habitat_reprise`, cf. `src/processing/duplicate.py`).
3. La station apparaît dans **« Mes stations »**, identifiée par son habitat
   (« 41.2 - Chênaies-charmaies (+N) »), état *À synchroniser*.

### Recopier une station
Un même modèle (`station_template` / `paste_fields`) sert trois gestes :

- **clic droit → « Copier les renseignements »** met de côté JDD, dates,
  observateurs, attributs, commentaire et habitats d'une station (mémoire de la
  session QGIS) ;
- **clic droit → « Coller les renseignements »** les applique à la ou aux
  stations sélectionnées, **déjà tracées** : leur **géométrie**, leur **nom** et
  leur **statut** de validation sont conservés, leurs habitats **remplacés**
  (confirmation chiffrée avant écriture) ; elles repassent *À synchroniser* et
  l'auteur du collage devient `updated_by` ;
- **« Reprendre une station renseignée… »**, en haut du formulaire ouvert,
  recopie une station choisie dans une liste filtrable — sans rien enregistrer
  avant validation du formulaire.

L'identité (`id`, `id_station`, uuid SINP, empreinte serveur) et le drapeau
`mine` ne sont **jamais** copiés : une copie est une station neuve, dont on est
l'auteur.

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

> **Déclaration dans l'admin GeoNature** (module Exports) : schéma `gn_exports`,
> vue `v_occhab_complet`, **colonne clé primaire `id_ligne`**, champ géométrie
> `geom` (SRID 4326). La clé primaire est obligatoire et sert d'`ORDER BY` à la
> pagination de l'API — d'où la colonne `id_ligne` en tête de la vue.

**Aucun schéma à créer** : trois fonctions et une vue, toutes dans `gn_exports`.
`CREATE SCHEMA` demande des droits sur la base que l'administrateur GeoNature
n'accorde pas toujours ; poser les fonctions à côté de la vue n'exige que le
droit dont on a déjà besoin pour créer la vue.

**Cinq objets, à poser dans cet ordre.** Chacun est indépendant : on peut
s'arrêter après le 4 et avoir une vue qui marche, en acceptant qu'elle soit lente.

| | Objet | Rôle |
|---|---|---|
| 1 | deux index sur `ref_habitats` | sans eux, les correspondances rampent (facteur 25) |
| 2 | `gn_exports.ana_eval_json()` | décode le bloc ANA-EVAL, JSON courant ou format hérité |
| 3 | `habref_famille()` + `habref_equivalents()` | résolvent les correspondances entre typologies |
| 4 | `gn_exports.v_occhab_complet` | **la vue à déclarer** dans le module Exports |
| 5 | `gn_exports.mv_habref_equivalents` | facultative en droit, indispensable en pratique |

#### 1. Deux index sur HABREF

Les fonctions de l'étape 3 parcourent les correspondances **dans les deux sens**
et remontent la hiérarchie ; une instance GeoNature n'indexe en général que
`cd_hab_entre`. Sans ces deux index, chaque lecture inverse balaie la table
entière, à chaque nœud et à chaque saut — mesuré à l'étape 5.

```sql
CREATE INDEX IF NOT EXISTS habref_corresp_hab_cd_hab_sortie_idx
    ON ref_habitats.habref_corresp_hab (cd_hab_sortie);
CREATE INDEX IF NOT EXISTS habref_cd_hab_sup_idx
    ON ref_habitats.habref (cd_hab_sup);
```

#### 2. Décoder le bloc ANA-EVAL

> **Pourquoi une fonction et pas tout en ligne dans la vue ?** Parce qu'il faut
> pouvoir **rattraper l'erreur** d'un bloc abîmé — un commentaire retouché à la
> main dans l'interface web GeoNature — et que le SQL pur n'a pas de « cast qui
> échoue proprement » avant **PostgreSQL 16** et son prédicat `IS JSON`. Sur
> PG 15, une vue sans fonction s'arrête sur `invalid input syntax for type json`
> et **ne rend plus une seule ligne** ; pire, l'erreur ne se manifeste que si l'on
> demande une colonne décodée (un `count(*)` passe, le planificateur n'évaluant
> pas le `LATERAL`). Le bloc `EXCEPTION` du plpgsql est là pour ça.
>
> Si vous êtes en **PostgreSQL 16 ou plus** et préférez zéro fonction, remplacez
> les deux `LATERAL` du bas par la version en ligne donnée juste après.


```sql
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
```

**Variante sans fonction — PostgreSQL 16 minimum.** Si votre serveur est en 16 ou
plus et que vous tenez à n'avoir *que* la vue, supprimez la fonction et remplacez
les deux dernières lignes par ceci. `IS JSON OBJECT` écarte un bloc illisible sans
lever d'erreur ; le repli parcourt l'ancien format « clé=valeur | clé=valeur »
(une paire sans valeur, ou dont la valeur contient elle-même un « = », est
ignorée). Sur PostgreSQL 15 ou antérieur, cette variante échoue avec
`syntax error at or near "JSON"`.

```sql
LEFT JOIN LATERAL (
    SELECT CASE
             WHEN x.raw IS JSON OBJECT THEN x.raw::jsonb
             ELSE (SELECT jsonb_object_agg(trim(k.kv[1]), trim(k.kv[2]))
                     FROM unnest(string_to_array(x.raw, '|')) AS p,
                          LATERAL (SELECT string_to_array(p, '=') AS kv) k
                    WHERE array_length(k.kv, 1) = 2
                      AND trim(k.kv[1]) <> '' AND trim(k.kv[2]) <> '')
           END AS j
    FROM (SELECT nullif(trim(substring(s.comment
              from '\[ANA-EVAL\](.*)\[/ANA-EVAL\]')), '') AS raw) x
) es ON true
LEFT JOIN LATERAL (
    SELECT CASE
             WHEN x.raw IS JSON OBJECT THEN x.raw::jsonb
             ELSE (SELECT jsonb_object_agg(trim(k.kv[1]), trim(k.kv[2]))
                     FROM unnest(string_to_array(x.raw, '|')) AS p,
                          LATERAL (SELECT string_to_array(p, '=') AS kv) k
                    WHERE array_length(k.kv, 1) = 2
                      AND trim(k.kv[1]) <> '' AND trim(k.kv[2]) <> '')
           END AS j
    FROM (SELECT nullif(trim(substring(h.technical_precision
              from '\[ANA-EVAL\](.*)\[/ANA-EVAL\]')), '') AS raw) x
) eh ON true;
```

Si le volume l'exigeait un jour, `ana_eval_json` étant `IMMUTABLE`, un index
d'expression GIN est possible :
`CREATE INDEX ON pr_occhab.t_habitats USING gin (gn_exports.ana_eval_json(technical_precision));`
Inutile à l'échelle de quelques milliers de stations : à ne poser que sur constat
de lenteur, pas par précaution. À noter que la **variante sans fonction** en perd
la possibilité — son repli est une sous-requête, et PostgreSQL les refuse dans une
expression d'index (`cannot use subquery in index expression`, vérifié).

#### 3. Résoudre les correspondances entre typologies

Deux fonctions, et non un `JOIN`, parce que le graphe HABREF est **orienté**, que
ses correspondances sont accrochées à un **niveau hiérarchique** précis et qu'une
même unité y a souvent **plusieurs entrées**. Le détail de ces trois pièges — et
la matrice qui les révèle — est dans
[Correspondances entre typologies](#correspondances-entre-typologies-corine--cahiers-dhabitats--eunis)
juste après ; ici, le code.

```sql
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
```

#### 4. La vue

C'est elle qu'on déclare dans le module Exports. Une ligne par habitat, les
stations sans habitat comprises.

```sql
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
    (es.j ->> 'zone_humide')::boolean                           AS station_zone_humide,
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
    coalesce(
        CASE WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN hab.lb_code END,
        corine.codes
    )                                                           AS habitat_code_corine,
    coalesce(
        CASE WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN hab.lb_hab_fr END,
        corine.noms
    )                                                           AS habitat_nom_corine,
    CASE WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN 0
         ELSE corine.rang END                                   AS habitat_corine_rang,
    coalesce(
        CASE WHEN t_hab.lb_nom_typo = 'EUNIS' THEN hab.lb_code END,
        eunis.codes
    )                                                           AS habitat_code_eunis,
    coalesce(
        CASE WHEN t_hab.lb_nom_typo = 'EUNIS' THEN hab.lb_hab_fr END,
        eunis.noms
    )                                                           AS habitat_nom_eunis,
    CASE WHEN t_hab.lb_nom_typo = 'EUNIS' THEN 0
         ELSE eunis.rang END                                    AS habitat_eunis_rang,
    -- Natura 2000. Deux typologies, que « N2000 » confond souvent : le code de
    -- l'annexe I (`6510`) et sa déclinaison en Cahiers d'habitats (`6510-1`).
    -- ⚠ Ce sont des CANDIDATS À ARBITRER, pas une détermination : un code CORINE
    -- se décline fréquemment en plusieurs codes N2000 que seule la `lb_condition`
    -- distingue (« en situation montagnarde »…), et cette condition n'est pas
    -- ici : elle se demande au cas par cas, cf. « Et la condition qui distingue
    -- deux codes N2000 ? » en fin de section correspondances. À croiser avec
    -- `interet_communautaire` plus bas, qui est la nomenclature SAISIE : un
    -- désaccord entre les deux signale une erreur ou un cas à regarder.
    coalesce(
        CASE WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN hab.lb_code END,
        n2000.codes
    )                                                           AS habitat_code_n2000,
    coalesce(
        CASE WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN hab.lb_hab_fr END,
        n2000.noms
    )                                                           AS habitat_nom_n2000,
    CASE WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN 0
         ELSE n2000.rang END                                    AS habitat_n2000_rang,
    coalesce(
        CASE WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN hab.lb_code END,
        cahiers.codes
    )                                                           AS habitat_code_cahiers,
    coalesce(
        CASE WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN hab.lb_hab_fr END,
        cahiers.noms
    )                                                           AS habitat_nom_cahiers,
    CASE WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN 0
         ELSE cahiers.rang END                                  AS habitat_cahiers_rang,
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
LEFT JOIN LATERAL (
    SELECT string_agg(e.o_code, ' ; ' ORDER BY e.o_code) AS codes,
           string_agg(e.o_nom,  ' ; ' ORDER BY e.o_code) AS noms,
           min(e.o_rang)                                 AS rang
    FROM gn_exports.habref_equivalents(h.cd_hab, 'CORINE_biotopes') e
) corine ON true
LEFT JOIN LATERAL (
    SELECT string_agg(e.o_code, ' ; ' ORDER BY e.o_code) AS codes,
           string_agg(e.o_nom,  ' ; ' ORDER BY e.o_code) AS noms,
           min(e.o_rang)                                 AS rang
    FROM gn_exports.habref_equivalents(h.cd_hab, 'EUNIS') e
) eunis ON true
LEFT JOIN LATERAL (
    SELECT string_agg(e.o_code, ' ; ' ORDER BY e.o_code) AS codes,
           string_agg(e.o_nom,  ' ; ' ORDER BY e.o_code) AS noms,
           min(e.o_rang)                                 AS rang
    FROM gn_exports.habref_equivalents(h.cd_hab, 'Habitats_d''intérêt_communautaire') e
) n2000 ON true
LEFT JOIN LATERAL (
    SELECT string_agg(e.o_code, ' ; ' ORDER BY e.o_code) AS codes,
           string_agg(e.o_nom,  ' ; ' ORDER BY e.o_code) AS noms,
           min(e.o_rang)                                 AS rang
    FROM gn_exports.habref_equivalents(h.cd_hab, 'Cahiers_d''habitats') e
) cahiers ON true
-- Bloc ANA-EVAL décodé UNE SEULE FOIS par ligne, station puis habitat.
LEFT JOIN LATERAL (SELECT gn_exports.ana_eval_json(s.comment)             AS j) es ON true
LEFT JOIN LATERAL (SELECT gn_exports.ana_eval_json(h.technical_precision) AS j) eh ON true;
```

#### 5. Matérialiser les correspondances

Les deux fonctions de l'étape 3 sont `STABLE PARALLEL SAFE`, mais elles sont
évaluées **par ligne** et enchaînent deux récursions. **La vue est lente** si on
s'en tient au calcul à la volée — assez pour que ça se voie tout de suite. Mesuré
sur une base d'essai à l'échelle du vrai (41 000 habitats HABREF, 13 000
correspondances, 2 000 habitats saisis, 1 000 `cd_hab` distincts), PostgreSQL 15,
les quatre colonnes de correspondance forcées :

| Montage | Temps |
|---|---|
| calcul à la volée, sans index | **63 s** |
| calcul à la volée, avec les deux index ci-dessous | **2,5 s** |
| jointure sur la table matérialisée | **12 ms** |
| *(construction de cette table, une fois)* | *5 s* |

> ⚠ **Piège de mesure** : `SELECT count(*) FROM v_occhab_complet` répond en
> quelques millisecondes et ne prouve **rien** — le planificateur n'évalue pas les
> `LATERAL` dont il n'a pas besoin. Pour chronométrer, demander les colonnes :
> `SELECT count(habitat_code_corine), count(habitat_code_eunis) FROM …`.
> C'est le même piège que pour le bloc ANA-EVAL, plus haut.

**2. Matérialiser dès que la vue sert à autre chose qu'un coup d'œil.** Les
correspondances ne dépendent que de HABREF et du `cd_hab` : rien qui change entre
deux consultations. Une centaine de `cd_hab` distincts en usage réel, donc une
table minuscule. Elle est **pré-agrégée** — la vue d'export n'a plus qu'à
joindre, sans rien recalculer ni regrouper.

```sql
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
```

Dans `v_occhab_complet`, les quatre `LEFT JOIN LATERAL` sont alors remplacés par
quatre jointures ordinaires — le reste de la vue, colonnes comprises, ne bouge
pas :

```sql
LEFT JOIN gn_exports.mv_habref_equivalents corine
       ON corine.cd_hab = h.cd_hab AND corine.typologie = 'CORINE_biotopes'
LEFT JOIN gn_exports.mv_habref_equivalents eunis
       ON eunis.cd_hab = h.cd_hab AND eunis.typologie = 'EUNIS'
LEFT JOIN gn_exports.mv_habref_equivalents n2000
       ON n2000.cd_hab = h.cd_hab AND n2000.typologie = 'Habitats_d''intérêt_communautaire'
LEFT JOIN gn_exports.mv_habref_equivalents cahiers
       ON cahiers.cd_hab = h.cd_hab AND cahiers.typologie = 'Cahiers_d''habitats'
```

`REFRESH MATERIALIZED VIEW gn_exports.mv_habref_equivalents;` après une mise à
jour de HABREF **et** après une campagne de saisie qui introduit de nouveaux
`cd_hab` — un habitat absent de la table ressortirait sans correspondance, très
exactement le symptôme qu'on cherche à faire disparaître. C'est le défaut de ce
montage, et la raison de ne le poser qu'en connaissance de cause.

> **Une piste essayée et abandonnée** : mettre `habref_equivalents` en étages
> (correspondance directe d'abord, lignée et deux sauts seulement si la première
> ne rend rien), pour que la majorité des habitats paient le prix du cas facile.
> Mesurée **plus lente** (4,7 s contre 2,5 s) — l'étape courte est exécutée pour
> tout le monde, et ceux qui n'y trouvent rien refont ensuite le parcours complet.
> Inutile de la retenter : le gain est du côté des index et de la
> matérialisation, pas de l'ordre des étapes.

> ✔ **Vérifié sur PostgreSQL 15.18 et 16.14** (conteneurs jetables, résultats
> identiques sur les deux) : fonctions et vue créées, puis interrogées sur un
> schéma reproduisant les tables GeoNature — bloc JSON décodé, ancien format
> `clé=valeur` converti, bloc abîmé sans erreur, station sans habitat conservée,
> clé `id_ligne` unique et non nulle (pagination en 3 pages sans doublon ni
> oubli). Le décodage a par ailleurs été comparé sur 12 cas limites (bloc absent,
> bloc vide, tableau JSON, `=` dans une valeur, accents, texte NULL…).
>
> Les **correspondances** ont été reprises séparément sur un HABREF d'essai
> calqué sur les `cd_hab` réels, un habitat par piège : correspondance directe,
> relation à parcourir **à l'envers**, correspondance portée deux niveaux plus
> bas (ordre PVF2 → alliance → association), doublon PVF1 sans code atteint par
> son alias, habitat mal typé en PHYSIS et habitat orphelin (les deux derniers
> restant vides, comme attendu). Contrôlé aussi : `validite = false` ignorée,
> `cd_hab` NULL ou inconnu sans erreur, aucun code de la typologie de départ
> restitué comme son propre équivalent, et **aucune multiplication de lignes**
> (10 habitats → 10 lignes, malgré plusieurs correspondances chacun). Les blocs
> SQL ont été **rejoués tels qu'ils figurent ici**, sur une base vierge, jusqu'à
> la table matérialisée — dont il a été vérifié qu'elle rend, ligne à ligne, très
> exactement ce que rend le calcul à la volée (`EXCEPT` dans les deux sens).
>
> Les **temps de réponse** ont été mesurés à part, sur un HABREF synthétique à
> l'échelle du vrai : la vue est lente si l'on s'en tient au calcul à la volée.
> Lire [Performance](#performance--deux-index-puis-une-table-matérialisée) avant
> de la déclarer dans le module Exports — deux index et une table matérialisée
> font passer les correspondances de plusieurs dizaines de secondes à quelques
> millisecondes.
>
> **Ce qui n'est pas vérifié** : les noms et types réels des colonnes GeoNature
> (le schéma d'essai les imite), `geom_4326`, testé en `text` faute de PostGIS,
> et les temps sur le **vrai** HABREF, dont la forme du graphe (nœuds très
> ramifiés, synonymies en étoile) peut différer de celle du jeu d'essai.
> À passer sur une base de test avant la production.


### Correspondances entre typologies (CORINE ↔ Cahiers d'habitats ↔ EUNIS)

La saisie se fait dans **une** typologie (souvent CORINE biotopes), alors que le
rendu Natura 2000 réclame d'autres codes. HABREF porte ces correspondances :
`ref_habitats.habref_corresp_hab` relie `cd_hab_entre` à `cd_hab_sortie`, avec un
**type de relation** (`bib_habref_typo_rel` : égalité, inclusion…), une éventuelle
condition et un drapeau `validite`.

La tentation est d'en faire un `JOIN` sur `cd_hab_entre = h.cd_hab`. **Ça ne
marche pas** : sur un jeu de saisie réel, les deux tiers des habitats ressortent
alors sans aucune correspondance. Voici pourquoi, et ce que font les deux
fonctions de la vue.

#### Commencer par la matrice

Avant toute chose, demander à HABREF quelles traductions il sait faire :

```sql
SELECT t_src.lb_nom_typo AS source, t_cib.lb_nom_typo AS cible, count(*) AS n
FROM ref_habitats.habref_corresp_hab c
JOIN ref_habitats.habref e       ON e.cd_hab = c.cd_hab_entre
JOIN ref_habitats.habref s       ON s.cd_hab = c.cd_hab_sortie
JOIN ref_habitats.typoref t_src  ON t_src.cd_typo = e.cd_typo
JOIN ref_habitats.typoref t_cib  ON t_cib.cd_typo = s.cd_typo
WHERE coalesce(c.validite, true)
GROUP BY 1, 2 ORDER BY 1, 2;
```

Sur l'instance de l'ANA (extrait des lignes qui nous concernent) :

```
CORINE_biotopes  →  EUNIS                             1801   ← seule sortie de CORINE
Cahiers_habitats →  CORINE_biotopes                    906   ← le sens N2000 est INVERSE
Cahiers_habitats →  EUNIS                              324
HIC              →  Cahiers_d'habitats                 778
HIC              →  EUNIS                              523
PVF2             →  CORINE 907 · EUNIS 1052 · Cahiers  926
PVF1             →  HIC                                602   ← et rien d'autre
PVF1             →  PVF1                              1362   ← synonymie interne
Unités_phyto     →  Cahiers_d'habitats                3916
EUNIS            →  (Cahiers, HIC, OSPAR…)   mais RIEN vers CORINE
```

#### Quatre pièges, que cette matrice suffit à révéler

- **Le graphe est orienté, et CORINE n'a qu'une seule arête sortante.** Un
  habitat saisi en EUNIS ne retrouvera jamais son code CORINE en lisant
  `cd_hab_entre` : la relation n'existe que dans l'autre sens. Idem pour Natura
  2000, où c'est `Cahiers → CORINE` qui est stocké. **Il faut parcourir les deux
  sens.**
- **La correspondance est accrochée à un niveau hiérarchique précis.** Un ordre
  phytosociologique (`Prunetalia spinosae`, `Loto pedunculati -
  Filipenduletalia ulmariae`) n'en porte aucune : elles sont sur les alliances ou
  les associations, un à deux crans plus bas. Inversement, une association fine
  peut n'avoir que celle de son alliance. **Il faut parcourir la lignée.**
- **Une même unité a souvent plusieurs entrées dans HABREF.** « Mentho-Juncion
  inflexi » (sans code) et « Mentho longifoliae-Juncion inflexi 3.0.1.0.5 »
  désignent la même alliance ; seule la seconde porte les correspondances, la
  première n'étant reliée que par une arête `PVF1 → PVF1`. Ces arêtes
  intra-typologie sont des **alias**, pas des traductions : les suivre ne doit
  rien coûter.
- **Une correspondance n'est pas une équivalence.** Un code CORINE se traduit
  fréquemment par *plusieurs* codes Cahiers d'habitats, distingués par une
  `lb_condition` (« en situation montagnarde »…). Le type de relation dit s'il
  s'agit d'une égalité ou d'une inclusion — ne le jetez pas, c'est lui qui dit
  si la traduction est automatisable ou demande un arbitrage.

Deux corollaires : les `cd_typo` **varient d'une instance à l'autre** (listez-les
avec `SELECT cd_typo, lb_nom_typo FROM ref_habitats.typoref ORDER BY 2;` plutôt
que de recopier un numéro), et le PVF1 n'atteint CORINE ou EUNIS qu'en
**traversant les HIC** — d'où les deux sauts autorisés par `habref_equivalents`.

#### Lire le rang

`habref_equivalents` rend, avec chaque code, un rang qui dit ce qu'il vaut. La
vue le publie en `habitat_corine_rang`, `habitat_eunis_rang`, etc.

| Rang | Signification | Utilisable pour |
|---|---|---|
| `0` | l'habitat est déjà dans la typologie visée, son propre code fait foi | tout |
| `10` | correspondance directe, portée par le code saisi | tout |
| `11` `12` | héritée d'un parent ou d'un descendant, à 1 ou 2 crans hiérarchiques | carte, statistiques |
| `2x` | obtenue en traversant une typologie intermédiaire | orientation, à arbitrer |

Le second chiffre compte les **crans**, pas le sens : `11` peut venir du parent
comme d'un descendant. Pour le savoir sur un habitat donné, la requête de la fin
de section publie le sens et la distance de chaque correspondance.

Un rang `11` ou `12` **élargit** la correspondance : l'équivalent EUNIS d'un ordre
est l'union de ceux de ses alliances. C'est juste pour colorier une carte —
l'usage de `habitat_style.py`, qui ne lit que la lettre de classe EUNIS — pas pour
un livrable. Un rang `2x` sur du PVF1 enchaîne deux inclusions : à traiter comme
une piste, jamais comme une détermination.

Une exception qui mérite d'être connue : `Cahiers → HIC` est structurel (lire
`6510` dans `6510-1`), donc un `habitat_code_n2000` au rang 20 obtenu depuis
CORINE n'est pas deux fois moins sûr qu'un rang 10 — toute l'incertitude est dans
le premier saut, `CORINE → Cahiers`.

#### Diagnostiquer un habitat qui reste vide

```sql
SELECT DISTINCT hab.cd_hab, hab.lb_code, hab.lb_hab_fr, t.lb_nom_typo, hab.cd_hab_sup,
       (SELECT count(*) FROM ref_habitats.habref_corresp_hab c
         WHERE c.cd_hab_entre  = hab.cd_hab)                          AS sortantes,
       (SELECT count(*) FROM ref_habitats.habref_corresp_hab c
         WHERE c.cd_hab_sortie = hab.cd_hab)                          AS entrantes,
       (SELECT count(*) FROM gn_exports.habref_famille(hab.cd_hab) f
          JOIN ref_habitats.habref_corresp_hab c
            ON c.cd_hab_entre = f.o_cd_hab OR c.cd_hab_sortie = f.o_cd_hab) AS via_famille
FROM pr_occhab.t_habitats h
JOIN ref_habitats.habref hab      ON hab.cd_hab = h.cd_hab
LEFT JOIN ref_habitats.typoref t  ON t.cd_typo  = hab.cd_typo
ORDER BY t.lb_nom_typo, hab.lb_code;
```

`sortantes = entrantes = via_famille = 0` signale un habitat que **rien** ne
rattache au reste de HABREF. Dans ce cas, ce n'est pas la requête qu'il faut
corriger mais la saisie : le plus souvent une **typologie mal choisie** — un
`31.8C` saisi en Classification Paléarctique alors que le même code existe en
CORINE biotopes et porte, lui, sa correspondance EUNIS. Ça se répare dans
`t_habitats`, pas dans la vue.

#### Et la condition qui distingue deux codes N2000 ?

`habref_corresp_hab` porte une `lb_condition` (« en situation montagnarde »…) et
un type de relation (égalité, inclusion) que les colonnes agrégées de la vue ne
transportent pas : elles qualifient **une relation**, pas un habitat, et n'ont
plus de sens dès qu'on enchaîne deux sauts. Quand il faut trancher entre les
codes d'une même cellule, la question se pose sur un habitat à la fois — une
requête ad hoc, pas une vue à maintenir :

```sql
SELECT cible.lb_code, cible.lb_hab_fr, t_cib.lb_nom_typo,
       rel.lb_type_rel, c.lb_condition, c.lb_remarques,
       CASE WHEN c.cd_hab_entre = f.o_cd_hab THEN 'direct' ELSE 'inverse' END AS sens,
       f.o_dist AS distance_hierarchique
FROM gn_exports.habref_famille(<cd_hab>) f
JOIN ref_habitats.habref_corresp_hab c
       ON (c.cd_hab_entre = f.o_cd_hab OR c.cd_hab_sortie = f.o_cd_hab)
      AND coalesce(c.validite, true)
JOIN ref_habitats.habref cible
       ON cible.cd_hab = CASE WHEN c.cd_hab_entre = f.o_cd_hab THEN c.cd_hab_sortie
                              ELSE c.cd_hab_entre END
LEFT JOIN ref_habitats.typoref t_cib ON t_cib.cd_typo = cible.cd_typo
LEFT JOIN ref_habitats.bib_habref_typo_rel rel ON rel.cd_type_rel = c.cd_type_relation
ORDER BY f.o_dist, t_cib.lb_nom_typo, cible.lb_code;
```

### Récupérer un export depuis le plugin

Le module Exports expose **deux** routes, dont une seule sert ici :

| Route | Comportement |
|---|---|
| `GET /exports/{id}/{format}` | **Asynchrone** : met la génération en file (Celery) et répond « en cours, vous recevrez une notification ». Pas de fichier en retour. |
| `GET /exports/api/{id}` | **Synchrone**, paginée, **GeoJSON** dès que la vue porte une géométrie. C'est celle qu'utilise le plugin. |

« Récupérer une station du serveur… ▸ **Charger un export du serveur (couche)** »
propose le JDD courant et une période (année en cours par défaut), puis dépose le
résultat en couche lecture seule sous le groupe **« OccHab (exports) »** — groupe
distinct de « OccHab (serveur) », qui est lui reconstruit à chaque
rafraîchissement.

**Seuls les exports bâtis sur `v_occhab_complet` sont proposés** (filtrage sur le
`view_name` renvoyé par `GET /exports/`). Les autres exports d'une instance —
synthèse, taxons, métadonnées — n'ont ni les colonnes `id_dataset`/`date_min`/
`date_max` que les filtres supposent, ni une structure que le plugin saurait
présenter : les lister reviendrait à promettre un filtrage qui n'aurait pas lieu.

Trois pièges de cette route, traités dans `geonature_client.py` :

- **`offset` est un numéro de page**, pas un décalage de lignes (`"page": self.offset`
  dans la réponse). S'y tromper renvoie dix fois la même page sans rien signaler.
- **`items` change de forme** : `FeatureCollection` si la vue a une géométrie,
  liste de dicts sinon (`as_geofeature()` vs `return_query()` côté GeoNature).
- **Un filtre sur une colonne absente de la vue est ignoré en silence.** Le
  plugin compare `total_filtered` à `total` et avertit quand le filtrage n'a
  visiblement rien restreint — d'où l'utilité des colonnes `id_dataset`,
  `date_min` et `date_max` dans la vue.

Les filtres de période suivent la convention de la route : `filter_d_up_date_min`
(« à partir de ») et `filter_d_lo_date_max` (« jusqu'à »), donc des stations
**contenues** dans l'intervalle.

**Symbologie : une couleur par habitat, dans le ton de son milieu**
(`processing/habitat_style.py`, pur et testé). Le **ton** vient du grand milieu,
la **nuance** distingue chaque habitat dans ce ton — les habitats présents étant
étalés sur la plage du milieu dans l'ordre de leur code. Jamais de liste
d'habitats codée en dur : un habitat inconnu se colore de lui-même.

Le milieu est déterminé par **vote de tous les équivalents** (`classe_habitat`),
et non par le premier code venu : première lettre des codes **EUNIS** (poids 2),
premier chiffre des codes **CORINE biotopes** (avec partage du groupe 3, qui
réunit landes et prairies) et des codes **Natura 2000** — annexe I ou Cahiers
d'habitats, dont les groupes 1 à 9 sont un découpage en milieux. `source_classe`
dit quelles typologies ont porté le résultat.

Le vote n'est pas un raffinement : la vue agrège les équivalents **par ordre
alphabétique**, si bien que lire le premier revenait à laisser l'alphabet décider.
Une chênaie-frênaie dont la liste commençait par un code « B… » se retrouvait
classée en « côtes et dunes ». Deux garde-fous en découlent :

- les codes sont **tous** lus, et la majorité l'emporte ;
- chaque voix est pondérée par le **rang** de sa correspondance (`poids_rang`) :
  une correspondance directe pèse quatre fois une correspondance obtenue en
  traversant une typologie intermédiaire. Sans cela, un détour à deux sauts
  rattachait une magnocariçaie à une dépression dunaire — les deux sont humides
  — avec le même poids qu'un lien direct, et des végétations de bord d'étang se
  retrouvaient en « côtes et dunes » ;
- les milieux **littoraux** (A, B) ne sont retenus qu'en dernier recours : un
  habitat réellement littoral gagne quand même, rien d'autre ne votant.

Une vue sans colonnes de rang continue de fonctionner : un rang absent n'est pas
pénalisé.

Sans cette cascade, une cartographie saisie en **PVF1** virait entièrement au
gris : dans HABREF, le Prodrome n'a qu'une table de correspondance, `PVF1_HIC`,
qui mène aux habitats d'intérêt communautaire et pas à EUNIS. Vérifié sur un jeu
PVF1 reconstitué — 8 habitats sur 9 rattachés via N2000 ou CORINE, le neuvième
étant un syntaxon réellement sans correspondance dans HABREF.

L'identité de couleur est le `cd_hab` (repli sur le nom) : un même habitat garde
sa couleur d'une station à l'autre, là où `nom_cite` est du texte libre.

Deux détails de colorimétrie, issus de mesures et non d'intuitions :

- la gamme est construite en **TSL** (éclaircir en RVB délave la saturation et
  vire au gris), luminosité en **axe rapide** et saturation en axe lent — l'ordre
  inverse plaçait trois nuances au point le plus sombre du ton, où la saturation
  ne se voit plus (écart RVB sous 5 sur 255) ;
- la plage de luminosité est **reportée et non rognée** quand le ton bute sur une
  borne : un vert forestier, déjà sombre, y perdait la moitié de son étendue.

Écarts mesurés (minimum entre deux nuances quelconques, sur 255) : **93 à deux
habitats par milieu, 28 à quatre, 15 à six**, contre **13 à 17 entre milieux
différents**. Au-delà de sept habitats dans un même milieu, les nuances se
resserrent — limite propre à un ton unique, que le groupement de la légende
compense.

C'est **le seul usage où un rang de correspondance dégradé est sans conséquence**
(voir [Lire le rang](#lire-le-rang)) : seule la première lettre est lue, et un
équivalent EUNIS hérité d'un parent reste dans la bonne classe de niveau 1. La
colonne peut porter plusieurs codes séparés par « ; » — la lettre du premier
l'emporte, ce qui suffit à colorier mais ne prétend pas trancher une mosaïque.

Neuf champs sont calculés à la volée avant l'écriture du GeoJSON :
`classe_milieu`, `libelle_milieu`, `source_classe`, `cle_habitat`, `couleur`,
`rang_habitat`, `est_dominant`, `est_mosaique` et `composition`. Le rendu est un
`QgsRuleBasedRenderer` **à deux niveaux** — un groupe par milieu, une règle par
habitat.

**Mosaïques : tous les habitats sont dessinés, CÔTE À CÔTE.** Chaque habitat
reçoit une **bande** du polygone proportionnelle à son recouvrement, découpée par
un `QgsGeometryGeneratorSymbolLayer` entre `bande_debut_pct` et `bande_fin_pct`.
Plus aucune superposition : chaque habitat garde un aplat franc, et la carte a la
lisibilité d'une carte mono-habitat quelle que soit sa densité.

Une première version superposait des hachures colorées : illisible dès que la
carte se densifiait, et il fallait deviner qu'une hachure reprenait la couleur
d'un autre poste de légende. Trois points d'implémentation :

- les bornes sont calculées **en Python à l'export** (`_bandes`) et non par
  expression : un `aggregate` par entité au rendu serait ruineux ;
- les bandes ne portent **pas de contour** — il dessinerait de fausses limites
  d'habitat ; un contour unique par station est tiré par l'entité dominante ;
- leurs bords sont **estompés** (`QgsBlurEffect`, 1,4 mm, méthode `StackBlur`)
  tandis que ce contour reste net : la limite relevée sur le terrain et le
  partage conventionnel ne doivent pas se lire pareil. L'effet est posé sur la
  COUCHE de symbole (`setPaintEffect` n'existe pas sur `QgsSymbol`) et réglé en
  millimètres, pour tenir à l'écran comme à 300 ppp ;
- les **niveaux de symboles** deviennent inutiles, les bandes ne se recouvrant
  plus.

**Limite assumée** : la bande dit la *proportion*, pas la *localisation* — la
donnée ne contient pas où se trouve chaque habitat dans le polygone. C'est une
convention de lecture, comme un diagramme. Le guide méthodologique national
(MNHN/CBN 2005) ne normalise d'ailleurs que le modèle de données, pas la
sémiologie ; les cartes publiées traitent le plus souvent la mosaïque comme un
poste de légende composite (couleur du dominant + surcharge), ce que cette
représentation remplace par un partage explicite.

L'infobulle donne la composition chiffrée, que les hachures ne disent pas.

La palette couvre **tous** les habitats, dominants ou non — un habitat secondaire
est bel et bien dessiné — mais seuls les milieux présents entrent en légende, au
lieu d'aligner onze entrées dont neuf vides.

> ✔ **Vérifié sur PostgreSQL 15.18** : les deux requêtes créées et interrogées
> sur des tables HABREF reproduisant `habref.sql` du module
> [Habref-api-module](https://github.com/PnX-SI/Habref-api-module) (colonnes et
> clés étrangères conformes). Un code CORINE relié à deux codes Cahiers
> d'habitats et un code EUNIS ressort bien en trois lignes — et la relation
> marquée `validite = false` est écartée.
> **Non vérifié** : le contenu réel de HABREF sur votre instance (jeu de données
> INPN), donc la couverture effective des correspondances pour vos habitats.

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
  La cellule **« Nom cité »** fait exception : elle ouvre la **recherche HABREF**
  (`HabrefLineEdit`), et l'habitat retenu écrit **nom cité + `cd_hab`** sur la
  ligne — via `GrilleModel.definir_par_cle`, donc même si la colonne `cd_hab`
  n'est pas affichée, et via `mapToSource` pour viser la bonne ligne sous un
  filtre. Hors connexion, repli sur du texte libre (annoncé en infobulle).
- Un champ **station** modifié sur une ligne l'est **pour toutes ses lignes
  sœurs** : les colonnes station sont teintées et le signalent en infobulle.
- **« Modifier les lignes sélectionnées… »** pousse les mêmes valeurs sur un lot ;
  chaque champ a une case à cocher, sinon valider écraserait tout avec du vide.
  Les champs restent **saisissables** et la saisie coche la case : les griser
  d'avance rendait le bloc HABREF « Nom cité » inerte sans que rien ne l'explique.
  Le bouton porte le nombre de lignes visées et reste grisé sans sélection : le
  libellé « Appliquer à la sélection… » ne disait pas ce qu'il appliquait.
  L'**identité de l'habitat** (`cd_hab` + `nom_cite`) s'y modifie via la même
  **recherche HABREF** (`ui/habref_widget.py`, partagé par le formulaire, le lot
  et les cellules) : choisir un habitat coche et renseigne **les deux champs**,
  un code qui ne correspondrait plus à son nom étant une donnée incohérente.
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
| `last_entry.cd_typo` | — | Typologie HABREF de la dernière saisie (filtre pré-réglé) |
| `last_entry.habitat` | — | Dernier habitat saisi, sans son identité ni ses mesures (pré-remplissage) |
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
    │                 duplicate.py               # duplication / collage / reprise (pur, testé)
    │                 habitat_style.py           # classes de milieu EUNIS, mosaïques (pur, testé)
    │                 geometry.py                # WKT/GeoJSON, reprojection 4326
    └── ui/           dock_widget.py             # dock principal
                      attribute_table.py         # table stations × habitats (adaptateur Qt)
                      dialog_size.py             # dialogues défilants, bornés à l'écran
                      station_form.py · habitat_form.py · station_dialog.py
                      station_picker_dialog.py   # choix d'une station à recopier
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
