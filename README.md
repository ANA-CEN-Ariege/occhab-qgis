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
**« Récupérer une station du serveur… »** offre **deux chemins**. Tous deux
rapatrient des données ÉDITABLES : charger un export, qui donne une couche de
consultation, est rangé ailleurs (« Cartographier… »), pour que le bouton ne
mélange pas deux natures d'objet.
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
| `zone_humide` | station | `oui` `non` `a_verifier` — extension **ANA**. Anciennement un booléen : `true` se relit `oui`, `false` ne se relit pas (une case décochée ne disait pas « non ») |
| `recouvrement` | habitat | 0-100 ; **pré-sélectionne** l'Abondance (< 5 %, 5-25 %, 25-50 %, 50-75 %, > 75 %) **et** alimente le champ natif `recovery_percentage` |
| `determination` | habitat | `{"nom": …, "ancre": …}` — présente **seulement** quand `cd_hab` est une ancre (cf. §6 quater) |
| `corresp` | habitat | `{typologie: {"cd_hab": …, "code": …, "src": …}}` — correspondances inscrites dans la donnée (cf. §6 quater) |

Ces deux dernières clés sont les seules **structurées** du bloc ; toutes les
autres sont scalaires. Elles sont validées typologie par typologie : une
typologie hors référentiel est écartée, une entrée sans `cd_hab` exploitable
aussi — c'est le `cd_hab` qui fait la correspondance, un code seul ne se
raccorde à rien.

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

> 📄 **Les étapes 1 à 4 sont réunies dans [`sql/v_occhab_complet.sql`](sql/v_occhab_complet.sql)**,
> prêt à exécuter d'un seul tenant dans DBeaver, psql ou pgAdmin. Le fichier fait
> foi : les blocs ci-dessous en sont la copie commentée, et un test
> (`tests/test_sql_script.py`) vérifie qu'ils ne divergent pas. Écrit et vérifié
> pour **PostgreSQL 15**, rejoué deux fois de suite pour s'assurer qu'il se
> relance sans erreur.

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
    coalesce(
        corresp_saisi.j -> 'CORINE_biotopes' ->> 'code',
        CASE WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN hab.lb_code END,
        corine.codes
    )                                                           AS habitat_code_corine,
    coalesce(
        corresp_saisi.j -> 'CORINE_biotopes' ->> 'nom',
        CASE WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN hab.lb_hab_fr END,
        corine.noms
    )                                                           AS habitat_nom_corine,
    CASE WHEN corresp_saisi.j -> 'CORINE_biotopes' ->> 'code' IS NOT NULL
              THEN coalesce(corresp_saisi.j -> 'CORINE_biotopes' ->> 'src', 'saisi')
         WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN 'determination'
         WHEN corine.codes IS NOT NULL THEN 'habref'
    END                                                         AS habitat_corine_source,
    CASE WHEN t_hab.lb_nom_typo = 'CORINE_biotopes' THEN 0
         ELSE corine.rang END                                    AS habitat_corine_rang,
    coalesce(
        corresp_saisi.j -> 'EUNIS' ->> 'code',
        CASE WHEN t_hab.lb_nom_typo = 'EUNIS' THEN hab.lb_code END,
        eunis.codes
    )                                                           AS habitat_code_eunis,
    coalesce(
        corresp_saisi.j -> 'EUNIS' ->> 'nom',
        CASE WHEN t_hab.lb_nom_typo = 'EUNIS' THEN hab.lb_hab_fr END,
        eunis.noms
    )                                                           AS habitat_nom_eunis,
    CASE WHEN corresp_saisi.j -> 'EUNIS' ->> 'code' IS NOT NULL
              THEN coalesce(corresp_saisi.j -> 'EUNIS' ->> 'src', 'saisi')
         WHEN t_hab.lb_nom_typo = 'EUNIS' THEN 'determination'
         WHEN eunis.codes IS NOT NULL THEN 'habref'
    END                                                         AS habitat_eunis_source,
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
        corresp_saisi.j -> 'Habitats_d''intérêt_communautaire' ->> 'code',
        CASE WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN hab.lb_code END,
        n2000.codes
    )                                                           AS habitat_code_n2000,
    coalesce(
        corresp_saisi.j -> 'Habitats_d''intérêt_communautaire' ->> 'nom',
        CASE WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN hab.lb_hab_fr END,
        n2000.noms
    )                                                           AS habitat_nom_n2000,
    CASE WHEN corresp_saisi.j -> 'Habitats_d''intérêt_communautaire' ->> 'code' IS NOT NULL
              THEN coalesce(corresp_saisi.j -> 'Habitats_d''intérêt_communautaire' ->> 'src', 'saisi')
         WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN 'determination'
         WHEN n2000.codes IS NOT NULL THEN 'habref'
    END                                                         AS habitat_n2000_source,
    CASE WHEN t_hab.lb_nom_typo = 'Habitats_d''intérêt_communautaire' THEN 0
         ELSE n2000.rang END                                    AS habitat_n2000_rang,
    coalesce(
        corresp_saisi.j -> 'Cahiers_d''habitats' ->> 'code',
        CASE WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN hab.lb_code END,
        cahiers.codes
    )                                                           AS habitat_code_cahiers,
    coalesce(
        corresp_saisi.j -> 'Cahiers_d''habitats' ->> 'nom',
        CASE WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN hab.lb_hab_fr END,
        cahiers.noms
    )                                                           AS habitat_nom_cahiers,
    CASE WHEN corresp_saisi.j -> 'Cahiers_d''habitats' ->> 'code' IS NOT NULL
              THEN coalesce(corresp_saisi.j -> 'Cahiers_d''habitats' ->> 'src', 'saisi')
         WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN 'determination'
         WHEN cahiers.codes IS NOT NULL THEN 'habref'
    END                                                         AS habitat_cahiers_source,
    CASE WHEN t_hab.lb_nom_typo = 'Cahiers_d''habitats' THEN 0
         ELSE cahiers.rang END                                    AS habitat_cahiers_rang,
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
LEFT JOIN LATERAL (SELECT gn_exports.ana_eval_json(h.technical_precision) AS j) eh ON true
-- Correspondances SAISIES, résolues en libellés. Le plugin n'enregistre que le
-- cd_hab et le code : le nom vient de HABREF, qui fait foi et peut le corriger
-- d'une version à l'autre — le figer dans la donnée garderait un nom périmé à
-- côté d'un code juste. Le cast n'a lieu que si la valeur est bien un entier :
-- un bloc abîmé à la main ne doit pas faire échouer la vue entière.
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(c.cle, jsonb_build_object(
               'code', coalesce(saisi.lb_code, c.valeur ->> 'code'),
               'nom',  saisi.lb_hab_fr,
               'src',  c.valeur ->> 'src'
           )) AS j
    FROM jsonb_each(CASE WHEN jsonb_typeof(eh.j -> 'corresp') = 'object'
                         THEN eh.j -> 'corresp' ELSE '{}'::jsonb END) AS c(cle, valeur)
    LEFT JOIN ref_habitats.habref saisi
           ON saisi.cd_hab = CASE WHEN c.valeur ->> 'cd_hab' ~ '^[0-9]+$'
                                  THEN (c.valeur ->> 'cd_hab')::int END
) corresp_saisi ON true;
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

