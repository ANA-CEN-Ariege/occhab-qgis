# Guide utilisateur — OccHab GeoNature (extension QGIS)

Ce guide s'adresse aux **utilisateurs** de l'ANA-CEN Ariège qui
saisissent des données d'habitats dans le module **OccHab** de GeoNature depuis
QGIS. Il couvre l'installation, la première configuration et l'usage quotidien.

> Vous cherchez les détails techniques (modèle de données, API, architecture) ?
> Voir le [README](README.md).

---

## Sommaire

1. [À quoi sert le plugin](#1-à-quoi-sert-le-plugin)
2. [Prérequis](#2-prérequis)
3. [Installation](#3-installation)
4. [Première configuration (connexion)](#4-première-configuration-connexion)
5. [Découvrir l'interface](#5-découvrir-linterface)
6. [Saisir une station et ses habitats](#6-saisir-une-station-et-ses-habitats)
7. [Modifier une station](#7-modifier-une-station)
8. [Récupérer des stations depuis le serveur](#8-récupérer-des-stations-depuis-le-serveur)
9. [Synchroniser avec GeoNature](#9-synchroniser-avec-geonature)
10. [Supprimer : base locale ou serveur](#10-supprimer--base-locale-ou-serveur)
11. [Travailler hors-ligne](#11-travailler-hors-ligne)
12. [Sauvegarde et export des données](#12-sauvegarde-et-export-des-données)
13. [Les champs « enjeu / état / zone humide / recouvrement »](#13-les-champs-enjeu--état--zone-humide--recouvrement)
13 bis. [Brouillon, validé, et la table des stations](#13-bis-brouillon-validé-et-la-table-des-stations)
13 ter. [Sortir une carte : la mise en page](#13-ter-sortir-une-carte--la-mise-en-page)
14. [Dépannage (FAQ)](#14-dépannage-faq)
15. [Glossaire](#15-glossaire)

---

## 1. À quoi sert le plugin

L'extension **OccHab GeoNature** permet de saisir, **même sans
connexion Internet**, des **stations** (objets géographiques : point, ligne ou
polygone) et les **habitats** qui s'y trouvent, puis de les **envoyer vers
GeoNature** une fois de retour au bureau (ou dès qu'une connexion est
disponible).

Concrètement, vous pouvez :

- **dessiner** une station directement sur la carte QGIS et laisser le plugin
  calculer sa **surface** et son **altitude** ;
- **décrire un ou plusieurs habitats** par station, avec recherche assistée dans
  le référentiel **HABREF** (Corine Biotopes, EUNIS…) ;
- renseigner des champs métier ANA — **niveau d'enjeu**, **état de conservation**,
  **zone humide** (oui / non / à vérifier), **recouvrement** — et les champs
  **Natura 2000** (typicité, dynamique, restauration, unité végétale…) ;
- **recopier** les renseignements d'un polygone déjà saisi sur d'autres, et
  reprendre automatiquement la saisie précédente d'un habitat au suivant ;
- travailler **en brouillon** et **valider** vos stations quand elles sont
  abouties ;
- voir et modifier **toutes vos stations et habitats dans un tableau**, y compris
  **en masse** sur une sélection ;
- **synchroniser** vos saisies avec GeoNature (création, modification,
  suppression) ;
- **consulter** les stations déjà présentes sur le serveur pour vous repérer et
  éviter les doublons ;
- **cartographier** : charger une couche d'habitats du serveur, colorée par
  habitat et regroupée par grand milieu, puis en tirer une **planche imprimable**
  à partir des gabarits de l'ANA (voir §13 ter).

---

## 2. Prérequis

- **QGIS 3.28 ou plus récent** (Windows, Linux ou macOS).
- Un **compte GeoNature** de votre instance (ex. celle de l'ANA-CEN Ariège), avec
  les **droits sur le module OccHab** (au minimum *Lire* et *Créer* ; *Modifier*
  et *Supprimer* pour éditer/effacer vos données). Voir §14 si vous obtenez une
  erreur de permissions.
- L'**URL de l'API GeoNature** de votre instance (elle ressemble à
  `https://votre-serveur/geonature/api`). Demandez-la à votre administrateur.

Aucune installation de base de données n'est nécessaire côté utilisateur : le
plugin gère un petit fichier local automatiquement.

---

## 3. Installation

### Méthode A — depuis le dépôt de l'ANA-CEN Ariège (recommandée)

L'extension est publiée sur le **dépôt d'extensions de l'ANA**, aux côtés des
autres outils maison (*Boîte à outils ANA-CEN Ariège*, *FluxCEN*…). C'est
l'installation la plus simple, avec **mises à jour automatiques** proposées par
QGIS.

**Une seule fois — ajouter le dépôt :**

1. Dans QGIS : menu **Extensions ▸ Installer/Gérer les extensions**.
2. Onglet **Paramètres**.
3. Cochez **« Afficher aussi les extensions expérimentales »**. L'extension est
   marquée expérimentale : sans cette case, elle **n'apparaîtra pas**, même une
   fois le dépôt ajouté.
4. Dans la section *Dépôts d'extensions*, cliquez **Ajouter…** et saisissez :
   - **Nom** : `ANA-CEN Ariège`
   - **URL** : `https://qgisplugins.ariegenature.fr/`
   - **Authentification** : laissez vide.
5. **OK** : le dépôt apparaît dans la liste, à l'état *connecté*.

**Ensuite — installer :**

6. Onglet **Toutes**, tapez **`OccHab GeoNature`** dans la recherche.
7. Sélectionnez-la et cliquez **Installer l'extension**.
8. Onglet **Installées** : vérifiez qu'elle est **cochée**.

> **L'URL pointe sur la racine du domaine**, barre oblique finale comprise :
> c'est là qu'est servi le fichier XML du dépôt. N'ajoutez **pas** `plugins.xml`
> à la fin, l'adresse ne répondrait pas.

> Quand une nouvelle version est déposée, QGIS vous la propose automatiquement
> (onglet *Mises à jour*).

### Méthode B — depuis un fichier ZIP

Utile hors ligne, en avant-première, ou si le dépôt n'est pas accessible :

1. Téléchargez le ZIP de la **dernière version** :
   **https://github.com/ANA-CEN-Ariege/occhab-qgis/releases/latest**
   → dans la section *Assets*, cliquez sur **`occhab-x.y.z.zip`**.
   *(lien direct de la dernière release : `…/releases/latest`)*
2. Dans QGIS : **Extensions ▸ Installer/Gérer les extensions ▸ Installer depuis un
   ZIP**, choisissez le fichier téléchargé, cliquez **Installer l'extension**.
3. Onglet **Installées** : vérifiez que **OccHab GeoNature** est **coché**.

> Si elle n'apparaît pas, cochez **« Afficher aussi les extensions
> expérimentales »** dans l'onglet *Paramètres*.

### Méthode C — copie manuelle du dossier

1. Copiez le dossier **`occhab`** dans le répertoire des extensions de votre
   profil QGIS :
   - Windows : `…\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
   - Linux : `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - macOS : `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
2. Redémarrez QGIS.
3. **Extensions ▸ Installer/Gérer les extensions ▸ Installées** → cochez
   **OccHab GeoNature**.

### ~~Méthode D — depuis le dépôt officiel plugins.qgis.org~~

> ⏸ **Voie mise en attente le temps de l'expérimentation.**
> ~~L'extension est aussi publiée sur le dépôt officiel des extensions QGIS,
> présent d'origine dans le gestionnaire.~~
> La version qui s'y trouve (**0.5.2**) est **plus ancienne** que celle du dépôt
> de l'ANA (**0.7.0**) : ne l'installez pas depuis là, vous n'auriez ni la mise
> en page cartographique, ni le copier-coller de polygone, ni les corrections de
> saisie. Utilisez la
> **méthode A**. Cette voie sera rouverte quand l'extension sortira de sa phase
> d'expérimentation.

### Rester connecté d'une session à l'autre

**Vous n'avez à vous connecter qu'une fois.** À la réouverture de QGIS, le plugin
reprend la session tout seul : vos identifiants sont dans le **gestionnaire
d'authentification de QGIS**, qui les chiffre — le plugin, lui, ne mémorise que
l'URL de l'API et la configuration à utiliser, jamais le mot de passe.

Deux cas où la reconnexion n'a pas lieu, et c'est voulu :

- **QGIS protège ses mots de passe par un mot de passe principal** que vous
  n'avez pas encore saisi dans cette session. Le plugin ne le réclame pas de
  lui-même — ce serait une fenêtre surgissant au démarrage, sans que vous l'ayez
  demandée. Cliquez « Connexion GeoNature… » quand vous en avez besoin : QGIS
  vous le demandera à ce moment-là.
  *Astuce* : dans **Préférences ▸ Options ▸ Authentification**, QGIS peut retenir
  ce mot de passe principal dans le trousseau du système ; la reconnexion devient
  alors totalement automatique.
- **Vous êtes hors ligne.** Le plugin démarre déconnecté, ce qui est son mode de
  travail normal : vous saisissez, vous synchroniserez plus tard.

Pour désactiver la reconnexion automatique, mettez `geonature.reconnexion_auto`
à `false` dans le fichier `config.json` du plugin (menu **Base locale… ▸ Ouvrir
le dossier**).

### Ouvrir le plugin

Une fois activé, cliquez sur son **icône dans la barre d'outils** (ou via le menu
**Extensions**) pour afficher le **panneau (dock)** « OccHab GeoNature », en
général ancré à droite de la fenêtre QGIS.

---

## 4. Première configuration (connexion)

L'authentification passe par le **système d'authentification de QGIS** (vos
identifiants sont **chiffrés** par QGIS ; le plugin ne stocke jamais votre mot de
passe).

### Étape 1 — Créer une configuration d'authentification (une seule fois)

1. Cliquez sur **« Connexion GeoNature… »** dans le dock.
2. Renseignez l'**URL de l'API** GeoNature (ex.
   `https://votre-serveur/geonature/api`).
3. En face de **Configuration d'authentification**, cliquez sur **« + »** pour en
   créer une :
   - **Type** : *Authentification de base* (*Basic*).
   - **Nom** : par ex. `GeoNature ANA`.
   - **Nom d'utilisateur** / **Mot de passe** : vos identifiants GeoNature.
   - Enregistrez. (QGIS peut demander de définir un **mot de passe principal**
     la première fois — c'est le coffre-fort qui chiffre vos identifiants.)
4. Sélectionnez cette configuration, puis **validez**.

### Étape 2 — Se connecter

Après validation, l'en-tête du dock affiche **« Connecté : Prénom Nom
(identifiant, id_role=…) »**. Le chargement des **JDD**, des listes déroulantes
(nomenclatures), du référentiel HABREF, des observateurs et de la couche serveur
se fait automatiquement.

> Les prochaines fois, il suffit de cliquer **« Connexion GeoNature… »** puis de
> valider : l'URL et la configuration d'auth sont mémorisées.

---

## 5. Découvrir l'interface

Le dock présente, de haut en bas : la **connexion + le JDD** (barre repliable),
vos **stations locales** avec leurs actions, puis le bloc **Serveur** :

```
┌─────────────────────────────────────────────────────────┐
│ ✓ Roy Cédric  ·  JDD : Puech Saint Sauveur    [changer]  │
│   Serveur : 12 station(s)                                 │
│─────────────────────────────────────────────────────────│
│ Mes stations                                    7 locales │
│ [✏ Éditer] [⬡ Géométrie ▾] [🔍 Zoom] [▦ Tableau] [🗑 Suppr.]│
│  ┌────────────────────┬───────────┬─────────────────┐     │
│  │ Habitat(s)         │ Date      │ Statut · synchro│     │
│  │ 41.711 — Bois de…  │ 2024-06-21│ ✔ Validée       │     │
│  │                    │           │ ✓ Synchronisée  │     │
│  └────────────────────┴───────────┴─────────────────┘     │
│  [＋ Nouvelle station ▾]                                  │
│─────────────────────────────────────────────────────────│
│ Serveur                                                   │
│  [Synchroniser (2)]  [Rafraîchir]                         │
│  [Récupérer une station du serveur… ▾]                    │
│─────────────────────────────────────────────────────────│
│ Base locale : occhab_local.db  [Base locale…] [Cartographier…]│
└─────────────────────────────────────────────────────────┘
```

- **Barre connexion + JDD** (repliable) : cliquez **« changer »** pour la déplier
  (se connecter, choisir le JDD, filtre « mes stations serveur ») ; elle se replie
  une fois le JDD choisi. La combo JDD est **cherchable** (tapez pour filtrer).
- **Mes stations** : le tableau de **vos** saisies. La **barre d'action
  au-dessus** agit sur la **ligne sélectionnée** (grisée sans sélection) :
  *Éditer*, *Géométrie ▾*, *Zoom*, *Supprimer* (destructif). *Supprimer* accepte
  une **multi-sélection** (Ctrl/Maj) pour effacer plusieurs stations d'un coup
  (voir §10). Les mêmes actions sont accessibles par **clic-droit** sur une ligne,
  et **double-clic** ouvre la station. **« ＋ Nouvelle station ▾ »** la crée (voir §6).
- **Serveur** : *Synchroniser*, *Rafraîchir*, *Récupérer une station du serveur…*
  — ces actions rapatrient des données **éditables** dans votre base.
- **Pied de panneau** : *Base locale…* (dossier, sauvegarde, exports) et
  *Cartographier…*, qui regroupe les deux temps d'une carte — charger la couche
  d'habitats depuis le serveur, puis en tirer une planche imprimable.
- **Astuce carte** : double-cliquer une station sur la carte (ou cliquer dessus
  avec l'outil **Identifier des entités**) ouvre son formulaire.
- **La sélection est commune à la liste et à la carte** : sélectionner des lignes
  dans la liste met les stations correspondantes en surbrillance sur la carte, et
  sélectionner des entités sur la carte (outil **Sélectionner**) sélectionne les
  lignes correspondantes. Pratique pour repérer où se trouve ce que vous êtes en
  train de modifier — et pour choisir un lot à la souris avant de le traiter.

### Les couches sur la carte

- **OccHab (local)** : vos stations, **colorées selon leur état** :
  - *À synchroniser* (pas encore envoyées ou modifiées),
  - *Synchronisée* (à jour sur GeoNature),
  - *Conflit* (modifiée aussi côté serveur — à résoudre),
  - *À supprimer* (marquée pour effacement),
- **OccHab (serveur)** : les stations déjà sur GeoNature pour le JDD choisi, en
  **bleu** et en **lecture seule** (contexte, non modifiable directement).

Ces deux groupes sont gérés automatiquement par le plugin : les couches sont
en lecture seule et reconstruites à chaque rafraîchissement (la base SQLite
locale reste la seule source de vérité). Un message s'affiche une fois par
session lors de leur première apparition dans le panneau Couches pour le
rappeler — évitez de les modifier, renommer, déplacer ou supprimer
manuellement : elles seraient simplement recréées au rafraîchissement
suivant.

### La colonne « Statut · synchro »

Elle répond à **deux questions différentes**, sur **deux pastilles empilées** —
la première dit où en est *votre travail*, la seconde où en est *l'envoi*.

**Pastille du haut — statut** (votre travail) :

| Statut         | Signification                                                  |
|----------------|----------------------------------------------------------------|
| **✎ Brouillon**| Saisie en cours, sur laquelle vous comptez revenir              |
| **✔ Validée**  | Travail abouti                                                  |

**Pastille du bas — synchronisation** (l'envoi vers GeoNature) :

| État affiché       | Signification                                              |
|--------------------|------------------------------------------------------------|
| **À synchroniser** | Créée ou modifiée localement, pas encore envoyée à GeoNature |
| **Synchronisée**   | Identique à la version GeoNature                           |
| **Conflit**        | Modifiée **aussi** sur GeoNature depuis votre dernière synchro — à résoudre |
| **À supprimer**    | Marquée pour suppression au prochain envoi (réversible)    |

> Les deux sont **indépendants** : un brouillon peut très bien être synchronisé
> (c'est même le but de la sauvegarde de fin de journée), et une station validée
> peut rester à envoyer.

---

## 6. Saisir une station et ses habitats

### Étape 1 — Créer la station et sa géométrie

Cliquez **« ＋ Nouvelle station ▾ »** et choisissez d'où vient la géométrie :

- **Dessiner un polygone** / **Dessiner un point** — dessinez sur la carte : clic
  gauche pour poser les sommets (l'**accrochage** QGIS est actif, pratique pour se
  caler sur des objets existants), **clic droit** pour terminer.
- **Copier la ou les entités sélectionnées (autre couche)** — sélectionnez d'abord
  une **ou plusieurs** entités dans une **autre couche** (parcellaire, ancien relevé,
  trace GPS…), puis choisissez ceci : leur forme est reprise (et reprojetée) pour la
  station.
  - **Une seule** entité sélectionnée → le formulaire habituel s'ouvre.
  - **Plusieurs** entités sélectionnées → **une station est créée par entité**. Un
    **seul formulaire** s'ouvre pour les **métadonnées communes** (JDD, dates,
    observateurs, commentaire, et éventuellement un habitat appliqué à toutes) ; le
    **nom est laissé vide** (à renseigner ensuite station par station) et la
    **surface / altitude** sont calculées pour chaque géométrie.
- **Dupliquer la station sélectionnée** — reprend d'une station existante son
  **JDD, ses dates, ses observateurs, tous ses attributs et ses habitats**, et vous
  fait **redessiner la géométrie** (du même type que l'original). Pratique quand le
  même habitat se répète d'un polygone à l'autre. La géométrie n'est jamais copiée,
  et la nouvelle station est bien une **création** (elle n'écrase pas l'originale).
  Disponible aussi par **clic droit** sur une ligne du tableau → **« Dupliquer »**.
- **Dessiner un polygone avec les renseignements copiés** — reprend les
  renseignements mis de côté par **« Copier les renseignements »** (voir ci-après) :
  ils restent disponibles pour **autant de stations que vous voulez**.
- **Sans géométrie (à tracer plus tard)** — ouvre directement le formulaire ; vous
  ajouterez la géométrie ensuite via **« Géométrie ▾ »**.

> **Recopier un polygone déjà renseigné.** Trois chemins, selon le moment :
>
> | Vous voulez… | Faites… |
> |---|---|
> | Renseigner un polygone **déjà tracé** comme un autre | **Clic droit** sur la station modèle → **« Copier les renseignements »**, puis sélectionnez la ou les stations à renseigner (Ctrl/Maj) → **clic droit → « Coller les renseignements »** |
> | Enchaîner **plusieurs nouvelles** stations identiques | **« Copier les renseignements »**, puis **« ＋ Nouvelle station ▾ → Dessiner un polygone avec les renseignements copiés »**, autant de fois que nécessaire |
> | Recopier une station **sans quitter le formulaire ouvert** | Bouton **« Reprendre une station renseignée… »**, en haut du formulaire |
>
> Dans les trois cas : **JDD, dates, observateurs, attributs, commentaire et
> habitats** sont repris ; la **géométrie**, le **nom** et le **statut**
> (brouillon / validée) de la station qui reçoit **ne changent pas**. Les habitats
> déjà présents sur la station qui reçoit sont **remplacés** — le plugin le dit et
> demande confirmation avant. Rien n'est enregistré tant que vous n'avez pas
> validé (formulaire) ou confirmé (collage). Les renseignements copiés restent
> disponibles jusqu'à la fermeture de QGIS.
>
> **Mosaïques photo-interprétées.** C'est le cas où ce geste fait gagner le plus
> de temps : renseignez **un** polygone type avec tous ses habitats, copiez-le,
> collez-le sur les polygones voisins (sélection multiple), puis **ajustez les
> coefficients** — soit dans la table attributaire (colonne *Recouvrement %*,
> une ligne par habitat, §12), soit en rouvrant chaque station. Vous n'avez plus
> à ressaisir la liste des habitats ni à vérifier que vous n'en oubliez aucun.

Le formulaire de la station s'ouvre. Pour un **polygone**, la **surface** (m²) et
l'**altitude min/max** sont déjà remplies automatiquement.

### Étape 2 — Renseigner la station

Le formulaire est à **deux niveaux**. L'**Essentiel** est toujours visible :

- **Jeu de données (JDD)** — *obligatoire*. Il est **déjà sélectionné** : le plugin
  retient le JDD choisi en haut du panneau, une fois pour toutes.
- **Nom de la station**, **dates** (début / fin).
- **Observateur(s)** — champ à **autocomplétion** : déroulez pour parcourir la
  liste, ou **tapez** un nom pour filtrer ; l'observateur choisi s'ajoute dessous
  (retirable par double-clic ou « Retirer »).
- **Unité végétale** et **nature de l'observation** (Natura 2000).
- **Niveau d'enjeu** / **état de conservation** (voir §13), **Commentaire**.

> **Reprise de la saisie précédente.** Dès la deuxième station, les
> **observateurs** de la saisie précédente sont **repris automatiquement**, ainsi
> que les **dates** si vous êtes toujours dans la même session QGIS. Une mention
> « ↺ … repris de la saisie précédente » l'indique sous les dates — elle est là
> pour vous inviter à **vérifier la date**. Les observateurs sont mémorisés d'une
> session à l'autre (une équipe change peu au cours d'une campagne) ; les dates,
> non : au redémarrage de QGIS, on repart de la date du jour. Tant qu'aucune
> station n'a été saisie, c'est l'utilisateur connecté qui est pré-ajouté comme
> observateur.

Les autres champs (**altitude**, **profondeur**, **surface**, **exposition**,
**type de sol**, **type de mosaïque**, **nature d'objet géographique**, **échelle
de numérisation**) sont sous **« ▸ Détails »** — cliquez pour déplier. En
**édition**, cette section se déplie d'elle-même si ces champs sont déjà
renseignés.

> Certains champs (type de sol, mosaïque…) ne s'affichent que si votre instance
> GeoNature les propose. **Surface** et **altitude** sont calculées automatiquement.

### Étape 3 — Ajouter un ou plusieurs habitats (facultatif)

L'habitat n'est **pas obligatoire** : vous pouvez enregistrer une station sans
habitat (géométrie d'abord) et la **qualifier plus tard** en l'éditant. Pour en
ajouter, dans le formulaire :

- **Nom cité** — commencez à taper le nom (ou le code) de l'habitat : une
  **liste HABREF** apparaît, préfixée par la typologie (« CORINE biotopes 41.2 -
  Chênaies-charmaies »). En choisissant une proposition, le **code `cd_hab`** est
  rempli automatiquement. Le nom cité reste ensuite librement modifiable.
  Si rien n'apparaît, un message sous le champ vous dit pourquoi : **hors
  connexion** (la recherche HABREF a besoin du serveur — saisissez alors le nom
  et le code à la main), erreur du serveur, ou aucun habitat trouvé.
- **Filtre typologie** — pour cibler la recherche (Corine, EUNIS…).
- **Déterminateur** — utilisateur connecté par défaut, saisie libre possible.
- **Type de détermination**, **intérêt communautaire**.
- **Technique de collecte** — **« In situ » par défaut**.
- **Recouvrement (%)** — pré-sélectionne automatiquement la classe d'**abondance**.
- **Niveau d'enjeu** / **état de conservation** de l'habitat (voir §13), puis le
  **critère d'évaluation** qui le justifie et les **PEE** (plantes exotiques
  envahissantes, 3 taxons au plus séparés par « ; »).

**Abondance** et **sensibilité** sont repliées **en bas** du formulaire, sous
**« ▸ Abondance et sensibilité »** : l'abondance se déduit du recouvrement saisi
plus haut et la sensibilité vaut **« Non sensible »** par défaut. La section
s'ouvre d'elle-même quand une valeur s'écarte de ce défaut — rien n'est caché
sans le dire.

> **Reprise de la saisie précédente.** Chaque **nouvel** habitat reprend les
> champs du **dernier habitat saisi** : type de détermination, déterminateur,
> technique, intérêt communautaire, sensibilité, enjeu, état de conservation,
> critère, PEE, typicité… Une mention « ↺ … » l'indique en haut du formulaire —
> **vérifiez ces valeurs**. Ne sont **jamais** repris : le **nom cité**, le
> **code cd_hab**, le **recouvrement** et l'**abondance**, propres à chaque
> habitat. C'est mémorisé d'une session QGIS à l'autre ; dans une station en
> mosaïque, c'est l'habitat précédent de la **même** station qui sert de modèle.
> Pour recopier un habitat **à l'identique**, utilisez plutôt le copier-coller
> de renseignements (§6, étape 1).

Répétez pour chaque habitat. La **liste des habitats** de la station affiche, pour
chacun, son **% de recouvrement**. Un garde-fou demande confirmation avant de
**retirer** un habitat. Pour en retirer **plusieurs d'un coup**, sélectionnez-les
avec **Ctrl** (ajouter/enlever) ou **Maj** (une plage), puis **« Retirer »**.

### Étape 4 — Enregistrer

Validez le formulaire : la station apparaît dans le tableau **« Mes stations
(local) »**, identifiée par son premier habitat (ex. « 41.2 - Chênaies-charmaies
(+2) » = 3 habitats), en état **À synchroniser**. Une station **sans habitat**
s'affiche sous son **nom** (ou « (station sans habitat) » si le nom est vide).

---

## 7. Modifier une station

Ouvrez une station de plusieurs façons : **« Éditer »** (barre au-dessus du
tableau), **double-clic** sur la ligne, **clic-droit → Éditer**, ou — directement
sur la carte — **double-clic** / clic avec l'outil **Identifier des entités**.

- **Attributs / habitats** : modifiez la station, ajoutez/retirez des habitats.
- **Géométrie** : bouton **« Géométrie ▾ »** (ou clic-droit → *Modifier la
  géométrie*) :
  - *Redessiner / éditer sur la carte* : déplacez/ajoutez/supprimez les sommets,
    puis **Valider** (ou **Annuler**) via la barre de message. *(Pendant l'édition,
    **Ctrl+Z** annule le dernier geste ; « Annuler » abandonne toute l'édition.)*
  - *Copier l'entité sélectionnée d'une autre couche* : remplace la géométrie par
    celle d'une entité sélectionnée dans une autre couche.
  - *Rétablir la géométrie précédente* : **annule** le dernier changement de
    géométrie (re-cliquez pour **refaire** — c'est un échange). Disponible tant que
    la station n'est **pas encore synchronisée** ; une fois envoyée, ce tampon est
    libéré (l'option se grise).

Toute modification repasse la station en **À synchroniser**.

> **Annuler une autre modification ?** En dehors de la géométrie, une modification
> **enregistrée** écrase l'ancienne valeur en local (pas d'historique). Pour une
> station déjà sur GeoNature, vous pouvez restaurer la version serveur via
> *Récupérer du serveur* (§8) — au prix de vos modifications locales non
> synchronisées.

---

## 8. Récupérer des stations depuis le serveur

Utile pour **corriger une station déjà envoyée**, **repartir d'un autre poste**,
ou **restaurer** une base locale perdue. Choisissez d'abord le bon **JDD**.

Cliquez **« Récupérer une station du serveur… »** — **deux façons** :

- **Depuis la carte (sélection)** : sélectionnez une ou plusieurs stations sur la
  couche **« OccHab (serveur) »** avec l'**outil de sélection de QGIS**. Si vous
  n'avez **rien** sélectionné, le plugin active la couche + l'outil et affiche un
  bouton **« Récupérer la sélection »** : sélectionnez *ensuite*, puis cliquez-le.
- **Chercher une station…** : un dialogue **liste et filtre** les stations serveur
  du JDD (par habitat, date, observateur) ; **cochez** celles à récupérer.

Elles sont copiées dans votre base locale et deviennent **éditables**.

> Si une station est **déjà** dans votre base locale, le plugin propose de
> **remplacer la copie locale par la version du serveur** (utile pour restaurer).
> Vos modifications locales non synchronisées seraient alors écrasées : lisez bien
> le message.

Ensuite : éditez comme d'habitude (§7), puis **synchronisez** (§9).

### Charger un export du serveur (couche de consultation)

> ⚠️ **La cartographie se fait sur les données de GeoNature, pas sur votre base
> locale.** Un export est une vue du **serveur** : tant qu'une station n'est pas
> **synchronisée**, elle n'y figure pas — donc pas non plus sur les cartes que
> vous en tirerez. La fenêtre de chargement compte vos stations en attente
> **dans le jeu de données courant** et vous le dit ; le même rappel revient à la
> création d'une mise en page. **Synchronisez avant de cartographier** (§9).

> **Le jeu de données ne se choisit pas ici** : c'est celui du panneau, où vous
> travaillez déjà. Le redemander posait une question dont la bonne réponse était
> toujours la même, avec le risque de charger un export qui ne parle pas des
> mêmes stations que votre saisie. Pour en changer, changez-le dans le panneau.
> Une case **« Charger tous les jeux de données »** reste là pour la
> consultation au-delà du vôtre — la couche mélange alors des stations qui ne
> sont pas les vôtres.

**Ce n'est pas dans le même bouton** : cherchez **« Cartographier… ▸ Charger un
export du serveur (couche)… »**, au pied du panneau. Les deux entrées
précédentes rapatrient des stations **éditables** dans votre base ; un export est
une **vue préparée côté GeoNature**
(données consolidées, identifiants déjà traduits en libellés, champs ANA-EVAL
décodés), chargée en **couche QGIS en lecture seule**.

1. L'**export** est celui bâti sur la vue OccHab complète : le plugin ne propose
   pas les autres exports de l'instance (synthèse, taxons, métadonnées…), dont il
   ne saurait ni filtrer ni présenter le contenu.
2. Choisissez le **jeu de données** — celui du panneau est présélectionné.
3. Choisissez la **période**. Par défaut **l'année en cours** (1ᵉʳ janvier →
   31 décembre) ; modifiable, ou décochez **« Restreindre à une période »** pour
   tout rapatrier. Sont retenues les stations dont les dates de début **et** de
   fin tombent dans l'intervalle.

#### Les couleurs de la couche

Elle arrive avec **une couleur par habitat**, chaque teinte restant dans le **ton
de son grand milieu** : les bois en verts, les prairies en verts plus tendres,
les landes en bruns, les tourbières en violets, les eaux en bleus. Une carte se
lit donc à deux niveaux — le milieu d'un coup d'œil, l'habitat précis à la
nuance.

La couleur ne vient d'**aucune liste d'habitats à tenir à jour** : le ton se
déduit du **grand milieu** de l'habitat, et la nuance de sa place parmi ceux
présents. Un habitat jamais rencontré se colore donc tout seul.

Le milieu est cherché **en cascade**, dans l'ordre : code **EUNIS**, puis
**CORINE biotopes**, puis code **Natura 2000** (annexe I ou Cahiers d'habitats).
Peu importe donc la typologie dans laquelle vous saisissez.

> **Cartographie en PVF1 (Prodrome des végétations)** : dans HABREF, le Prodrome
> n'a **qu'une seule** table de correspondance, `PVF1_HIC`, qui mène aux habitats
> d'intérêt communautaire — jamais à EUNIS. Sans la cascade, toute une carto PVF1
> serait restée grise. Elle est désormais colorée d'après les codes Natura 2000,
> et l'infobulle indique la typologie qui a servi (colonne `source_classe`).

Reste en gris — « Habitat non rattaché » — ce qui n'a **aucune** correspondance
dans HABREF, à aucun niveau. Là, ce n'est pas un défaut d'affichage : c'est que
le référentiel ne relie pas ce syntaxon. Les requêtes de diagnostic du README
(§6) permettent de les compter et de les lister.

La légende est **à deux niveaux** : chaque grand milieu forme un groupe repliable
dans le panneau des couches, avec ses habitats dessous.

> Un même habitat garde **la même couleur sur toutes les stations** — la couleur
> suit le `cd_hab`, pas le nom cité, qui peut varier d'une station à l'autre.
> Au-delà de six ou sept habitats dans un même milieu, les nuances se
> rapprochent : c'est la limite d'un ton unique, et c'est précisément pourquoi
> la légende les groupe par milieu.

| Lettre | Milieu | | Lettre | Milieu |
|---|---|---|---|---|
| **G** | Forêts et bois | | **D** | Tourbières et bas-marais |
| **E** | Prairies et pelouses | | **C** | Eaux douces |
| **F** | Landes et fruticées | | **H** | Rochers, éboulis |
| **B** | Côtes, dunes | | **I** | Cultures et jardins |
| **A** | Milieux marins | | **J** | Bâti, artificialisé |

La **légende ne contient que les milieux réellement présents** dans ce que vous
avez chargé : elle se reconstruit à chaque chargement.

#### Les stations en mosaïque

Un polygone peut porter plusieurs habitats. **Aucune convention nationale ne dit
comment les représenter** — le guide méthodologique du MNHN normalise le modèle
de données, pas la sémiologie. La fenêtre de chargement propose donc **deux
représentations**, à comparer sur vos propres données :

| Mode | Ce qu'on voit |
|---|---|
| **Bandes proportionnelles** | le polygone partagé en bandes horizontales, une par habitat, à la surface exacte de son recouvrement |
| **Damier de mailles carrées** | la station quadrillée ; chaque maille revient en entier à un habitat, en nombre proportionnel à son recouvrement |

Dans les deux cas, **chaque habitat occupe la surface de son recouvrement** : un
50 / 30 / 20 se mesure à la règle sur la carte. Les parts sont calculées au
chargement, y compris sur les polygones concaves, où un simple partage de la
hauteur donnerait de fausses surfaces.

> **Ce qui les distingue.** Les bandes se lisent de haut en bas, ce qui suggère
> une stratification que la donnée ne contient pas ; en échange, les surfaces
> sont exactes au millionième. Le damier ne suggère rien sur l'emplacement des
> habitats, mais arrondit à la maille près — environ 1,6 %.

Le mode retenu figure dans le **nom de la couche** : chargez deux fois le même
export avec deux modes différents et comparez-les côte à côte dans le panneau
Couches.

Quel que soit le mode, un contour unique cerne la station, la légende garde une
entrée par habitat, et la composition chiffrée reste en infobulle (**Afficher les
infobulles** dans la barre d'outils) : « Chênaie 50 % ; Lande à callune 30 % ;
Prairie de fauche 20 % ».

> **Aucun de ces modes ne dit OÙ se trouve chaque habitat** dans le polygone :
> ils en donnent la proportion, pas la localisation, que la donnée ne contient
> pas. Ce sont des conventions de lecture, comme un diagramme.
>
> Les **surfaces sont exactes** en mode bandes, quelle que soit la forme du
> polygone : les hauteurs de coupe sont calculées au chargement. Un simple
> partage de la hauteur suffisait sur un rectangle mais donnait 68,8 / 18,8 /
> 12,5 % au lieu de 50 / 30 / 20 sur une forme en L — la partie basse étant plus
> large, une tranche de même hauteur y pèse davantage.

La couche arrive dans un groupe **« OccHab (exports) »**, nommée avec sa période
— deux années peuvent donc coexister pour être comparées. Ce groupe n'est **pas**
reconstruit à chaque rafraîchissement, contrairement à « OccHab (serveur) » :
vos exports restent en place.

> **Rien ne s'affiche, ou trop de choses ?**
> - *« Aucun export disponible »* : le module **Exports** n'est pas installé sur
>   l'instance, ou votre compte n'a pas le droit de lecture dessus.
> - *« Aucun export ne s'appuie sur la vue v_occhab_complet »* : l'export existe
>   peut-être sous un autre nom, mais sur une autre vue. Il se déclare dans
>   l'admin GeoNature — schéma `gn_exports`, vue `v_occhab_complet`, clé primaire
>   `id_ligne`, géométrie `geom`.
> - Un avertissement dit que **vos filtres n'ont peut-être pas été appliqués** :
>   l'API d'export ignore silencieusement un filtre portant sur une colonne
>   absente de la vue. La vue doit exposer `id_dataset`, `date_min` et
>   `date_max` (voir le README, §6).

---

## 9. Synchroniser avec GeoNature

Cliquez **« Synchroniser »** (vous devez être connecté). Le plugin :

1. **applique les suppressions** marquées *À supprimer* (`DELETE` sur GeoNature) ;
2. **envoie les créations et modifications** (les stations *À synchroniser*).

Un **récapitulatif** s'affiche (« X envoyée(s), Y supprimée(s), Z échec(s) »), et
la couche serveur est rechargée.

### « Cette station n'existe plus sur GeoNature »

Si une station que vous aviez déjà synchronisée a été **supprimée sur GeoNature**
entre-temps (par un autre utilisateur, ou après une remise à zéro du serveur), il
n'y a plus rien à mettre à jour. Le plugin le détecte et vous demande :

> « X » n'existe plus sur GeoNature… La recréer comme une nouvelle station ?

- **Oui** → la station est **renvoyée comme une nouvelle saisie** et reçoit un
  **nouvel identifiant** GeoNature. La réponse vaut pour **toute la
  synchronisation** en cours.
- **Non** → rien n'est envoyé ; la station reste **À synchroniser** en local et la
  question sera reposée à la prochaine synchronisation.

Vos données locales ne sont jamais perdues dans un cas comme dans l'autre.

### Garde-fous suppression

Pour éviter les effacements accidentels en masse :

- confirmation listant le **nombre** et les **libellés** des stations à supprimer ;
- au-delà de **3 suppressions**, il faut **taper `SUPPRIMER`** (en majuscules) ;
- seules **vos** données peuvent être supprimées côté serveur (selon vos
  permissions GeoNature).

---

## 10. Supprimer : base locale ou serveur

Le bouton **« Supprimer »** distingue **deux gestes différents** :

- **Station non synchronisée** → **suppression locale immédiate** (après
  confirmation). Elle n'a jamais existé sur GeoNature.
- **Station déjà sur le serveur** → une fenêtre propose :
  - **« Retirer de ma base locale »** : enlève **seulement** la copie locale.
    **GeoNature n'est pas touché** ; vous pourrez la re-récupérer plus tard.
    *Toujours disponible*, y compris pour une station créée par **quelqu'un
    d'autre**.
  - **« Supprimer sur GeoNature »** : marque la station *À supprimer* (réversible
    en re-cliquant), effacée du serveur à la prochaine **synchronisation**.
    *Uniquement pour vos propres données.*

**Plusieurs stations à la fois** : sélectionnez plusieurs lignes dans « Mes
stations » avec **Ctrl** (ajouter/enlever une ligne) ou **Maj** (une plage), puis
**« Supprimer »**. Une fenêtre récapitule la sélection (jamais synchronisées /
déjà sur le serveur / modifications non synchronisées) et propose **« Retirer de
ma base locale »** (toutes) ou **« Supprimer sur GeoNature »** (uniquement vos
stations déjà synchronisées, les autres de la sélection ne sont pas touchées).

**En résumé** : importer la station d'un collègue pour la consulter, puis la
« retirer de ma base locale » n'a **aucun effet** sur GeoNature.

---

## 11. Travailler hors-ligne

Le plugin est **hors-ligne par défaut** : toutes vos saisies sont écrites dans une
base locale (`occhab_local.db`), **connecté ou non**.

- **Sans réseau** : créez et éditez vos stations/habitats
  normalement. Elles restent en état **À synchroniser**.
- **De retour au bureau** : connectez-vous et cliquez **« Synchroniser »**.

Quelques listes (JDD, HABREF, observateurs, nomenclatures) et le calcul
d'altitude nécessitent d'être **connecté**. Hors-ligne, certaines listes peuvent
être vides ; elles seront complétées à la synchronisation (ex. la technique de
collecte est fixée à « In situ » à l'envoi si elle n'a pas pu être renseignée).

---

## 12. Sauvegarde et export des données

Bouton **« Base locale… »** (en bas du dock) :

- **Ouvrir le dossier** — accéder au fichier `occhab_local.db` (pour le copier,
  l'archiver…).
- **Sauvegarder (copie .db)…** — enregistrer une **copie de sauvegarde** de votre
  base locale.
- **Exporter en GeoPackage…** — exporter vos stations dans un **`.gpkg`**
  réutilisable dans QGIS ou un autre outil.
- **Exporter la cartographie du JDD (serveur)…** — produit une **cartographie
  d'habitats** du JDD choisi : le plugin récupère **toutes** les stations du JDD
  sur GeoNature et les écrit en **vue à plat** — **une ligne par habitat**, avec
  les libellés résolus (**nom officiel HABREF** de l'habitat + code + nom cité,
  recouvrement, niveau d'enjeu, état, observateurs, exposition…). Sortie en **GeoPackage** *et* **Shapefile** (une couche / un
  fichier par type de géométrie). Vous devez être **connecté**.
  > Le **Shapefile** tronque les noms de champs à 10 caractères et limite le texte
  > — préférez le **GeoPackage** si le destinataire l'accepte.
- **Nettoyer les stations synchronisées anciennes…** — retire de votre base
  **locale** les stations **déjà synchronisées et non modifiées depuis plus de
  6 mois**, pour garder la liste « Mes stations » courte et rapide. Elles
  **restent sur GeoNature** et sont récupérables via *Récupérer une station du
  serveur*. Les stations **À synchroniser**, **en conflit** ou **à supprimer** ne
  sont **jamais** touchées. Le plugin affiche le nombre concerné et **demande
  confirmation** ; après une synchronisation, un rappel discret apparaît si
  beaucoup de stations anciennes se sont accumulées.

> Pensez à **sauvegarder** régulièrement votre base locale, surtout avant une
> synchronisation importante.

---

## 13. Les champs « enjeu / état / zone humide / recouvrement »

Le module OccHab de GeoNature n'a pas de champ dédié pour le **niveau d'enjeu**,
l'**état de conservation**, le **statut zone humide** et le **recouvrement**. 
Le plugin les enregistre de façon **normalisée**, **encodés dans les champs de 
commentaire** d'OccHab (au niveau station et/ou habitat), sans détruire le texte 
libre que vous y mettez.

- **Niveau d'enjeu** : Très fort / Fort / Moyen / Faible / Aucun / Inconnu (liste
  déroulante, du plus fort au plus faible). Les stations saisies avec l'ancienne
  valeur **« Majeur »** se rouvrent automatiquement sur **« Très fort »** : rien
  n'est perdu.
- **État de conservation** : Inconnu / Excellent / Bon / Moyen / Mauvais (liste
  déroulante). Cette liste suit désormais le **cahier des charges des
  cartographies Natura 2000 d'Occitanie** (annexe 2). L'ancienne valeur « Non
  déterminé » se rouvre automatiquement sur **« Inconnu »** : rien n'est perdu.
- **Zone humide** : **Oui / Non / À vérifier** (liste déroulante). « À vérifier »
  est là pour ce qu'on ne peut pas trancher sur le moment — un bas-fond vu en fin
  d'été, une parcelle interprétée par photo aérienne : la station est marquée
  pour un retour sur le terrain au lieu d'être rangée dans « non » faute de
  mieux. Les stations saisies avec l'ancienne **case à cocher** se rouvrent sur
  **« Oui »** si elle était cochée ; si elle ne l'était pas, la liste reste vide,
  car une case décochée ne voulait pas dire « non ».
- **Recouvrement (%)** : de 0 à 100 (habitat seulement) ; il **pré-sélectionne** 
  aussi la classe d'**abondance** de l'habitat.

Vous les saisissez dans le formulaire de station (les trois premiers l'un sous
l'autre, le recouvrement au niveau habitat) ; à la relecture 
(édition), le plugin les ré-affiche automatiquement. Côté GeoNature, ces valeurs 
restent ré-extractibles (voir README §6 pour les administrateurs).

---

## 13 bis. Brouillon, validé, et la table des stations

### Travailler en brouillon

Une station porte deux états qu'il ne faut pas confondre :

- **Brouillon** ou **Validée** — où en est *votre* travail. Nouvelle station =
  brouillon.
- **À synchroniser / Synchronisée / Conflit** — où en est *l'envoi* vers
  GeoNature.

La colonne **« Statut · synchro »** les montre sur **deux pastilles empilées**, de couleurs distinctes : le statut au-dessus, la synchronisation en dessous.

**Les brouillons sont bien envoyés à GeoNature** : la synchronisation de fin de
journée sert aussi de sauvegarde, pour ne pas perdre une journée de terrain si
l'ordinateur lâche. En contrepartie, ce que voient vos collègues sur GeoNature
peut être du travail en cours — d'où l'intérêt de valider dès que c'est abouti.

Vous changez le statut dans le formulaire de la station (liste **« Statut »**),
ou pour tout un lot depuis la table (**« Marquer comme validées »**).

### La table des stations et habitats

Le bouton **« Tableau »**, au-dessus de la liste, ouvre une fenêtre qui montre
tout le JDD courant : **une ligne par habitat**. Une station qui porte trois
habitats occupe trois lignes ; ses informations de station y sont répétées.

- **La colonne « N° polygone »**, tout à gauche, porte le **numéro de la
  station** — pas celui de la ligne. Trois habitats d'une même mosaïque portent
  donc le **même numéro**, et le fond de la ligne change d'un polygone au
  suivant : les mosaïques se repèrent d'un coup d'œil. L'infobulle du numéro
  précise « habitat 2 sur 3 ». Ce numéro vaut **pour la session** : il se
  renumérote au prochain chargement, ne se modifie pas, et ne part ni en base ni
  vers GeoNature.
- **Colonnes** : choisissez *Essentiel*, *Natura 2000* ou *Tout*.
- **Filtres** : statut, synchro, et une zone de recherche (nom de station,
  habitat, cd_hab). Cliquez un en-tête pour trier.
- **Modifiez directement dans les cellules.** La colonne **« Nom cité »** ouvre
  la **liste HABREF** : double-cliquez, tapez au moins 3 caractères, choisissez
  un habitat — le **cd_hab** de la ligne est renseigné en même temps, même si sa
  colonne n'est pas affichée. La recherche est filtrée par la **dernière
  typologie** que vous avez utilisée. Hors connexion, la cellule redevient un
  champ de texte libre (l'infobulle de l'en-tête vous le rappelle) : pensez alors
  à corriger le cd_hab vous-même.
- **La sélection est partagée avec la carte** : la table s'ouvre sans bloquer
  QGIS, vous pouvez donc sélectionner des polygones à la souris sur la carte pour
  retrouver leurs lignes ici, ou l'inverse. Une station en mosaïque voit **toutes
  ses lignes d'habitats** sélectionnées.
- **Les observateurs** ne se saisissent **pas dans une cellule** (c'est une liste,
  pas une valeur) mais se posent en lot : **« Modifier les lignes
  sélectionnées… »**, champ *Observateurs*, cochez l'équipe. Cocher le champ sans
  retenir personne **efface** les observateurs des stations visées.
- **Corriger une détermination sur tout un lot** : sélectionnez les lignes, puis
  **« Modifier les lignes sélectionnées… »** et servez-vous du champ
  **« Nom cité »**, qui propose la **recherche HABREF** (tapez au moins 3
  caractères ; la ligne **Typologie** juste au-dessus cible la recherche).
  Choisir un habitat coche et remplit à la fois le **nom cité** et le **cd_hab**
  — ils ne peuvent pas être dissociés, sans quoi vous laisseriez des habitats
  dont le code ne correspond plus au nom.
  Vous pouvez **taper directement** dans n'importe quel champ de cette fenêtre :
  la case « modifier » se coche toute seule. Décochez-la pour renoncer à ce
  champ.

> ⚠️ Les colonnes **teintées en gris-bleu** sont des champs de la **station** :
> les modifier sur une ligne les modifie pour **tous les habitats du même
> polygone**. L'infobulle vous le rappelle.

**Copier vers Excel ou LibreOffice** — le bouton **« Copier »**, en haut à
droite, propose trois portées :

| Action | Ce qui part dans le presse-papiers |
|---|---|
| **Copier les lignes sélectionnées** (ou `Ctrl+C`) | les lignes retenues, sans en-têtes |
| **Copier la cellule** | le contenu de la seule cellule où vous êtes, tel quel |
| **Copier tout le tableau (avec en-têtes)** | tout ce qui est **affiché** — donc filtré et trié comme à l'écran — précédé de la ligne d'en-têtes |

Les trois se retrouvent aussi au **clic droit** dans le tableau. Collez ensuite
avec `Ctrl+V` : les colonnes se placent d'elles-mêmes dans le tableur. Un
commentaire à plusieurs lignes reste dans sa cellule et ne décale rien.

> « Copier tout » suit vos filtres : si la recherche ne laisse voir que douze
> lignes, ce sont ces douze-là qui partent, pas les quatre cents du jeu de
> données.

**Modifier plusieurs lignes d'un coup** — sélectionnez les lignes (Ctrl / Maj),
puis **« Modifier les N lignes sélectionnées… »** : le bouton affiche le nombre
de lignes visées, et reste grisé tant que vous n'avez rien sélectionné. Saisissez
les champs à modifier (leur case se coche à la saisie) ; les autres restent tels
quels. Un récapitulatif vous dit
combien de stations et d'habitats sont concernés et, surtout, **combien de
valeurs déjà renseignées seront remplacées**.

**Rien n'est écrit tant que vous n'avez pas cliqué « Enregistrer ».** Les
cellules modifiées apparaissent en orangé. À l'enregistrement, le plugin :

1. vous avertit si un polygone ne totalise pas 100 % de recouvrement (exigence
   Natura 2000) — c'est un avertissement, vous pouvez continuer ;
2. **copie votre base** dans un fichier `…avant-lot-AAAAMMJJ-HHMMSS.db` — c'est
   votre marche arrière en cas de fausse manœuvre ;
3. écrit les modifications et repasse les stations en « À synchroniser ».

Une station **validée** que vous retouchez dans la table **repasse en brouillon**
automatiquement : y revenir, c'est que le travail n'était pas fini.

---

## 13 ter. Sortir une carte : la mise en page

> ⚠️ **Synchronisez avant.** La planche est faite à partir d'une couche d'export,
> donc des données **du serveur**. Vos saisies du jour n'y seront pas tant
> qu'elles ne sont pas parties. Un message jaune vous rappelle combien de
> stations sont encore en attente.

**« Cartographier… ▸ Créer une mise en page… »**, au pied du panneau, compose une planche
cartographique dans QGIS à partir des **gabarits de l'ANA** — ceux du dossier
partagé `composer_templates`. Bandeau vert, logo, adresse et mentions y sont
déjà : vous ne renseignez que ce qui change.

1. **Gabarit** — la liste montre les `.qpt` trouvés. S'ils sont ailleurs,
   cliquez **« Dossier… »** : le chemin est retenu pour les fois suivantes.
   *Carte seule pleine page A4* pour une carte simple, *A3* quand la légende est
   longue, *carte rapport* pour l'insérer dans un document.
2. **Titre** — c'est lui qui s'affiche dans le bandeau vert.
3. **Sous-titre** — jeu de données, année, nom du projet. Laissez vide si vous
   n'en voulez pas : le texte d'exemple du gabarit est effacé de toute façon.
4. **Couche à cartographier** — c'est celle que la **légende** détaille. La carte,
   elle, reprend **toutes les couches allumées à l'écran** : votre ortho reste
   sous les polygones.
5. **Cadrage** — ce que montre l'écran, ou toute la couche.
6. **Fond de plan cité** — BD ORTHO, SCAN25, Cartes IGN. Ce choix alimente la
   ligne « Sources » du gabarit. **Ne citez que ce que vous affichez vraiment.**

La planche s'ouvre dans le composeur de QGIS, **entièrement modifiable** :
déplacez les cadres, changez les polices, exportez en PDF ou en PNG.

> **Si la légende compte trop d'habitats** pour la colonne du gabarit — au-delà
> d'une vingtaine — elle est **placée sur une deuxième page**, en pleine page et
> en colonnes. Rien n'est coupé, et la carte occupe alors toute la page 1. Un
> message vous le dit au moment de la création. Le PDF sort en deux pages : la
> carte, puis sa légende.
>
> La page de légende **reprend l'habillage de la première** — bandeau, titre,
> logo, adresse, sources — pour qu'imprimée seule, on sache de quelle carte elle
> parle. Les **grands types d'habitats y sont en capitales**, pour se distinguer
> des habitats qu'ils regroupent.

> La barre d'échelle et la légende sont rattachées à la carte : elles se mettent
> à jour toutes seules si vous recadrez.

> **Titre court.** Le bandeau vert est d'une hauteur fixe : un titre long passe à
> la ligne et le déborde. Le nom du jeu de données suffit — « Cartographie des
> habitats » tient très bien en sous-titre.

> **Les pavés rouges « WebKit not available »** n'apparaissent plus : votre QGIS
> est construit sans QtWebKit, et le plugin convertit donc les blocs HTML du
> gabarit (adresse, sources, mention du fond) en étiquettes ordinaires. Le
> gabarit lui-même n'est pas modifié.

---

## 14. Dépannage (FAQ)

### « Je ne vois pas l'extension dans le gestionnaire »
Deux causes, dans cet ordre (onglet **Paramètres** du gestionnaire) :

1. **« Afficher aussi les extensions expérimentales »** n'est pas coché — sans
   cette case, l'extension reste invisible, dépôt ajouté ou non.
2. Le **dépôt de l'ANA** n'est pas dans la liste, ou n'est pas *connecté* :
   ajoutez `https://qgisplugins.ariegenature.fr/` (§3, méthode A). Un dépôt en
   erreur se rafraîchit avec **Recharger le dépôt**.

Ne cherchez pas l'extension dans le dépôt officiel QGIS : la version qui s'y
trouve est plus ancienne et cette voie est en attente (§3).

### La connexion échoue (400 / 401)
- Vérifiez l'**URL de l'API** (elle doit finir par `…/geonature/api`).
- Vérifiez vos **identifiants** dans la configuration d'authentification QGIS
  (méthode *Basic*).

### « User … has no permissions to R in OCCHAB » (403)
Vous êtes bien connecté, mais votre compte n'a pas le droit de **lecture** sur
OccHab. Points à vérifier avec votre **administrateur GeoNature** :
- vous appartenez bien au **groupe** qui porte les droits OccHab (et pas à un
  autre) ;
- il n'y a pas de **droit en double** (même droit défini à la fois sur le groupe
  **et** directement sur votre compte) — dans GeoNature, deux permissions
  identiques peuvent s'**annuler** ;
- le droit est **validé** et **non expiré**.
Après un changement de droits, **reconnectez-vous**.

### « Nomenclature TYPE_SOL non trouvée » (404) dans le journal
Ce n'est **pas une erreur** : votre instance GeoNature ne fournit pas cette liste.
Le champ correspondant (« Type de sol ») est simplement **masqué**. Rien à faire.

### « Pas de couche vectorielle active » / la numérisation ne démarre pas
Utilisez **« ＋ Nouvelle station ▾ → Dessiner un polygone / un point »** : le
plugin prépare lui-même la couche de dessin. Ne créez pas de couche à la main.

### Les stations serveur ne s'affichent pas
- Vous devez être **connecté** et avoir choisi un **JDD précis** (pas « Tous les
  JDD »).
- Vérifiez le **compteur « Serveur : N station(s) »**. S'il indique 0, il n'y a pas
  de station pour ce JDD (ou vos permissions ne vous en montrent aucune).

### J'ai modifié une géométrie côté serveur mais je ne la vois pas mise à jour
Après **Synchroniser**, la couche serveur est rechargée. Sinon, cliquez
**« Rafraîchir »**.

### J'ai perdu ma base locale
Reconnectez-vous, sélectionnez vos stations dans la couche serveur et
**« Récupérer du serveur »** (voir §8) : elles sont restaurées en local.

---

## 15. Glossaire

- **Station** : objet géographique (point, ligne, polygone) décrivant un lieu
  d'observation. Porte 1 à N habitats.
- **Habitat** : description d'un milieu au sein d'une station (non géographique),
  identifié par un **`cd_hab`** HABREF.
- **JDD (jeu de données)** : cadre GeoNature auquel se rattachent les stations
  (obligatoire).
- **HABREF** : référentiel national des habitats (typologies Corine Biotopes,
  EUNIS, etc.). Le plugin y recherche le `cd_hab` à partir du nom.
- **`cd_hab`** : code d'un habitat dans HABREF.
- **Nomenclature** : liste de valeurs standardisées GeoNature/SINP (technique de
  collecte, abondance, exposition…).
- **CRUVED** : les 6 droits GeoNature — **C**réer, **R**ead (lire), **U**pdate
  (modifier), **V**alider, **E**xporter, **D**elete (supprimer).
- **Synchroniser** : envoyer vos saisies locales vers GeoNature.
- **Hors-ligne (offline-first)** : tout est d'abord stocké localement, puis
  envoyé au serveur à la demande.
- **id_digitiser** : identifiant de l'utilisateur qui a **numérisé** (créé) une
  station ; sert à savoir ce qui est « à vous ».

---

*Extension développée par l'ANA-CEN Ariège — contact : it@ariegenature.fr.
Licence GPL-3.0-or-later. Pour les aspects techniques, voir le [README](README.md).*
