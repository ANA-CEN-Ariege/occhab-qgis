#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalogue des végétations de l'Ariège (0_Typologie.xlsx) → dictionnaire de
correspondances exploitable par le plugin.

Le catalogue est tenu par les botanistes dans un tableur : une ligne par
**alliance**, avec ses correspondances CORINE, EUNIS et Natura 2000. Le plugin,
lui, ne manipule que des `cd_hab` HABREF. Ce script fait le pont, une fois, hors
QGIS — et **n'écrit jamais dans le fichier source**.

Il produit deux fichiers :

- `dictionnaire_typologie.csv` — le dictionnaire proprement dit, une ligne par
  alliance, avec les `cd_hab` résolus ;
- `anomalies_typologie.csv` — tout ce qui n'a pas résolu, avec sa gravité. Ce
  second fichier n'est pas un sous-produit : c'est la **liste de travail des
  botanistes**, et le seul garde-fou contre un import qui aurait l'air complet
  sans l'être.

Trois règles portent l'essentiel de la logique métier :

1. **Ancrage.** 43 alliances du catalogue sont absentes de HABREF — le catalogue
   diverge délibérément du Prodrome (cf. la légende du fichier, « différences
   d'interprétation entre Gilles Corriol et le PVF II »). Leur détermination ne
   peut donc pas tenir dans `cd_hab`. On y met alors le code CORINE de la ligne
   (à défaut EUNIS) comme **ancre**, et le nom d'alliance part en `nom_cite` :
   c'est l'usage prévu d'OccHab, où le code ancre la donnée dans un référentiel
   national et le nom porte la détermination réelle.
2. **Routage Natura 2000.** La colonne « Natura 2000 » mélange deux typologies
   HABREF : les habitats d'intérêt communautaire (`6510`) et leur déclinaison en
   Cahiers d'habitats (`6510-1`). Un code suffixé part vers les Cahiers.
3. **Tirets.** Le tableur écrit `Achilleo ptarmicae – Cirsion palustris` (tiret
   long), HABREF `Achilleo ptarmicae - Cirsion palustris`. Sans normalisation,
   une recherche sur quinze noms échoue en bloc — soit dix-huit points de
   résolution perdus.

Ce que le script **ne fait pas** : il ignore les enjeux, le statut ZNIEFF et la
liste rouge (hors périmètre, l'enjeu relève de l'expertise de terrain station par
station), et il ne lit pas les **couleurs** des cellules. Or elles portent du
sens dans le fichier source — a minima « divergence avec le PVF II » et
« présence incertaine en Ariège ». Tant qu'elles ne sont pas passées en colonnes
explicites, cette information reste dans le tableur et n'arrive pas au plugin ;
le script le rappelle à chaque exécution.

Usage :
    python3 scripts/import_typologie.py CHEMIN/0_Typologie.xlsx \\
        --api https://geonature.ariegenature.fr/geonature/api \\
        --sortie ./dictionnaire

Les résolutions HABREF sont mises en cache sur disque (`--cache`) : une seconde
exécution ne réinterroge pas le serveur, et le résultat est reproductible.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

# Le découpage du `search_name` de HABREF est déjà écrit — et testé — dans le
# module pur du plugin. Le redéfinir ici ferait diverger le libellé du
# dictionnaire importé de celui affiché à la saisie. Le module ne dépend que de
# la bibliothèque standard, il s'importe donc depuis un script autonome.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "processing"))
from correspondances import nom_habref  # noqa: E402

#: Classeur des botanistes, versionné DANS le dépôt. Il vivait dans un dossier
#: de téléchargement : un document qui fait autorité — 227 alliances et leurs
#: correspondances — n'a rien à faire là où les fichiers arrivent en double et
#: se vident. Ici, chaque modification se relit en `git diff`, et le dictionnaire
#: livré ne peut plus diverger de sa source.
CATALOGUE_SOURCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resources", "typologie", "0_Typologie.xlsx")

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

#: Colonnes de la feuille « Classif », par lettre. Le fichier a des en-têtes
#: fautifs (« Descripiton simplifiée », « Libellé EunisRhynchospora alba ») :
#: s'y fier casserait au premier nettoyage du tableur. On lit donc par lettre, et
#: on VÉRIFIE les en-têtes au démarrage (`verifier_entetes`) pour échouer
#: bruyamment si une colonne a été insérée, plutôt qu'importer de travers.
COL = {
    "classe": "D", "ordre": "F", "alliance": "H", "auteurs": "I",
    "corine": "L", "eunis": "N", "n2000": "P",
}
LIGNE_ENTETE = 2  # la ligne 1 porte la légende des couleurs, pas les en-têtes

#: cd_typo HABREF des typologies utilisées (constants, HABREF étant national).
CD_TYPO = {
    "PVF1": 18,
    "PVF2": 28,
    "CORINE_biotopes": 22,
    "EUNIS": 7,
    "Habitats_d'intérêt_communautaire": 8,
    "Cahiers_d'habitats": 4,
}
#: Typologies interrogées, dans l'ordre, pour retrouver une alliance.
TYPOS_ALLIANCE = ("PVF1", "PVF2")

#: Motif du code de chaque typologie, appliqué en TÊTE de cellule. Ce qui suit
#: est du texte non codifiable (« pp », « uniquement si… »), conservé à part.
MOTIF_CODE = {
    "corine": re.compile(r"\d+(?:\.\d+)*[A-Za-z]?"),
    # EUNIS emploie des LETTRES aux niveaux profonds : « C3.24A », « G1.A41 »,
    # « D2.2C11 », « E1.262J ». Un motif qui n'admet que des chiffres après le
    # point tronquait quatorze codes du catalogue — « G1.A41 » devenait « G1 »,
    # soit cinq niveaux au-dessus : une correspondance fausse, résoluble, donc
    # invisible. C'est exactement ce que le fichier d'anomalies doit empêcher.
    "eunis": re.compile(r"[A-Z]\d*(?:\.[0-9A-Z]+)*"),
    "n2000": re.compile(r"\d{4}(?:-\d+)?"),
}
#: Cellule vide au sens du catalogue (pas de correspondance connue).
VIDES = {"", "/", "-", "?"}


# =============================================================== outils purs
def normaliser(texte):
    """Forme comparable d'un nom : sans accent, sans casse, tirets unifiés.

    Les tirets (court, long, cadratin) deviennent des espaces : le tableur et
    HABREF n'écrivent pas les noms composés de la même façon, et c'est la
    première cause d'échec de résolution.
    """
    texte = unicodedata.normalize("NFD", texte or "")
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = re.sub(r"[‐-―\-]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip().lower()


def nom_alliance(brut):
    """Nom latin seul, sans ce que le botaniste a ajouté autour.

    La cellule porte parfois un commentaire (`Charion fragilis (! Nommé …)`), un
    synonyme (`… = Junipero …`) ou une variante (`… ; Vaccinio …`). Tout ce qui
    suit `(`, `=` ou `;` est de la glose : le nom s'arrête avant.
    """
    return re.sub(r"\s+", " ", re.split(r"\s*[(;=]", brut or "")[0]).strip()


def mot_sonde(nom):
    """Mot à envoyer à HABREF pour retrouver `nom`.

    L'autocomplétion HABREF filtre sur la chaîne entière : lui donner le nom
    composé complet échoue dès que les tirets diffèrent. On lui envoie donc un
    seul mot — l'épithète en `-ion`, qui désigne l'alliance et discrimine bien —
    puis on compare les résultats nous-mêmes.
    """
    mots = [m for m in normaliser(nom).split() if len(m) > 4]
    for mot in mots:
        if mot.endswith("ion"):
            return mot
    return max(mots, key=len) if mots else normaliser(nom)


def extraire_codes(cellule, typologie):
    """(codes, texte non codifié) d'une cellule de correspondance.

    Une cellule vaut plusieurs codes séparés par `;` (`C1.25 ; C1.141`), et peut
    porter une condition que rien ne code (`6430 (pp si habitat linéaire)`). La
    condition n'est pas jetée : elle remonte en anomalie et suit dans le
    dictionnaire, car c'est elle qui décide si le code s'applique.
    """
    valeur = (cellule or "").strip()
    if valeur in VIDES:
        return [], ""
    codes, reste = [], []
    for morceau in valeur.split(";"):
        morceau = morceau.strip()
        if not morceau:
            continue
        trouve = MOTIF_CODE[typologie].match(morceau)
        suite = morceau[trouve.end():].strip(" .") if trouve else ""
        # Un code EUNIS suivi d'une LETTRE n'est pas un code : c'est de la prose
        # (« Aucune correspondance » → « A » + « ucune… ») ou un code qu'on ne
        # sait pas lire (« E1.26a »). Le contrôle se fait APRÈS coup et non par
        # une sentinelle dans le motif : `(?![A-Za-z])` ferait rétro-agir le
        # moteur dans les chiffres et rendrait « E1.2 » pour « E1.26a » — une
        # correspondance fausse, résoluble, donc invisible. Mieux vaut la
        # signaler en anomalie que la deviner.
        colle = trouve is not None and morceau[trouve.end():trouve.end() + 1].isalpha()
        # Et une lettre SEULE suivie de texte (« A définir ») : la lettre est un
        # vrai niveau 1 EUNIS, mais jamais accompagnée d'un commentaire.
        seule = trouve is not None and len(trouve.group(0)) == 1 and bool(suite)
        prose = trouve is not None and typologie == "eunis" and (colle or seule)
        if trouve is not None and not prose:
            codes.append(trouve.group(0))
            if suite:
                reste.append(suite)
        else:
            reste.append(morceau)
    return codes, " ; ".join(reste)


def typologie_n2000(code):
    """Typologie HABREF d'un code de la colonne « Natura 2000 ».

    `6510` est un habitat d'intérêt communautaire ; `6510-1` sa déclinaison en
    Cahiers d'habitats. Le tableur met les deux dans la même colonne, HABREF les
    range dans deux typologies distinctes.
    """
    return "Cahiers_d'habitats" if "-" in code else "Habitats_d'intérêt_communautaire"


def est_ligne_catalogue(cellules):
    """La ligne décrit-elle une alliance du catalogue ?

    Le bas de la feuille sert de brouillon : la colonne « Classe » y contient des
    codes CORINE et la colonne « Alliance » des noms de taxons. Un nom de classe
    phytosociologique est latin et ne contient aucun chiffre — c'est le
    discriminant le plus sûr, et il ne dépend pas d'un numéro de ligne qui
    bougera au prochain ajout.

    Une classe **vide** ne disqualifie pas la ligne : trois alliances bien
    réelles (`Arabidion soyeri`, `Saxifrago rotundifoliae – Violion biflorae`,
    `Selino pyrenaei – Nardetum strictae`) n'ont pas leur classe recopiée. Les
    exiger revenait à perdre en silence des déterminations valides — le défaut
    exact que ce script est censé rendre impossible.
    """
    if not (cellules.get(COL["alliance"]) or "").strip():
        return False
    classe = (cellules.get(COL["classe"]) or "").strip()
    return not any(c.isdigit() for c in classe)


def choisir_ancre(codes_corine, codes_eunis):
    """Code servant de `cd_hab` quand l'alliance est absente de HABREF.

    CORINE d'abord : 42 des 43 alliances concernées en ont un, et il est
    généralement plus fin qu'EUNIS sur la végétation. EUNIS en repli. `None`
    quand la ligne n'offre ni l'un ni l'autre — cas bloquant, à compléter dans le
    tableur.
    """
    if codes_corine:
        return "CORINE_biotopes", codes_corine[0]
    if codes_eunis:
        return "EUNIS", codes_eunis[0]
    return None


# ============================================================ lecture du xlsx
def _valeur(cellule, chaines):
    valeur = cellule.find(NS + "v")
    inline = cellule.find(NS + "is")
    if cellule.get("t") == "s" and valeur is not None:
        return chaines[int(valeur.text)]
    if inline is not None:
        return "".join(t.text or "" for t in inline.iter(NS + "t"))
    return valeur.text if valeur is not None else None


def lire_feuille(chemin, nom_feuille="Classif"):
    """[(numéro de ligne, {lettre: valeur})] — sans dépendance externe."""
    with zipfile.ZipFile(chemin) as archive:
        chaines = [
            "".join(t.text or "" for t in si.iter(NS + "t"))
            for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))
        ]
        classeur = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        cibles = {
            r.get("Id"): r.get("Target")
            for r in rels
        }
        cible = None
        for feuille in classeur.iter(NS + "sheet"):
            if (feuille.get("name") or "").strip().lower() == nom_feuille.lower():
                rid = [v for k, v in feuille.attrib.items() if k.endswith("}id")]
                cible = cibles.get(rid[0]) if rid else None
        if cible is None:
            raise SystemExit("Feuille « %s » introuvable dans %s" % (nom_feuille, chemin))
        chemin_interne = "xl/" + cible.lstrip("/")
        racine = ET.fromstring(archive.read(chemin_interne))

    lignes = []
    for ligne in racine.iter(NS + "row"):
        cellules = {}
        for cellule in ligne.iter(NS + "c"):
            lettre = "".join(c for c in cellule.get("r") if c.isalpha())
            valeur = _valeur(cellule, chaines)
            if valeur not in (None, ""):
                cellules[lettre] = valeur.strip()
        lignes.append((int(ligne.get("r")), cellules))
    return lignes