« Cartographier… ▸ **Charger un export du serveur (couche)** » propose le JDD
courant et une période (année en cours par défaut), puis dépose le
résultat en couche lecture seule **en tête** du groupe **« OccHab (exports) »**.
En tête, et non à la suite : `addLayer` ajoute en DERNIER enfant, c'est-à-dire
sous les couches déjà présentes — un deuxième export se retrouvait caché par le
premier, et on le croyait vide. Le groupe est distinct de « OccHab (serveur) »,
qui est lui reconstruit à chaque rafraîchissement.

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

**La vue peut fournir le grand type elle-même.** Si elle expose `grand_type_code`
et `grand_type_nom` — la racine hiérarchique HABREF de l'équivalent EUNIS — ils
font autorité et le vote n'a pas lieu : le rattachement et son libellé viennent
alors du référentiel, plus des tables de ce module. La racine n'est retenue que
si c'est une classe EUNIS connue, faute de quoi aucune couleur ne lui serait
attribuée.

```sql
-- Racine hiérarchique d'un habitat dans SA typologie (niveau 1).
CREATE OR REPLACE FUNCTION gn_exports.habref_racine(p_cd_hab integer)
RETURNS TABLE(o_cd_hab integer, o_code character varying, o_nom character varying)
LANGUAGE sql STABLE PARALLEL SAFE AS $fn$
    WITH RECURSIVE remonte AS (
        SELECT h.cd_hab, h.cd_hab_sup, h.lb_code, h.lb_hab_fr, 0 AS d
        FROM ref_habitats.habref h WHERE h.cd_hab = p_cd_hab
      UNION ALL
        -- Borne à 20 : une boucle dans cd_hab_sup ferait tourner sans fin.
        SELECT s.cd_hab, s.cd_hab_sup, s.lb_code, s.lb_hab_fr, r.d + 1
        FROM remonte r JOIN ref_habitats.habref s ON s.cd_hab = r.cd_hab_sup
        WHERE r.d < 20
    )
    SELECT cd_hab, lb_code, lb_hab_fr FROM remonte ORDER BY d DESC LIMIT 1;
$fn$;
```

⚠ **Prenez la racine de l'ÉQUIVALENT EUNIS, pas celle de l'habitat saisi.** Le
niveau 1 d'EUNIS est un découpage en milieux (11 classes) ; celui du Prodrome est
la classe phytosociologique — plusieurs dizaines, donc une légende à 80 groupes.
La colonne se construit en appliquant `habref_racine` au `cd_hab` que
`habref_equivalents(h.cd_hab, 'EUNIS')` désigne.

**Ce que cela ne règle pas** : les couleurs. Associer « forêt » à un vert foncé
reste un choix de ce module — HABREF ne porte pas de sémiologie. Le gain est que
le *regroupement* et les *libellés* cessent d'être une interprétation.

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

**Un habitat de l'annexe I, une voix — pas une par fiche.** Les Cahiers
d'habitats déclinent chaque habitat en autant de fiches qu'il a de variantes, et
le compte varie du simple au quadruple : l'habitat **6210** (pelouses calcicoles)
en aligne **45**, l'habitat **4060** (landes) en aligne 11. Laisser voter chaque
fiche revient à voter le nombre de variantes plutôt que le milieu.

Mesuré sur le `Prunetalia spinosae`, un ordre de **fourrés** : HABREF le relie à
4060, 4070, 5110, 5130 et 5210 — landes et fruticées — contre le seul 6210. Il
ressortait pourtant en « Prairies et pelouses », les 45 fiches de 6210 écrasant
les 36 des cinq autres. `habitats_annexe_i()` ne retient donc que les codes à
quatre chiffres, dédoublonnés : cinq voix pour les landes contre une pour la
pelouse, et le Prunetalia rejoint les fruticées.

**L'annexe I ne peut pas, à elle seule, désigner un milieu littoral.** Ses
correspondances disent où une végétation *peut se rencontrer*, pas ce qu'elle
est. HABREF relie ainsi le `Caricion gracilis`, le `Mentho longifoliae-Juncion
inflexi` et l'`Oenanthion fistulosae` à l'habitat **2190 « Dépressions humides
intradunales »**, parce que ces alliances décrivent aussi la végétation des
pannes dunaires. Prises au mot, elles peuplaient un poste « Côtes, dunes et
plages » sur une carte ariégeoise, à 600 m d'altitude et 150 km de la mer. Un
milieu littoral demande donc un témoin **EUNIS ou CORINE**
(`_TEMOINS_LITTORAUX`) ; sans lui, l'habitat reste « non rattaché », ce qui est
la vérité. Une vraie dune, elle, ressort toujours : EUNIS la code `B1`.

**En dernier recours, la CLASSE du Prodrome tranche**
(`_rattacher_par_classe_pvf`). HABREF ne donne à certains syntaxons aucune
correspondance vers EUNIS, CORINE ou l'annexe I. Ils restaient gris — alors que
le référentiel sait très bien où les ranger : le code d'un syntaxon commence par
le numéro de sa **classe phytosociologique**, et une classe de végétation est une
unité écologique. Trois rattachements sur une carto ariégeoise, tous justes :

| Sans correspondance | Rejoint | Milieu |
|---|---|---|
| `Caricion gracilis` (**51**.0.2.0.2) | `Phragmition communis` (**51**.0.1.0.1) | Tourbières et bas-marais |
| `Cynosurion cristati` (**6**.0.2.0.1) | `Brachypodio rupestris-Centaureion nemoralis` (**6**.0.1.0.2) | Prairies et pelouses |
| `Lonicerion periclymeni` (**20**.0.2.0.4) | `Prunetalia spinosae` (**20**.0.2) | Landes et fruticées |

Seuls les codes **numériques** comptent — « C1.6 » et « E2.12 » sont des codes
EUNIS, dont le milieu se lit directement — et seules les alliances **présentes
sur la carte** votent : on ne rattache jamais à partir d'un référentiel qu'on n'a
pas sous les yeux. Sur l'export réel, les habitats non rattachés passent de six à
trois, et `source_classe` porte `classe PVF` pour dire d'où vient la couleur.

**Un habitat non rattaché reprend le milieu de son homonyme**
(`_rattacher_les_homonymes`). HABREF porte la même alliance sous plusieurs
`cd_hab` dont les correspondances diffèrent : `16747` « Mentho longifoliae -
Juncion inflexi » ressort d'EUNIS `E3.1` et de CORINE `37.24`, tandis que
`16573` « Mentho longifoliae-Juncion inflexi » n'a que l'annexe I. C'est la même
végétation, et la légende la regroupe déjà sous une seule entrée — deux milieux
la feraient apparaître deux fois, dans deux groupes. La propagation ne va que
dans un sens : une classe établie n'est jamais remise en cause par un silence.

