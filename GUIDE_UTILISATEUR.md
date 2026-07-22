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
13. [Les champs « enjeu / état / recouvrement »](#13-les-champs-enjeu--état--recouvrement)
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
  **recouvrement** ;
- **synchroniser** vos saisies avec GeoNature (création, modification,
  suppression) ;
- **consulter** les stations déjà présentes sur le serveur pour vous repérer et
  éviter les doublons.

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

### Méthode A — depuis le dépôt d'extensions QGIS (recommandée)

L'installation la plus simple, avec **mises à jour automatiques** proposées par
QGIS :

1. Dans QGIS : menu **Extensions ▸ Installer/Gérer les extensions**.
2. Comme l'extension est marquée « expérimentale », ouvrez d'abord l'onglet
   **Paramètres** et cochez **« Afficher aussi les extensions expérimentales »**.
3. Onglet **Toutes**, tapez **`OccHab GeoNature`** dans la recherche.
4. Sélectionnez-la et cliquez **Installer l'extension**.
5. Onglet **Installées** : vérifiez qu'elle est **cochée**.

> Quand une nouvelle version est publiée, QGIS vous propose la **mise à jour**
> automatiquement (onglet *Mises à jour*).

### Méthode B — depuis un fichier ZIP

Utile hors ligne, en avant-première, ou si le dépôt QGIS n'est pas accessible :

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
│ [✏ Éditer] [⬡ Géométrie ▾] [🔍 Zoom]         [🗑 Supprimer]│
│  ┌────────────────────┬───────────┬─────────────────┐     │
│  │ Habitat(s)         │ Date      │ État            │     │
│  │ 41.711 — Bois de…  │ 2024-06-21│ ✓ Synchronisée  │     │
│  └────────────────────┴───────────┴─────────────────┘     │
│  [＋ Nouvelle station ▾]                                  │
│─────────────────────────────────────────────────────────│
│ Serveur                                                   │
│  [Synchroniser (2)]  [Rafraîchir]                         │
│  [Récupérer une station du serveur… ▾]                    │
│─────────────────────────────────────────────────────────│
│ Base locale : occhab_local.db          [Base locale…]     │
└─────────────────────────────────────────────────────────┘
```

- **Barre connexion + JDD** (repliable) : cliquez **« changer »** pour la déplier
  (se connecter, choisir le JDD, filtre « mes stations serveur ») ; elle se replie
  une fois le JDD choisi. La combo JDD est **cherchable** (tapez pour filtrer).
- **Mes stations** : le tableau de **vos** saisies. La **barre d'action
  au-dessus** agit sur la **ligne sélectionnée** (grisée sans sélection) :
  *Éditer*, *Géométrie ▾*, *Zoom*, *Supprimer* (isolé, destructif). Les mêmes
  actions sont accessibles par **clic-droit** sur une ligne, et **double-clic**
  ouvre la station. **« ＋ Nouvelle station ▾ »** la crée (voir §6).
- **Serveur** : *Synchroniser*, *Rafraîchir*, *Récupérer une station du serveur…*.
- **Astuce carte** : double-cliquer une station sur la carte (ou cliquer dessus
  avec l'outil **Identifier des entités**) ouvre son formulaire.

### Les couches sur la carte

- **OccHab (local)** : vos stations, **colorées selon leur état** :
  - *À synchroniser* (pas encore envoyées ou modifiées),
  - *Synchronisée* (à jour sur GeoNature),
  - *Conflit* (modifiée aussi côté serveur — à résoudre),
  - *À supprimer* (marquée pour effacement),
- **OccHab (serveur)** : les stations déjà sur GeoNature pour le JDD choisi, en
  **bleu** et en **lecture seule** (contexte, non modifiable directement).

### La colonne « État »

| État affiché       | Signification                                              |
|--------------------|------------------------------------------------------------|
| **À synchroniser** | Créée ou modifiée localement, pas encore envoyée à GeoNature |
| **Synchronisée**   | Identique à la version GeoNature                           |
| **Conflit**        | Modifiée **aussi** sur GeoNature depuis votre dernière synchro — à résoudre |
| **À supprimer**    | Marquée pour suppression au prochain envoi (réversible)    |

---

## 6. Saisir une station et ses habitats

### Étape 1 — Créer la station et sa géométrie

Cliquez **« ＋ Nouvelle station ▾ »** et choisissez d'où vient la géométrie :

- **Dessiner un polygone** / **Dessiner un point** — dessinez sur la carte : clic
  gauche pour poser les sommets (l'**accrochage** QGIS est actif, pratique pour se
  caler sur des objets existants), **clic droit** pour terminer.
- **Copier l'entité sélectionnée (autre couche)** — sélectionnez d'abord une entité
  dans une **autre couche** (parcellaire, ancien relevé, trace GPS…), puis
  choisissez ceci : sa forme est reprise (et reprojetée) pour la station.
- **Sans géométrie (à tracer plus tard)** — ouvre directement le formulaire ; vous
  ajouterez la géométrie ensuite via **« Géométrie ▾ »**.

Le formulaire de la station s'ouvre. Pour un **polygone**, la **surface** (m²) et
l'**altitude min/max** sont déjà remplies automatiquement.

### Étape 2 — Renseigner la station

Le formulaire est à **deux niveaux**. L'**Essentiel** est toujours visible :

- **Jeu de données (JDD)** — *obligatoire*.
- **Nom de la station**, **dates** (début / fin).
- **Observateur(s)** — champ à **autocomplétion** : déroulez pour parcourir la
  liste, ou **tapez** un nom pour filtrer ; l'observateur choisi s'ajoute dessous
  (retirable par double-clic ou « Retirer »). L'utilisateur connecté est
  pré-ajouté.
- **Niveau d'enjeu** / **état de conservation** (voir §13), **Commentaire**.

Les autres champs (**altitude**, **profondeur**, **surface**, **exposition**,
**type de sol**, **type de mosaïque**, **nature d'objet géographique**) sont sous
**« ▸ Détails »** — cliquez pour déplier. En **édition**, cette section se déplie
d'elle-même si ces champs sont déjà renseignés.

> Certains champs (type de sol, mosaïque…) ne s'affichent que si votre instance
> GeoNature les propose. **Surface** et **altitude** sont calculées automatiquement.

### Étape 3 — Ajouter un ou plusieurs habitats

Dans le formulaire, ajoutez au moins un habitat :

- **Nom cité** — commencez à taper le nom (ou le code) de l'habitat : une
  **liste HABREF** apparaît, préfixée par la typologie (« CORINE biotopes 41.2 -
  Chênaies-charmaies »). En choisissant une proposition, le **code `cd_hab`** est
  rempli automatiquement. Le nom cité reste ensuite librement modifiable.
- **Filtre typologie** — pour cibler la recherche (Corine, EUNIS…).
- **Déterminateur** — utilisateur connecté par défaut, saisie libre possible.
- **Technique de collecte** — **« In situ » par défaut**.
- **Recouvrement (%)** — pré-sélectionne automatiquement la classe d'**abondance**.
- **Sensibilité** — **« Non sensible » par défaut**.
- **Type de détermination**, **abondance**, **intérêt communautaire**.
- **Niveau d'enjeu** / **état de conservation** de l'habitat (voir §13).

Répétez pour chaque habitat. La **liste des habitats** de la station affiche, pour
chacun, son **% de recouvrement**. Un garde-fou demande confirmation avant de
**retirer** un habitat.

### Étape 4 — Enregistrer

Validez le formulaire : la station apparaît dans le tableau **« Mes stations
(local) »**, identifiée par son premier habitat (ex. « 41.2 - Chênaies-charmaies
(+2) » = 3 habitats), en état **À synchroniser**.

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
    géométrie (re-cliquez pour **refaire** — c'est un échange).

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

---

## 9. Synchroniser avec GeoNature

Cliquez **« Synchroniser »** (vous devez être connecté). Le plugin :

1. **applique les suppressions** marquées *À supprimer* (`DELETE` sur GeoNature) ;
2. **envoie les créations et modifications** (les stations *À synchroniser*).

Un **récapitulatif** s'affiche (« X envoyée(s), Y supprimée(s), Z échec(s) »), et
la couche serveur est rechargée.

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
  les libellés résolus (habitat, recouvrement, niveau d'enjeu, état, observateurs,
  exposition…). Sortie en **GeoPackage** *et* **Shapefile** (une couche / un
  fichier par type de géométrie). Vous devez être **connecté**.
  > Le **Shapefile** tronque les noms de champs à 10 caractères et limite le texte
  > — préférez le **GeoPackage** si le destinataire l'accepte.

> Pensez à **sauvegarder** régulièrement votre base locale, surtout avant une
> synchronisation importante.

---

## 13. Les champs « enjeu / état / recouvrement »

Le module OccHab de GeoNature n'a pas de champ dédié pour le **niveau d'enjeu**,
l'**état de conservation** et le **recouvrement**. Le plugin les enregistre de
façon **normalisée**, **encodés dans les champs de commentaire** d'OccHab (au
niveau station et/ou habitat), sans détruire le texte libre que vous y mettez.

- **Niveau d'enjeu** : Faible / Moyen / Fort / Majeur.
- **État de conservation** : Bon / Moyen (altéré) / Mauvais (dégradé) / Non
  déterminé.
- **Recouvrement (%)** : de 0 à 100 ; il **pré-sélectionne** aussi la classe
  d'**abondance** de l'habitat.

Vous les saisissez via des listes déroulantes ; à la relecture (édition), le
plugin les ré-affiche automatiquement. Côté GeoNature, ces valeurs restent
ré-extractibles (voir README §6 pour les administrateurs).

---

## 14. Dépannage (FAQ)

### « Je ne vois pas l'extension dans le gestionnaire »
Cochez **« Afficher aussi les extensions expérimentales »** dans les paramètres du
gestionnaire d'extensions.

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