def lire_complement(chemin):
    """{numéro de ligne: {colonne: valeur}} — corrections hors tableur.

    Le tableur fait autorité, mais il n'est pas toujours à portée de main : une
    correction décidée en réunion doit pouvoir servir le jour même. Ce fichier
    l'accueille **provisoirement** — chaque valeur appliquée ressort en anomalie
    « à reporter dans le tableur », pour qu'un correctif de circonstance ne
    devienne pas une seconde source de vérité.

    Colonnes attendues : `ligne_xlsx`, et l'une au moins de `corine`, `eunis`,
    `n2000`.
    """
    if not chemin:
        return {}
    complements = {}
    with open(chemin, encoding="utf-8-sig", newline="") as fichier:
        for ligne in csv.DictReader(fichier, delimiter=";"):
            numero = (ligne.get("ligne_xlsx") or "").strip()
            if not numero.isdigit():
                continue
            valeurs = {
                cle: (ligne.get(cle) or "").strip()
                for cle in ("corine", "eunis", "n2000")
                if (ligne.get(cle) or "").strip()
            }
            if valeurs:
                complements[int(numero)] = valeurs
    return complements


def verifier_entetes(lignes):
    """Échouer si les colonnes ont bougé, plutôt qu'importer de travers."""
    entetes = dict(lignes).get(LIGNE_ENTETE, {})
    attendu = {
        COL["classe"]: "classe", COL["alliance"]: "alliance",
        COL["corine"]: "corine", COL["eunis"]: "eunis", COL["n2000"]: "natura",
    }
    ecarts = [
        "colonne %s : « %s » (attendu : un intitulé contenant « %s »)"
        % (lettre, entetes.get(lettre, "(vide)"), mot)
        for lettre, mot in attendu.items()
        if mot not in normaliser(entetes.get(lettre, ""))
    ]
    if ecarts:
        raise SystemExit(
            "Les colonnes de la feuille Classif ne sont pas celles attendues :\n  "
            + "\n  ".join(ecarts)
            + "\nAdaptez COL dans ce script avant de relancer."
        )


