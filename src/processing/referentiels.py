# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Référentiels fermés des champs métier (module pur, testable).

Deux origines, séparées volontairement :

- **Natura 2000** — « Inventaires et cartographie des habitats naturels et espèces
  végétales des sites Natura 2000 d'Occitanie », cahier des charges 2021,
  **annexe 2** (format de données, mise à jour du 28/09/2021). Les listes sont
  transcrites **dans l'ordre de l'annexe**, pour rester vérifiables ligne à ligne
  face au document.
- **ANA** — le niveau d'enjeu, qui n'existe pas dans le cahier des charges.

En interne les valeurs sont des **codes textuels** (comme le reste des champs
métier, cf. `eval_fields`) ; les **codes numériques** de l'annexe sont donnés à
part (`CDC_*`), car ils ne concernent que le rendu réglementaire. Découpler les
deux évite d'avoir à migrer les données déjà saisies à chaque ajustement du
format de restitution.

Chaque liste s'accompagne d'une table d'alias des codes hérités : sans elle, une
valeur retirée du référentiel serait relue « non renseigné » puis **effacée** au
premier réenregistrement (`encode_eval` n'écrit pas un code hors liste).
"""

# --- Workflow : état métier d'une station. -----------------------------------
# Distinct de l'état de synchronisation, qui est technique. Les botanistes
# reviennent plusieurs fois sur une station avant de la figer ; la synchro sert
# entre-temps de sauvegarde (fin de journée), donc un brouillon PART sur
# GeoNature — d'où la nécessité que ce statut y voyage aussi (bloc ANA-EVAL).
# Ces deux codes sont aussi définis dans `database.sqlite_local`, qui doit rester
# sans dépendance : un test vérifie que les deux listes ne divergent pas.
BROUILLON = "brouillon"
VALIDE = "valide"
STATUTS_VALIDATION = [
    (BROUILLON, "Brouillon"),
    (VALIDE, "Validé"),
]

# --- ANA : niveau d'enjeu (hors cahier des charges N2000). -------------------
# Ordre d'AFFICHAGE : du plus fort au plus faible, sens de lecture d'une liste
# de priorité. Les codes stockés ne dépendent pas de cet ordre.
NIVEAUX_ENJEU = [
    ("tres_fort", "Très fort"),
    ("fort", "Fort"),
    ("moyen", "Moyen"),
    ("faible", "Faible"),
    ("aucun", "Aucun"),
    ("inconnu", "Inconnu"),
]
ALIAS_ENJEU = {"majeur": "tres_fort"}  # référentiel ANA antérieur

# --- ANA : zone humide (hors cahier des charges N2000). ---------------------
# Le terrain distingue trois cas, pas deux : une station manifestement humide,
# une qui ne l'est pas, et celle dont on ne peut trancher sans y retourner — un
# bas-fond en fin d'été, une prairie vue par photo-interprétation. Une case à
# cocher forçait ce troisième cas dans « non », c'est-à-dire dans l'oubli.
ZONES_HUMIDES = [
    ("oui", "Oui"),
    ("non", "Non"),
    ("a_verifier", "À vérifier"),
]
#: Le champ était un booléen : `True` valait « oui », et l'absence de valeur ne
#: voulait rien dire de plus qu'une case décochée. Les données déjà saisies se
#: relisent donc sans conversion (cf. `eval_fields._normalize`).
ALIAS_ZONE_HUMIDE = {"true": "oui", "vrai": "oui", "false": "non", "faux": "non"}

# --- Annexe 2, table HABITAT : id_et_cons (état de conservation). ------------
ETATS_CONSERVATION = [
    ("inconnu", "Inconnu"),
    ("excellent", "Excellent"),
    ("bon", "Bon"),
    ("moyen", "Moyen"),
    ("mauvais", "Mauvais"),
]
ALIAS_ETAT = {"nd": "inconnu"}  # « Non déterminé » du référentiel ANA antérieur
CDC_ETAT_CONSERVATION = {
    "inconnu": 0, "excellent": 1, "bon": 2, "moyen": 3, "mauvais": 4,
}

# --- Annexe 2, table HABITAT : id_dynam (dynamique). -------------------------
DYNAMIQUES = [
    ("inconnue", "Inconnue"),
    ("stable", "Stable"),
    ("progressive_lente", "Progressive lente"),
    ("regressive_lente", "Régressive lente"),
    ("progressive_rapide", "Progressive rapide"),
    ("regressive_rapide", "Régressive rapide"),
]
CDC_DYNAMIQUE = {
    "inconnue": 0, "stable": 1, "progressive_lente": 2, "regressive_lente": 3,
    "progressive_rapide": 4, "regressive_rapide": 5,
}

# --- Annexe 2, table HABITAT : id_restaur (restauration). --------------------
# L'ordre est celui de l'annexe (difficile avant impossible avant possible) :
# transcription fidèle, pas un classement.
RESTAURATIONS = [
    ("inconnu", "Inconnu"),
    ("difficile", "Difficile"),
    ("impossible", "Impossible"),
    ("possible", "Possible"),
    ("possible_avec_efforts", "Possible avec efforts"),
]
CDC_RESTAURATION = {
    "inconnu": 0, "difficile": 1, "impossible": 2, "possible": 3,
    "possible_avec_efforts": 4,
}

# --- Annexe 2, table HABITAT : id_typi (typicité). ---------------------------
TYPICITES = [
    ("inconnue", "Inconnue"),
    ("bonne", "Bonne"),
    ("moyenne", "Moyenne"),
    ("mauvaise", "Mauvaise"),
]
CDC_TYPICITE = {"inconnue": 0, "bonne": 1, "moyenne": 2, "mauvaise": 3}

# --- Annexe 2, table GEOMETRIE : id_uv (clé unité végétale). -----------------
# Champ de la STATION. Ce n'est pas seulement un « type de mosaïque » : il code
# aussi l'unité simple et l'unité mixte, et doit rester cohérent avec le nombre
# d'habitats saisis (une unité non complexe = un seul habitat).
UNITES_VEGETALES = [
    ("non_complexe", "Unité non complexe"),
    ("mosaique_non_definie", "Mosaïque de type non défini"),
    ("mosaique_temporelle", "Mosaïque temporelle"),
    ("mosaique_topographique", "Mosaïque topographique"),
    ("mixte", "Unité mixte"),
]
CDC_UNITE_VEGETALE = {
    "non_complexe": 1, "mosaique_non_definie": 2, "mosaique_temporelle": 3,
    "mosaique_topographique": 4, "mixte": 5,
}

# --- Annexe 2, table GEOMETRIE : id_nat_obs (nature de l'observation). -------
NATURES_OBSERVATION = [
    ("inconnu", "Inconnu"),
    ("directe_avec_releve", "Observation directe avec relevé phytosociologique"),
    ("directe_sans_releve", "Observation directe sans relevé phytosociologique"),
    ("a_distance", "Observation à distance"),
    ("photo_interpretation", "Photo-interprétation"),
    ("autre", "Autre"),
]
CDC_NATURE_OBSERVATION = {
    "inconnu": 0, "directe_avec_releve": 1, "directe_sans_releve": 2,
    "a_distance": 3, "photo_interpretation": 4, "autre": 5,
}


def codes(items):
    """Ensemble des codes valides d'un référentiel."""
    return {code for code, _ in items}


def label_for(items, code, default=""):
    """Libellé d'un code dans un référentiel."""
    for value, label in items:
        if value == code:
            return label
    return default


def normalize(code, alias):
    """Code courant correspondant à `code` (éventuellement hérité)."""
    return alias.get(code, code)