Le rapprochement suppose que les deux noms se ressemblent, et HABREF ne les écrit
pas deux fois pareil. `_normaliser()` ignore la casse, les espaces multiples et
les espaces autour du tiret ; **`_squelette()` réduit un nom de syntaxon à ses
genres** — le premier mot de chaque membre — pour que la forme abrégée rejoigne
la complète. Trois paires relevées sur une seule carto, chacune sortie en deux
postes de deux couleurs :

| Forme complète | Forme abrégée |
|---|---|
| Brachypodio **rupestris**-Centaureion **nemoralis** | Brachypodio-Centaureion nemoralis |
| Tetragonolobo **maritimi**-Mesobromenion **erecti** | Tetragonolobo-Mesobromenion |
| Mentho **longifoliae**-Juncion **inflexi** | Mentho-Juncion inflexi |

Les épithètes tombent — et pas toujours les mêmes, d'où la réduction à un seul
mot par membre. La réduction ne s'applique **qu'aux noms de syntaxons**, reconnus
au suffixe de leur dernier membre (`-ion`, `-enion`, `-etalia`, `-etea`,
`-etum`) : sans ce garde-fou, « Lacs, étangs et mares temporaires » tomberait à
« Lacs, » et se confondrait avec tout ce qui commence pareil.

En légende, c'est le libellé **le plus renseigné** qui s'affiche : « Brachypodio
rupestris-Centaureion nemoralis (6.0.1.0.2) » dit l'épithète et le code, sa forme
abrégée n'apprend rien de plus. Mesuré sur l'export réel : **26 postes de légende
au lieu de 42**.

Neuf champs sont calculés à la volée avant l'écriture du GeoJSON :
`classe_milieu`, `libelle_milieu`, `source_classe`, `cle_habitat`, `couleur`,
`rang_habitat`, `est_dominant`, `est_mosaique` et `composition`. Le rendu est un
`QgsRuleBasedRenderer` **à deux niveaux** — un groupe par milieu, une règle par
habitat.

**La géométrie GeoJSON est lue par un convertisseur maison**
(`processing/geojson_wkt.py`), pas par `QgsJsonUtils.geometryFromGeoJson()` :
cette fonction n'existe qu'à partir de **QGIS 3.36**, alors que l'extension
annonce prendre en charge la **3.28**. Sur un poste Windows en 3.28, charger un
export levait `AttributeError: type object 'QgsJsonUtils' has no attribute
'geometryFromGeoJson'` et la couche ne se chargeait pas du tout.
`QgsGeometry.fromWkt()`, elle, existe depuis toujours — et un seul chemin pour
toutes les versions vaut mieux qu'une branche selon celle qu'on a sous la main.
Vérifié identique à `QgsJsonUtils` sur les 236 entités d'un export réel.

Trois autres énumérations ne sont atteintes qu'avec un repli, pour la même
raison : `Qgis.RenderUnit` (QGIS 3.30), `Qgis.SymbolType` (3.20) et
`QgsLegendStyle.Style`. Toutes existent encore dans les versions récentes, mais
leur ancienne place existe dans TOUTES — c'est elle qui sert de filet.

**La carte des PEE** (`_poser_pee`, `_ajouter_regles_pee`) pose un cercle par
espèce exotique, sur les bandes d'habitats. Trois décisions :

- **les couleurs viennent d'un pas d'or** sur le cercle des teintes
  (`processing/pee.py`), avec clarté et saturation alternées : deux espèces
  voisines se distinguent alors même sans percevoir la teinte. Un pas régulier
  (360/n) aurait rebattu toutes les couleurs à chaque espèce ajoutée ; ici les
  précédentes ne bougent pas. Les espèces sont triées par nom, jamais par ordre
  d'apparition — sinon deux chargements du même export donnent deux cartes ;
- **les points sont répartis en ALTERNANCE**, pas par blocs : trois espèces
  réparties par tiers dessineraient trois taches contiguës, qu'on lirait comme
  une localisation à l'intérieur de la station. Or la donnée dit seulement
  qu'elles sont là. Le nombre de cercles est fixe (huit) pour la même raison :
  la saisie note une présence, pas une abondance ;
- **une seule entité par station porte les points**, la dominante : les habitats
  d'une station partagent sa géométrie, et laisser chaque ligne poser ses
  cercles les empilerait au même endroit. Les points partent en JSON dans
  `pee_points`, relus à l'affichage par `map_get(from_json(…))`.

Trois pièges rencontrés, tous silencieux :

- les mailles de bordure. Prendre le centre d'une maille ROGNÉE plaçait les
  cercles sur le contour, en chapelet ; on écarte désormais celles qui font
  moins de 55 % d'une maille pleine, ce qui suppose une grille plus fine (40
  mailles calculées pour 8 cercles retenus) ;
- `@symbol_label` dans le générateur de géométrie : la variable n'y est pas
  résolue, et **aucun cercle ne sortait**, sans message. Le nom de l'espèce est
  écrit dans l'expression, une règle par espèce ;
- une taille de marqueur **définie par données en unités de carte** : les bornes
  en millimètres d'un `QgsMapUnitScale` ne s'y appliquent pas, et sur des
  coordonnées en degrés le cercle tombait à deux centièmes de millimètre. Taille
  fixe en millimètres — un symbole de présence n'a pas à changer de taille.