# ================================================================== HABREF
class Habref:
    """Résolution des noms et des codes en `cd_hab`, avec cache sur disque."""

    def __init__(self, api_url, cache=None, verbose=True):
        import requests  # importé ici : le reste du script n'en dépend pas

        self.url = api_url.rstrip("/") + "/habref/habitats/autocomplete"
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self._requests = requests
        self.chemin_cache = cache
        self.verbose = verbose
        self.cache = {}
        if cache and os.path.exists(cache):
            with open(cache, encoding="utf8") as fichier:
                self.cache = json.load(fichier)

    def enregistrer_cache(self):
        if not self.chemin_cache:
            return
        with open(self.chemin_cache, "w", encoding="utf8") as fichier:
            json.dump(self.cache, fichier, ensure_ascii=False)

    def _interroger(self, recherche, cd_typo):
        cle = "%s|%s" % (cd_typo, recherche)
        if cle in self.cache:
            return self.cache[cle]
        for essai in range(3):
            try:
                reponse = self.session.get(
                    self.url,
                    params={"search_name": recherche, "cd_typo": cd_typo, "limit": 100},
                    timeout=30,
                )
                if reponse.status_code == 200:
                    # `.json()` lève sur une page HTML (portail captif, erreur de
                    # reverse-proxy) : sans ce garde, l'exception traverserait la
                    # boucle de reprise et interromprait tout l'import.
                    try:
                        resultat = reponse.json() if reponse.text else []
                    except ValueError:
                        resultat = None
                    # Un 200 qui ne rend pas une liste (page d'erreur, objet
                    # d'erreur) n'est PAS un « aucun résultat » : le mettre en
                    # cache figerait pour toujours une panne passagère en
                    # « absent de HABREF », indiscernable d'une vraie absence.
                    if isinstance(resultat, list):
                        self.cache[cle] = resultat
                        return resultat
            except self._requests.RequestException:
                pass
            time.sleep(1 + essai)
        raise SystemExit(
            "HABREF ne répond pas (%s). Relancez : le cache conserve l'acquis." % self.url
        )

    def par_nom(self, nom):
        """(typologie, entrée) de l'alliade portant exactement ce nom, ou (None, None)."""
        cible = normaliser(nom)
        for typologie in TYPOS_ALLIANCE:
            for entree in self._interroger(mot_sonde(nom), CD_TYPO[typologie]):
                candidat = normaliser(
                    (entree.get("search_name") or "").split(" - ", 1)[-1]
                )
                if candidat == cible or candidat.startswith(cible + " "):
                    return typologie, entree
        return None, None

    def par_code(self, code, typologie):
        """Entrée dont le `lb_code` vaut exactement `code`, ou None."""
        exactes = [
            entree for entree in self._interroger(code, CD_TYPO[typologie])
            if (entree.get("lb_code") or "").strip() == code
        ]
        return exactes[0] if len(exactes) == 1 else None


# ================================================================= traitement
CHAMPS_DICO = [
    "ligne_xlsx", "classe", "alliance", "alliance_brut", "auteurs",
    "cd_hab", "typologie", "code_habref", "nom_habref",
    "ancre_cd_hab", "ancre_typologie", "ancre_code",
    # Le LIBELLÉ de chaque correspondance, et pas seulement son code : un
    # botaniste qui a déterminé une alliance ne connaît pas forcément le code
    # CORINE ou EUNIS correspondant. Lui proposer « 41.112 » tout seul ne l'aide
    # pas à choisir ; « 41.112 — Hêtraies acidiphiles » si.
    "corine_cd_hab", "corine_code", "corine_nom", "corine_autres",
    "eunis_cd_hab", "eunis_code", "eunis_nom", "eunis_autres",
    "n2000_cd_hab", "n2000_code", "n2000_nom",
    "cahiers_cd_hab", "cahiers_code", "cahiers_nom",
    "condition_n2000",
]
CHAMPS_ANOMALIES = ["ligne_xlsx", "alliance", "gravite", "type", "detail"]


def _resoudre_codes(habref, cellule, typologie_cellule, anomalies, ligne, alliance):
    """([(code, typologie, entrée HABREF ou None)], texte non codifié).

    Le texte non codifié est RENDU plutôt que recalculé par l'appelant : deux
    analyses de la même cellule finiraient par diverger, et l'une d'elles décide
    si un code Natura 2000 s'applique.
    """
    codes, reste = extraire_codes(cellule, typologie_cellule)
    if reste:
        anomalies.append({
            "ligne_xlsx": ligne, "alliance": alliance, "gravite": "avertissement",
            "type": "texte_non_codifie",
            "detail": "%s : « %s » (cellule : « %s »)" % (
                typologie_cellule.upper(), reste, cellule),
        })
    resolus = []
    for code in codes:
        cible = (typologie_n2000(code) if typologie_cellule == "n2000"
                 else {"corine": "CORINE_biotopes", "eunis": "EUNIS"}[typologie_cellule])
        entree = habref.par_code(code, cible)
        if entree is None:
            anomalies.append({
                "ligne_xlsx": ligne, "alliance": alliance, "gravite": "avertissement",
                "type": "code_absent_habref",
                "detail": "%s « %s » introuvable dans la typologie %s" % (
                    typologie_cellule.upper(), code, cible),
            })
        resolus.append((code, cible, entree))
    return resolus, reste