**La carte des enjeux** (`_renderer_enjeux`) est une autre carte, pas une autre
mosaïque : la couleur n'y dit pas ce qui pousse mais ce qui est en jeu. Le niveau
appartient à la STATION (`station_niveau_enjeu` dans la vue d'export), que ses
habitats se partagent — seule l'entité **dominante** peint le fond, sinon les
lignes d'une mosaïque repeindraient trois fois le même polygone, pour rien et en
plus sombre.

Palette et libellés dans `referentiels.COULEURS_ENJEU`, repris de la charte des
planches « Flore Ariège ». La dernière entrée ramasse « aucun », « inconnu » et
l'absence de valeur : les distinguer donnerait trois postes de légende là où la
carte n'en montre qu'un. Un test vérifie qu'une station tombe dans **exactement
une** règle, quel que soit son niveau — deux la dessineraient deux fois, aucune la
laisserait invisible, et ni l'un ni l'autre ne se voit sur une carte.

Les contours d'habitats passent au-dessus des aplats par les **niveaux de
symboles** (`setUsingSymbolLevels`, passe 1 contre 0) : l'ordre des règles reste
celui de la légende — contours en tête, comme sur les planches — sans commander
l'ordre de dessin. Ils sont tracés **une fois par station** et non par ligne :
les habitats d'une mosaïque partagent la géométrie de leur station, et sans le
filtre `est_dominant = 1` le même contour était retracé trois fois au même
endroit — l'empilement le faisait grossir et noircir, le trait paraissait sale.
0,16 mm en gris très sombre plutôt que 0,26 en noir : sur des aplats clairs, un
trait épais fait ressortir le découpage plus que le propos de la carte.

**Mosaïques : deux représentations, choisies au chargement** (`MODES` dans
`ui/export_layers.py`). Aucune convention nationale ne tranche — le guide
MNHN/CBN 2005 normalise le modèle de données, pas la sémiologie — d'où le choix
laissé à l'utilisateur, le mode figurant dans le nom de la couche pour que deux
représentations des mêmes données cohabitent.

| Mode | Mise en œuvre |
|---|---|
| `bandes` | `QgsGeometryGeneratorSymbolLayer` découpant des bandes horizontales |
| `damier` | grille régulière, mailles affectées par déficit, stockées en WKT et relues par `geom_from_wkt` |
| `enjeux` | une règle par niveau d'enjeu de la station, contours d'habitats en passe de dessin supérieure |
| `pee` | les bandes, plus une règle par espèce exotique ; les points sont posés au chargement et relus par `map_get(from_json(…))` |

Quatre autres figurés ont été construits, rendus sur les données réelles, puis
**écartés** ; le détail vaut d'être gardé, ne serait-ce que pour ne pas les
reproposer :

| Écarté | Pourquoi |
|---|---|
| hachures colorées superposées | illisible dès que la carte se densifie ; il fallait deviner qu'une hachure reprenait la couleur d'un autre poste de légende |
| diagramme circulaire, couche par rang, aplat + étiquette | tous privilégient l'habitat dominant, ou demandent d'allumer les couches une à une |
| semis de points | dit une densité, pas une surface, et laisse le dominant seul en aplat |
| cercles et carrés concentriques | surfaces exactes, mais la lecture centre-bord suggère une organisation que la donnée ne contient pas, et un rond au milieu d'une parcelle se confond avec une mare |
| damier de pois ronds | trop chargé sur les stations petites ou étroites — les haies viraient au chapelet |

Le **damier** ne partage pas le polygone dans un sens de lecture : il le
quadrille, et la proportion se lit au NOMBRE de mailles. C'est le seul mode qui
ne suggère aucune organisation spatiale — là où les bandes se lisent de haut en
bas — alors que la donnée n'en contient aucune. Les
mailles reviennent aux habitats **par déficit** : à chaque maille, celui qui est
le plus loin de sa surface due la prend, si bien que les arrondis ne s'accumulent
pas et que les habitats s'alternent d'eux-mêmes. Le parcours suit la suite R2 de
Roberts ; ligne par ligne, il aurait refait des bandes. Un habitat trop
minoritaire pour décrocher une maille s'en voit céder une par le mieux servi —
mieux vaut 1,6 % de trop qu'un habitat relevé mais absent de la carte.

La précision du WKT est **calée sur la maille** (`_decimales`), jamais fixée
d'avance : les exports GeoNature arrivent en **degrés**, où une décimale vaut
onze kilomètres. Écrite à une décimale — un choix qui valait dix centimètres en
Lambert 93 — la géométrie s'effondrait sur un point et **toutes les mosaïques
ressortaient vides**, sans la moindre erreur au chargement. Deux chiffres de plus
que la maille suffisent, soit un centième de maille. `tests/test_export_layers.py`
monte le damier dans les deux unités pour que la panne ne revienne pas.

Mesuré sur carré, rectangle allongé et L concave, 64 mailles visées : **50,0 /
29,7 / 20,3 %** pour un 50/30/20 et **59,4 / 37,5 / 1,6 / 1,6 %** pour un
60/37/2/1, l'union des mailles couvrant le polygone au millionième près et sans
chevauchement. Les mailles voisines d'un même habitat sont **fusionnées** avant
écriture : invisible à l'écran, mais les côtés communs quittent le fichier
(910 → 601 Ko sur 200 stations dont 100 en mosaïque).

**Tous les habitats sont dessinés, CÔTE À CÔTE**, chacun sur la part du polygone
qui revient à son recouvrement, découpée par un
`QgsGeometryGeneratorSymbolLayer`. Plus aucune superposition : chaque habitat
garde un aplat franc, et la carte a la lisibilité d'une carte mono-habitat quelle
que soit sa densité.

**Les hauteurs de coupe des bandes sont calculées par dichotomie au chargement**
(`_poser_coupes`), jamais déduites d'une fraction de la hauteur : sur un carré ou
un rectangle allongé le partage naïf tombe juste, mais sur une forme en L — banale
en cartographie d'habitats — il donne **68,8 / 18,8 / 12,5 %** au lieu de
50 / 30 / 20, la partie basse étant plus large. On cherche donc directement la
hauteur sous laquelle le polygone couvre la surface voulue : 24 itérations par
borne, une fois pour toutes, mesuré ensuite à 50,0 / 30,0 / 20,0 % sur les trois
formes. Le même écueil avait fait écarter les anneaux à rayon ∝ √part, qui
donnaient 30 / 9 / 61 sur un rectangle allongé.

Trois points d'implémentation :

- les parts cumulées sont calculées **en Python à l'export** (`_bandes`) et non
  par expression : un `aggregate` par entité au rendu serait ruineux ;
- les parts ne portent **pas de contour** — il dessinerait de fausses limites
  d'habitat ; un contour unique par station est tiré par l'entité dominante ;
- leurs bords sont **estompés** (`QgsBlurEffect`, 0,3 mm, méthode `StackBlur`)
  tandis que ce contour reste net : la limite relevée sur le terrain et le
  partage conventionnel ne doivent pas se lire pareil. L'effet est posé sur la
  COUCHE de symbole (`setPaintEffect` n'existe pas sur `QgsSymbol`), réglé en
  millimètres pour tenir à l'écran comme à 300 ppp, et **seulement sur les
  mosaïques** — un polygone à un seul habitat n'a aucune séparation interne. Les
  deux variantes tiennent dans un même symbole, chacune s'effaçant quand l'autre
  s'applique, pour que la légende garde une entrée par habitat ;
- les **niveaux de symboles** deviennent inutiles, les parts ne se recouvrant
  plus.

**Limite assumée** : le figuré dit la *proportion*, pas la *localisation* — la
donnée ne contient pas où se trouve chaque habitat dans le polygone. C'est une
convention de lecture, comme un diagramme. Le guide méthodologique national
(MNHN/CBN 2005) ne normalise d'ailleurs que le modèle de données, pas la
sémiologie ; les cartes publiées traitent le plus souvent la mosaïque comme un
poste de légende composite (couleur du dominant + surcharge), ce que cette
représentation remplace par un partage explicite.

L'infobulle donne la composition chiffrée, que le figuré ne dit pas.

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

**Libellé HABREF** — la colonne `Habitat (HABREF)` (clé `champs.HABREF`) montre à
quoi le `cd_hab` renvoie vraiment, à côté du `nom_cite` que le botaniste a écrit :
c'est ainsi qu'on repère une détermination dont le code ne correspond plus au nom.
Elle n'est pas dans la base — `Contexte.poser_libelles_habref()` l'écrit sur les
dicts d'habitat au chargement de la table, pour que la valeur circule comme les
autres (affichage, infobulle, copie TSV, tri) plutôt que par un cas particulier
dans le modèle. `lecture_seule` et `cellule=False` la tiennent hors de tout
enregistrement.

Les libellés viennent de `GET habref/habitat/<cd_hab>`, **un appel par code**, et
sont mis en cache dans la **base locale** (table `habref_libelles`) : sans cela,
chaque ouverture de la table rejouerait des dizaines d'allers-retours. Ils ont
d'abord été rangés dans `config.json` — c'était une faute : un fichier de
PRÉFÉRENCES n'est pas un cache de données, rafraîchir un nom d'habitat y
demandait de l'éditer à la main, et une valeur bancale y restait pour toujours.
Le menu **Base locale… ▸ Recharger les libellés HABREF** vide la table ; les
libellés sont redemandés à l'ouverture suivante. Au premier lancement, l'ancien
cache de la configuration est versé en base — sans les valeurs qui ne sont qu'un
code — et la clé est retirée. La première
ouverture d'un gros jeu de données en demande au plus 40 (`LIBELLES_PAR_OUVERTURE`),
le reste venant aux ouvertures suivantes — le cache s'épaissit à chaque fois.
**Deux chemins pour un libellé**, parce que la fiche directe ne suffit pas. Un
habitat marqué `fg_validite = NR` — non retenu, c'est-à-dire un synonyme —
existe dans HABREF avec son `lb_hab_fr`, mais `GET habref/habitat/<cd_hab>` peut
le refuser. Relevé sur le `Brachypodio rupestris-Centaureion nemoralis`
(cd_hab 16415, `cd_typo` 18) : la base porte le nom, la colonne restait vide. À
défaut de fiche, on repasse donc par l'**autocomplétion**, sur le code lu en tête
du nom cité (`6.0.1.0.2 - …`, tel que le sélecteur HABREF l'écrit), en retenant
l'entrée dont le `cd_hab` correspond.

Hors ligne, la colonne reste partiellement vide : mieux vaut ça qu'une table qui
refuse de s'ouvrir. Encore faut-il pouvoir répondre à « pourquoi celui-là n'a pas
de nom ? » — la première version consignait l'échec en `debug` et laissait une
case muette. Désormais : la raison est journalisée en `info` code par code
(hors ligne, erreur du serveur, fiche sans libellé), l'infobulle de la case vide
la rappelle, et `_libelle_de_fiche()` accepte plusieurs formes de réponse.

La fiche et l'autocomplétion ne rendent d'ailleurs pas les mêmes champs : la
première donne `lb_hab_fr` / `lb_hab_fr_complet`, la seconde `search_name`, qui
vaut « code - nom ». On en retire le code plutôt que de se rabattre sur
`lb_code` — qui ferait afficher « 6.0.1.0.2 » dans une colonne intitulée
« Habitat », alors que le `cd_hab` est déjà dans la colonne d'à côté. Mieux vaut
une case vide, qui se voit et s'explique, qu'un code qui se fait passer pour un
nom.

**`id_station`** — première colonne de la table attributaire **et** de la liste
du dock. C'est l'identifiant de la station sur GeoNature : le même que dans la
base, dans les exports et dans l'interface web, donc celui qu'on cite dans un
courriel ou qu'on colle dans une requête. Une première version affichait un
numéro d'ordre inventé au chargement — lisible, mais qui ne désignait rien hors
de la fenêtre où il s'affichait.

Il est **vide tant que la station n'est pas synchronisée** : GeoNature ne le lui
a pas encore attribué. La liste du dock écrit alors un tiret plutôt qu'une case
vide, qui se lirait comme un oubli de saisie. Le champ est `lecture_seule` et
`cellule=False`, donc jamais dans `colonnes_modifiees()` — c'est le serveur qui
l'attribue, la table ne fait que le montrer.

Le fond des cellules, lui, suit le **rang de la station dans la grille**
(`Grille.rang_station`), tenu à part et non écrit dans le dict de la station :
une clé de plus finirait par se retrouver quelque part. Une station sur deux est
teintée sur toute la largeur de la ligne, ce qui a remplacé l'alternance ligne à
ligne de Qt (`setAlternatingRowColors`) : les deux rythmes se contrariaient, et
une mosaïque de trois habitats paraissait en compter six. C'est ce fond qui
continue de grouper les lignes quand `id_station` est encore vide.

Dans la liste du dock, la colonne porte aussi l'**identifiant local** en donnée
cachée (`UserRole`) : tout le panneau va le chercher sur la première colonne pour
savoir sur quelle station porte une action.

**Copier vers un tableur** — `Ctrl+C`, le bouton « Copier » et le menu
contextuel produisent du **TSV** (`processing/tableur.py`), le seul format que
LibreOffice et Excel collent sans rien demander. Les cellules contenant une
tabulation, un saut de ligne ou un guillemet sont encadrées à la convention CSV,
faute de quoi un commentaire de station sur deux lignes décalerait tout le
tableau — une erreur qu'on ne voit qu'après coup, une fois les colonnes
mélangées. La copie d'une **cellule seule** échappe à cette règle : on la recolle
le plus souvent dans un champ de saisie, où les guillemets seraient à effacer à
la main. « Copier tout » suit le proxy, donc les filtres et le tri à l'écran.

**Architecture** — toute la logique risquée (propagation, suivi des
modifications, application en masse, rétrogradation) est dans
`processing/grille.py`, **pur et testé sans Qt** ; `ui/attribute_table.py` n'en
est qu'un adaptateur.

---

## 6 ter. Mise en page cartographique

**La carte montre le SERVEUR, pas la base locale.** Une couche d'export est une
vue de GeoNature ; une station non synchronisée n'y est pas, et rien à l'écran ne
le signalerait. `_stations_en_attente(id_dataset)` les compte **dans la portée
retenue**, et le nombre est rappelé deux fois : dans la fenêtre de chargement
d'un export, et à la création d'une mise en page — le moment où la carte devient
un livrable. La portée compte : additionner les stations en attente de tous les
jeux de données serait du bruit, celles d'un autre JDD n'ayant rien à faire dans
cet export.

**Les fenêtres de choix rendent leur contenu défilant** (`rendre_defilant`),
boutons exceptés. Une taille écrite une fois pour toutes vieillit mal : on ajoute
un avertissement de synchronisation, un choix de figuré, une ligne d'aide, et les
champs se compriment jusqu'à se couper — sans que rien ne le signale. Avec un
ascenseur, la fenêtre peut être trop courte sans que rien ne disparaisse. Vérifié
en la forçant à 500 × 380 puis à 520 × 300 : aucun champ tronqué.

**La symbologie doit rester modifiable.** Chaque part de mosaïque est peinte par
une couche de symbole dont la couleur est **définie par données**, pour s'éteindre
quand elle ne s'applique pas — la variante « mosaïque » et la variante « station à
un seul habitat » cohabitent dans un même symbole, chacune transparente quand
l'autre s'applique, faute de quoi la légende compterait deux entrées par habitat.

L'expression écrivait la couleur EN TOUTES LETTRES. Elle l'imposait donc à
l'affichage : on changeait la couleur d'un habitat dans le panneau des couches,
la pastille de légende suivait, la carte gardait l'ancienne — et le style
enregistré dans le projet ne servait à rien. Elle lit désormais
`coalesce(@symbol_color, '<couleur d'origine>')` : la teinte vient du symbole, et
l'expression ne fait plus que ce pour quoi elle est là, allumer ou éteindre.
`coalesce` couvre une version de QGIS qui ne connaîtrait pas la variable, où
l'expression rendrait NULL — donc une carte blanche.

> Vérifié au rendu, dans les deux modes : une règle recolorée en magenta passe
> de 0 à plus de 2 700 pixels magenta à l'écran.

**Une couche d'export appartient au PROJET, pas à la session du plugin.**
`ExportLayerManager.cleanup()` les retirait au déchargement — c'est-à-dire à la
fermeture de QGIS comme au rechargement de l'extension — et un projet enregistré
après coup en ressortait amputé, avec le travail de symbologie perdu. Il ne
retire plus que le groupe **vide**. De même, recharger un même export ne remplace
plus la couche : `_nom_libre()` numérote (« … (2) »), fichier GeoJSON compris,
parce qu'une couche déjà chargée a pu être recolorée et enregistrée. Vérifié :
style retouché, projet écrit puis relu — la couleur revient.

**Le JDD ne se choisit pas dans la fenêtre d'export.** C'est celui du panneau, où
l'on travaille déjà ; le redemander posait une question dont la bonne réponse
était toujours la même, avec le risque de charger un export qui ne parle pas des
mêmes stations que la saisie en cours. Reste une case « tous les jeux de
données » pour la consultation.

**Le plugin ne dessine pas de planche : il remplit celles de l'ANA.** Les
gabarits `.qpt` de la structure (`composer_templates` sur le partage) portent
déjà le bandeau vert, le logo, l'adresse, les mentions légales et la place des
cadres. Réinventer tout cela produirait une carte hors charte, à recomposer à
chaque fois.

`ui/print_layout.creer()` charge le gabarit et ne renseigne que ce qui varie :

| Objet du gabarit | Ce que le plugin y met |
|---|---|
| nom de la mise en page | le titre — les gabarits ANA titrent par `@layout_name` |
| `Sous-titre` | le texte saisi, **ou rien** : sans cela le « Sous-titre ou texte complémentaire » du gabarit partirait à l'impression |
| `Carte principale` | l'emprise (vue courante ou couche entière), le CRS du canevas, et **la pile de couches du canevas** — fond de plan compris |
| `Légende` | liée à la carte, filtrée sur elle, réduite à la couche d'habitats |
| `Échelle` | liée à la carte, remise en mètres |
| `@fond_bd_ortho` · `@fond_scan25` · `@fond_cartes_ign` | le fond choisi, **les deux autres remises à vide** — citer un fond qu'on n'affiche pas est une erreur de source |
| `@footer_text` | « ANA-CEN Ariège — <date> » |

**Aucun cadre n'est déplacé** : la charte appartient à la structure. La seule
retouche est la taille du texte de la légende, et pour cause — c'est la seule
chose que le gabarit ne peut pas prévoir.

**La légende est le point de rupture.** Une carte d'habitats en compte trois sur
un secteur homogène et quarante sur une mosaïque, et la colonne d'un gabarit A4
n'en tient pas quarante, à aucune taille lisible.

- la place disponible n'est **pas** la taille du cadre. Celui du gabarit A4 fait
  4 × 7,5 mm et grandit à son contenu ; s'y fier réduirait le texte à 5 pt pour
  tenir dans 8 mm alors que la colonne en offre 130. `mise_en_page.espace_libre()`
  cherche donc jusqu'où le cadre peut s'étendre avant de buter sur un voisin, en
  ignorant ceux qui l'**englobent** — le fond de page et la carte pleine page
  sont sous lui, pas devant ;
- **l'encombrement n'est pas calculé, il est MESURÉ** (`print_layout._essayer`).
  Une première version l'estimait au caractère : plausible, et faux, parce que la
  hauteur d'une entrée dépend du symbole, des marges de groupe et du rendu de la
  police. On applique donc chaque combinaison (taille, colonnes) et on demande à
  QGIS ce qu'elle donne. Attention, `rect()` **ne convient pas** : hors écran il
  rend la taille du CADRE et non celle du contenu, et une légende trop haute
  paraît alors tenir. La mesure juste est
  `QgsLegendRenderer(model, settings).minimumSize(contexte)` ;
- **la taille se règle sur la largeur autant que sur la hauteur.** QGIS ne coupe
  pas les libellés d'une légende : il ÉLARGIT le cadre. Un « Tetragonolobo
  maritimi-Mesobromenion erecti (26.0.2.0.3.3) » pousse donc la légende
  par-dessus la carte, hors de sa colonne — c'est le débordement qu'on voit en
  premier ;
- **la page de légende reprend l'habillage de la page 1**
  (`_habiller_pages_suivantes`) : bandeau, titre, logo, adresse, sources, pied de
  page, à la même place. Une page de légende nue ne s'identifie pas — sortie du
  PDF, imprimée seule, plus rien ne dit de quelle carte elle est la légende ni
  qui l'a produite. Sont exclus les cartes, la légende, et la **barre d'échelle**,
  qui sans carte ne veut rien dire et ferait prendre la page pour une carte.
  La copie passe par une **sérialisation XML** — les objets de mise en page n'ont
  pas de `clone()` en Python — avec deux pièges, tous deux silencieux :
  **l'identifiant unique doit être effacé** de l'élément avant relecture, sinon
  `readXml` le reprend tel quel et la copie devient un homonyme parfait de
  l'original ; QGIS ne sait alors plus lequel des deux il manipule, les deux se
  dessinent à l'écran mais **l'export sort la page de légende nue**. Et il faut
  **`refresh()`** après ajout : une image embarquée en base64 et une étiquette en
  expression ne sont décodées qu'au rafraîchissement, sans quoi le bandeau existe
  à la bonne place et s'imprime blanc.
  La légende est ensuite **recalée** dans la bande restée libre
  (`_recadrer_legende`) : posée avant l'habillage, elle passait sous le titre.
  Un objet large d'au moins 60 % de la page est tenu pour un **bandeau** et
  borne la HAUTEUR ; en deçà c'est un cartouche, qui borne la LARGEUR. Les
  confondre coûtait 46 mm de hauteur à toute la légende pour un bloc large d'un
  quart de page ;
- **si rien ne tient, la légende part sur une DEUXIÈME PAGE** (`_page_dediee`),
  en pleine page et en colonnes, plutôt que d'être coupée. La carte n'y perd
  rien : dans les gabarits ANA elle occupe déjà toute la page, la colonne de
  légende était posée par-dessus. La couper aurait été le pire des cas — QGIS le
  fait sans un mot, et on lit une carte à laquelle il manque des postes sans
  pouvoir s'en apercevoir.

> Vérifié sur l'export réel (114 stations, 42 postes de légende) avec
> `carte_seule_pleine_page_a4_cen.qpt` : fond de plan conservé sous les
> polygones, échelle graduée 0-100-200 m, légende complète sur une page 2 à 9 pt
> et deux colonnes, mentions lisibles, deux planches du même nom créées d'affilée
> sans erreur.

**Les grands milieux sont EN CAPITALES** dans la légende. QGIS rend les
règles-groupes d'un rendu par règles comme de simples entrées
(`QgsSymbolLegendNode`), au même style que les habitats : impossible de les
mettre en gras par `setStyleFont`, elles se lisaient donc à la même hauteur que
les habitats sans qu'on voie que c'étaient des titres. La capitale est le procédé
classique quand la graisse n'est pas disponible.

**Les intitulés techniques sont effacés** de la légende : sans cela elle s'ouvre
sur « OccHab (exports) » puis « Occhab complet (2026-01-01 → 2026-12-31) [bandes
proportionnelles] » — le nom du groupe de couches et celui du fichier chargé. Ce
sont des repères de travail, pas des postes de légende. Les groupes de projet
sont aplatis (`_degrouper`, **par clones** : `removeChildNode` détruit le nœud, et
le déplacer lève « QgsLayerTreeLayer has been deleted ») et le nom de couche
passe en style `Hidden`. Restent les grands milieux, que le rendu par règles
porte déjà en sous-groupes.

**Quatre pièges d'API**, tous silencieux :

- **`layoutManager().addLayout()` DÉTRUIT la mise en page** si une autre porte
  déjà ce nom. L'objet Python survit, son C++ a disparu, et le premier accès
  lève « wrapped C/C++ object of type QgsPrintLayout has been deleted » — sur
  la ligne d'après, loin de la cause. D'où `_nom_unique()`, qui numérote, et le
  contrôle de la valeur de retour ;
- `carte.setCrs()` sans reprojeter l'emprise donne une **carte vide** et une
  échelle à 1:0. Les couches d'export arrivent en degrés (WGS84), le canevas est
  en Lambert 93 : `_cadrer()` transforme l'emprise avant de cadrer ;
- `carte.setLayers([couche])` **efface le fond de plan**. On passe la pile du
  canevas (`iface.mapCanvas().layers()`) ; seule la LÉGENDE est restreinte à la
  couche d'habitats ;
- `legende.style(x).setTextFormat(...)` travaille sur un objet **temporaire**,
  détruit à la fin de l'expression : Qt lève « wrapped C/C++ object has been
  deleted ». On passe par `setStyleFont()`.

**QtWebKit** — les blocs « Sources », « Adresse » et « Fond » des gabarits ANA
sont des `QgsLayoutItemHtml`, seul objet de mise en page à réclamer WebKit.
Plusieurs paquets QGIS de Debian et d'Ubuntu sont construits sans lui : QGIS les
remplace alors par un pavé rouge « WebKit not available », à l'écran comme dans
le PDF.

`_sans_webkit()` les **convertit en étiquettes en mode HTML**, qui rendent le
même balisage (`<strong>`, `<br />`) par le moteur de texte de Qt, présent
partout. Le gabarit sur disque n'est pas touché. Deux détails :

- la feuille de style ne survit pas à la conversion, et une étiquette ne réduit
  jamais son texte : sans corps imposé, l'adresse s'affiche à la taille par
  défaut, à cheval sur le bandeau de pied. `mise_en_page.taille_pour_bloc()`
  choisit un corps, appliqué **à l'objet** (`setTextFormat`) et pas seulement en
  CSS — en mode HTML, QGIS part de la police de l'objet ;
- la mention du fond est figée dans le gabarit (SCAN25 dans les nôtres). La
  laisser telle quelle citerait une source qu'on n'affiche pas : elle est
  réécrite depuis le choix « Fond de plan cité » (`gabarits.MENTIONS_FOND`).

---

### Reconnexion d'une session à l'autre

Le mot de passe n'est **nulle part** dans le plugin : il vit dans le gestionnaire
d'authentification de QGIS, qui le chiffre. Seuls l'URL et l'identifiant de
configuration (`geonature.authcfg`) sont mémorisés. Rouvrir QGIS ne perdait donc
que le **jeton de session** — et obligeait à refaire le tour du dialogue pour
retrouver des identifiants que la machine avait déjà.

`OccHabDockWidget._reconnecter()` reprend la session à l'ouverture du dock, avec
trois garde-fous, parce qu'un plugin qui parle au réseau au démarrage de QGIS se
fait vite détester :

- **rien sans mot de passe principal déjà saisi.** Lire une configuration
  d'authentification le réclame, et le demander de nous-même ferait surgir une
  fenêtre que personne n'a appelée. `masterPasswordIsSet()` sert de test ; s'il
  est faux, on ne tente rien et le bouton « Connexion » reste le chemin normal ;
- **aucun message en cas d'échec.** Hors ligne — le cas d'usage même de cette
  extension — la tentative échoue, et c'est normal. Mesuré à 0,3 s de démarrage
  supplémentaire contre un serveur injoignable, sans exception ni fenêtre ;
- **désactivable** par `geonature.reconnexion_auto = false`.

---

## 6 quater. Déterminer dans le catalogue des végétations, arbitrer les correspondances

### Le problème

Les correspondances entre typologies calculées depuis HABREF (§ « Correspondances
entre typologies ») ne sont pas toujours justes, et la bonne **dépend de la
station** : une même alliance ne se traduit pas pareil d'un polygone à l'autre.
Le catalogue des végétations de l'Ariège porte d'ailleurs **quatre lignes** pour
`Luzulo luzuloidis – Fagion sylvaticae`, qui ne diffèrent que par leurs codes.
Il faut donc que le botaniste puisse trancher, station par station, et que son
arbitrage **prime** sur le calcul.

### Le catalogue, importé une fois

`scripts/import_typologie.py` transforme le tableur des botanistes
(`0_Typologie.xlsx`, feuille *Classif*, qui **fait autorité**) en
`resources/typologie/dictionnaire_typologie.csv`, livré avec le plugin. Le script
tourne hors QGIS, n'écrit **jamais** dans le fichier source, et met ses
résolutions HABREF en cache — une seconde exécution est instantanée.

```
python3 scripts/import_typologie.py CHEMIN/0_Typologie.xlsx --sortie resources/typologie
```

Trois règles portent l'essentiel :

| Règle | Pourquoi |
|---|---|
| **Ancrage** | 43 alliances sont absentes de HABREF — le catalogue diverge délibérément du Prodrome. `cd_hab` étant obligatoire, on y met le code CORINE (à défaut EUNIS) de la ligne |
| **Routage Natura 2000** | La colonne « Natura 2000 » du tableur mélange deux typologies HABREF : `6510` (intérêt communautaire) et `6510-1` (Cahiers d'habitats). Un code suffixé part vers les Cahiers |
| **Tirets** | Le tableur écrit `–`, HABREF `-`. Sans normalisation, la résolution tombe de 81 % à 63 %, **en silence** |

Le second fichier produit, `anomalies_typologie.csv`, n'est pas un sous-produit :
c'est la liste de travail des botanistes, et le seul garde-fou contre un import
qui aurait l'air complet sans l'être. `--complement` accepte un CSV de
corrections provisoires (`ligne_xlsx;corine;eunis;n2000`), chacune ressortant en
anomalie « à reporter dans le tableur » — un correctif de circonstance ne doit
pas devenir une seconde source de vérité.

> Le script **ne lit pas les couleurs** des cellules. Elles portent pourtant du
> sens (« divergence avec le PVF II », « présence incertaine en Ariège ») : tant
> qu'elles ne sont pas des colonnes explicites, cette information reste dans le
> tableur. Le script le rappelle à chaque exécution.

### Une ancre n'est pas une détermination

C'est la distinction qui commande tout le reste. Quand `cd_hab` porte un code
emprunté, la clé `determination` du bloc le dit :

```json
{"determination": {"nom": "Salicion pyrenaicae", "ancre": "CORINE_biotopes"}}
```

Sans elle, rien ne distinguerait un code CORINE **choisi** comme détermination
d'un code CORINE **posé faute de mieux**. Le formulaire l'affiche en clair, et
l'export la sort en colonne `alliance` — vide ne veut donc pas dire « pas
d'alliance », mais « le `cd_hab` est lui-même la détermination ».

### Choisir, pas taper un code

Un botaniste connaît son alliance, pas le code EUNIS d'arrivée. Chaque typologie
a donc sa ligne dans le formulaire, garnie de propositions **avec leurs
libellés** — « 41.112 — Hêtraies montagnardes à Luzule » se choisit, « 41.112 »
se devine. Deux sources, dans cet ordre :

1. le **catalogue**, quand il connaît le `cd_hab` déterminé ;
2. les **correspondances que HABREF publie** dans la fiche de l'habitat
   (`/habref/habitat/<cd_hab>`), sinon.

Faute des deux, la ligne reste en recherche libre — qui accepte un nom aussi bien
qu'un code. La saisie n'est **jamais** bloquée.

Deux règles d'ergonomie qui sont en réalité des règles de données :

- **rien n'est retenu d'office dès qu'il y a plusieurs candidats.** Trancher en
  silence une question que le catalogue laisse ouverte produirait de la donnée
  fausse et muette ; la ligne affiche « n propositions — à choisir » ;
- **la typologie de la détermination ne pose pas de question.** Un habitat
  déterminé en EUNIS *est* sa propre correspondance EUNIS ; la ligne se remplit
  de son code et se verrouille. Rien n'est enregistré pour autant — ce serait
  recopier le `cd_hab`, avec le risque que les deux divergent.

### Trois provenances

| `src` | Sens |
|---|---|
| `catalogue` | repris du catalogue des végétations tel quel |
| `habref` | proposé par HABREF et accepté tel quel |
| `manuel` | **arbitré par un botaniste** — le seul qui atteste d'un contrôle |

C'est ce qui permet, en fin de campagne, de lister ce qui a été vérifié. L'export
du plugin l'isole dans `corresp_manu` ; la vue SQL l'expose par typologie dans
`habitat_*_source`, où s'ajoute `determination` (l'habitat était déjà dans la
typologie visée) et le vide (rien de saisi : c'est `habref_equivalents` qui a
parlé, et `habitat_*_rang` dit ce que vaut sa déduction).

### Colonnes ajoutées

**Export du plugin** (`processing/export.py`) : `alliance`, `ancre_typo`,
`corine_cite`, `eunis_cite`, `n2000_cite`, `cahiers_cite`, `corresp_manu`.

**Vue `gn_exports.v_occhab_complet`** : `habitat_alliance`,
`habitat_ancre_typologie`, et pour chacune des quatre typologies une colonne
`habitat_*_source`. Les colonnes `habitat_code_*` / `habitat_nom_*` existantes
**changent de sémantique** : elles rendent désormais la valeur saisie quand il y
en a une, le calcul sinon. Le libellé de la valeur saisie est résolu par jointure
sur HABREF, jamais lu depuis la donnée : HABREF fait foi et peut le corriger
d'une version à l'autre.

### Limites connues

- Le catalogue est **désactivé dans les cellules de la table attributaire** :
  une cellule n'écrit que le nom cité et le `cd_hab`, elle y poserait une ancre
  sans la détermination qui dit que c'en est une. Le catalogue se choisit au
  formulaire. Les autres éditions de la table sont sûres — `champs.ecrire()`
  passe par `merge_eval`, donc modifier un enjeu ne détruit pas les
  correspondances de la même ligne (un test le verrouille).
- Seules les correspondances **directes** de HABREF sont proposées. Il en publie
  aussi à deux sauts, mais sans libellé : les proposer reviendrait à afficher des
  codes nus. Elles restent du ressort de la vue, qui les résout côté serveur.
- Le choix d'un habitat déclenche **un appel réseau** (fiche HABREF), mis en
  cache par `cd_hab` pour la durée du formulaire. Hors connexion, aucune
  proposition : les lignes passent en recherche libre.

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
    │                 geojson_wkt.py             # GeoJSON → WKT, sans QgsJsonUtils (pur, testé)
    │                 tableur.py                 # mise en TSV pour le presse-papiers (pur, testé)
    │                 gabarits.py                # repérage des .qpt de mise en page (pur, testé)
    │                 mise_en_page.py            # dimensionnement de la légende (pur, testé)
    │                 habitat_style.py           # classes de milieu EUNIS, mosaïques (pur, testé)
    │                 geometry.py                # WKT/GeoJSON, reprojection 4326
    ├── sql/          v_occhab_complet.sql       # vue d'export, prête à exécuter (PostgreSQL 15)
    └── ui/           dock_widget.py             # dock principal
                      print_layout.py            # planche cartographique depuis un gabarit ANA
                      layout_dialog.py           # choix du gabarit, du titre, du cadrage
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