def _premier(resolus, typologies=None):
    """(code, cd_hab, libellé, autres codes) du premier code résolu.

    Le libellé vient de HABREF et non du tableur : il décrit exactement le
    `cd_hab` retenu, là où la colonne du tableur porte parfois le libellé d'une
    cellule qui contenait deux codes.
    """
    retenus = [
        (code, typo, entree) for code, typo, entree in resolus
        if entree is not None and (typologies is None or typo in typologies)
    ]
    if not retenus:
        return "", "", "", ""
    code, _typo, entree = retenus[0]
    autres = "|".join(c for c, _t, _e in retenus[1:])
    return code, entree.get("cd_hab"), nom_habref(entree.get("search_name")), autres


def construire(chemin_xlsx, habref, complements=None, journal=print):
    """(lignes du dictionnaire, anomalies) — le cœur du script."""
    lignes = lire_feuille(chemin_xlsx)
    verifier_entetes(lignes)
    complements = complements or {}

    dico, anomalies, appliques = [], [], set()
    for numero, cellules in lignes:
        if numero <= LIGNE_ENTETE:
            continue
        brut = (cellules.get(COL["alliance"]) or "").strip()
        if not brut:
            continue  # ligne de séparation entre deux classes
        if not est_ligne_catalogue(cellules):
            anomalies.append({
                "ligne_xlsx": numero, "alliance": brut, "gravite": "information",
                "type": "hors_catalogue",
                "detail": "colonne Classe = « %s » : ligne de brouillon, ignorée"
                          % (cellules.get(COL["classe"]) or ""),
            })
            continue

        alliance = nom_alliance(brut)
        appliques.add(numero)
        for colonne, valeur in complements.get(numero, {}).items():
            anomalies.append({
                "ligne_xlsx": numero, "alliance": alliance, "gravite": "avertissement",
                "type": "complement_applique",
                "detail": "%s = « %s » vient du fichier de complément (le tableur "
                          "porte « %s ») : à reporter dans le tableur"
                          % (colonne.upper(), valeur,
                             cellules.get(COL[colonne]) or ""),
            })
            cellules[COL[colonne]] = valeur
        corine, _ = _resoudre_codes(habref, cellules.get(COL["corine"]), "corine",
                                    anomalies, numero, alliance)
        eunis, _ = _resoudre_codes(habref, cellules.get(COL["eunis"]), "eunis",
                                   anomalies, numero, alliance)
        n2000, condition = _resoudre_codes(habref, cellules.get(COL["n2000"]), "n2000",
                                           anomalies, numero, alliance)

        ligne = dict.fromkeys(CHAMPS_DICO, "")
        ligne.update({
            "ligne_xlsx": numero, "alliance": alliance, "alliance_brut": brut,
            "classe": cellules.get(COL["classe"], ""),
            "auteurs": cellules.get(COL["auteurs"], ""),
            "condition_n2000": condition,
        })
        (ligne["corine_code"], ligne["corine_cd_hab"], ligne["corine_nom"],
         ligne["corine_autres"]) = _premier(corine)
        (ligne["eunis_code"], ligne["eunis_cd_hab"], ligne["eunis_nom"],
         ligne["eunis_autres"]) = _premier(eunis)
        (ligne["n2000_code"], ligne["n2000_cd_hab"], ligne["n2000_nom"],
         _) = _premier(
            n2000, {"Habitats_d'intérêt_communautaire"})
        (ligne["cahiers_code"], ligne["cahiers_cd_hab"], ligne["cahiers_nom"],
         _) = _premier(n2000, {"Cahiers_d'habitats"})

        typologie, entree = habref.par_nom(alliance)
        if entree is not None:
            ligne.update({
                "cd_hab": entree.get("cd_hab"), "typologie": typologie,
                "code_habref": entree.get("lb_code") or "",
                "nom_habref": nom_habref(entree.get("search_name")),
            })
            if not entree.get("lb_code"):
                anomalies.append({
                    "ligne_xlsx": numero, "alliance": alliance, "gravite": "information",
                    "type": "habref_sans_code",
                    "detail": "entrée %s sans lb_code (cd_hab %s) : elle s'affichera "
                              "sans code" % (typologie, entree.get("cd_hab")),
                })
        else:
            # Alliance absente de HABREF : on l'ancre sur son code CORINE/EUNIS.
            ancre = choisir_ancre(
                [c for c, _t, e in corine if e is not None],
                [c for c, _t, e in eunis if e is not None],
            )
            if ancre is None:
                anomalies.append({
                    "ligne_xlsx": numero, "alliance": alliance, "gravite": "bloquant",
                    "type": "alliance_sans_ancre",
                    "detail": "absente de HABREF et sans code CORINE ni EUNIS "
                              "résoluble : non saisissable en l'état",
                })
            else:
                typo_ancre, code_ancre = ancre
                source = corine if typo_ancre == "CORINE_biotopes" else eunis
                cd_hab = next(e.get("cd_hab") for c, _t, e in source
                              if c == code_ancre and e is not None)
                ligne.update({
                    "ancre_cd_hab": cd_hab, "ancre_typologie": typo_ancre,
                    "ancre_code": code_ancre,
                })
                anomalies.append({
                    "ligne_xlsx": numero, "alliance": alliance, "gravite": "information",
                    "type": "alliance_hors_habref",
                    "detail": "ancrée sur %s %s (cd_hab %s) ; le nom d'alliance ira "
                              "en nom cité" % (typo_ancre, code_ancre, cd_hab),
                })
        dico.append(ligne)
        if len(dico) % 25 == 0:
            journal("  %d alliances traitées…" % len(dico))

    # Un complément qui ne rencontre aucune ligne de catalogue ne s'applique
    # pas — et sans cette anomalie, le compte rendu annoncerait pourtant une
    # correction « appliquée » : le numéro de ligne a bougé, ou la ligne visée
    # est écartée du catalogue.
    for numero in sorted(set(complements) - appliques):
        anomalies.append({
            "ligne_xlsx": numero, "alliance": "", "gravite": "bloquant",
            "type": "complement_sans_cible",
            "detail": "aucune ligne de catalogue à cette ligne : le complément "
                      "%s n'a PAS été appliqué" % complements[numero],
        })
    return dico, anomalies


def _ecrire(chemin, champs, lignes):
    """CSV point-virgule, UTF-8 avec BOM : LibreOffice et Excel l'ouvrent tel quel."""
    with open(chemin, "w", encoding="utf-8-sig", newline="") as fichier:
        redacteur = csv.DictWriter(fichier, fieldnames=champs, delimiter=";")
        redacteur.writeheader()
        redacteur.writerows(lignes)


def resumer(dico, anomalies, journal=print):
    """Compte rendu — et rappel de ce que le script ne sait pas lire."""
    ancrees = [l for l in dico if l["ancre_cd_hab"]]
    resolues = [l for l in dico if l["cd_hab"]]
    par_type = {}
    for anomalie in anomalies:
        par_type.setdefault(anomalie["type"], []).append(anomalie)

    journal("")
    journal("Alliances du catalogue      : %d" % len(dico))
    journal("  résolues dans HABREF      : %d" % len(resolues))
    journal("  ancrées sur CORINE/EUNIS  : %d" % len(ancrees))
    journal("  ni l'un ni l'autre        : %d"
            % len(par_type.get("alliance_sans_ancre", [])))
    for typologie in ("corine", "eunis", "n2000", "cahiers"):
        journal("Correspondances %-9s : %d"
                % (typologie, sum(1 for l in dico if l["%s_cd_hab" % typologie])))
    journal("")
    journal("Anomalies : %d" % len(anomalies))
    for type_anomalie, liste in sorted(par_type.items()):
        journal("  %-24s %3d  (%s)" % (type_anomalie, len(liste), liste[0]["gravite"]))
    bloquants = [a for a in anomalies if a["gravite"] == "bloquant"]
    if bloquants:
        journal("")
        journal("BLOQUANTS — à compléter dans le tableur :")
        for anomalie in bloquants:
            journal("  l.%-4s %s" % (anomalie["ligne_xlsx"], anomalie["alliance"]))
    journal("")
    journal("Rappel : les COULEURS du fichier ne sont pas lues. Elles portent au")
    journal("moins « divergence avec le PVF II » et « présence incertaine en")
    journal("Ariège » ; tant qu'elles ne sont pas des colonnes, cette information")
    journal("n'arrive pas au plugin.")


def main(argv=None):
    parseur = argparse.ArgumentParser(
        description="Catalogue des végétations (xlsx) → dictionnaire de correspondances.",
    )
    parseur.add_argument(
        "xlsx", nargs="?", default=CATALOGUE_SOURCE,
        help="chemin du classeur des botanistes (défaut : celui du dépôt)")
    parseur.add_argument(
        "--api", default="https://geonature.ariegenature.fr/geonature/api",
        help="base de l'API GeoNature (les routes HABREF sont publiques)",
    )
    parseur.add_argument("--sortie", default=".", help="dossier des CSV produits")
    parseur.add_argument(
        "--cache", default=None,
        help="fichier de cache des résolutions HABREF (défaut : <sortie>/habref_cache.json)",
    )
    parseur.add_argument(
        "--complement", default=None,
        help="CSV de corrections provisoires (ligne_xlsx;corine;eunis;n2000)",
    )
    args = parseur.parse_args(argv)

    os.makedirs(args.sortie, exist_ok=True)
    cache = args.cache or os.path.join(args.sortie, "habref_cache.json")
    habref = Habref(args.api, cache=cache)
    complements = lire_complement(args.complement)
    if complements:
        print("Complément : %d lignes lues (l'application est vérifiée plus bas)"
              % len(complements))

    print("Lecture de %s" % args.xlsx)
    try:
        dico, anomalies = construire(args.xlsx, habref, complements)
    finally:
        habref.enregistrer_cache()  # ne jamais perdre l'acquis réseau

    chemin_dico = os.path.join(args.sortie, "dictionnaire_typologie.csv")
    chemin_anomalies = os.path.join(args.sortie, "anomalies_typologie.csv")
    _ecrire(chemin_dico, CHAMPS_DICO, dico)
    _ecrire(chemin_anomalies, CHAMPS_ANOMALIES, anomalies)
    resumer(dico, anomalies)
    print("")
    print("Écrit : %s" % chemin_dico)
    print("Écrit : %s" % chemin_anomalies)
    return 0


if __name__ == "__main__":
    sys.exit(main())
