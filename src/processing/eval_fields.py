# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Champs métier ANA / Natura 2000 encodés dans les champs libres d'OccHab.

OccHab n'a pas de champ natif pour ces notions, et le module ne gère pas les
champs additionnels de GeoNature : le seul canal d'écriture reste les champs
texte — `comment` (station) et `technical_precision` (habitat). On y insère un
**bloc balisé non destructif** dont le contenu est du **JSON** :

    Texte libre saisi par l'utilisateur.

    [ANA-EVAL] {"enjeu": "fort", "etat_conservation": "bon", "typicite": "bonne"} [/ANA-EVAL]

**Pourquoi JSON** : les champs Natura 2000 comprennent du texte libre (critère,
remarque) et des listes (taxons). Le format historique `clé=valeur | clé=valeur`
ne survivait pas à un `|`, un `]` ou un retour à la ligne saisis par
l'utilisateur. JSON échappe tout par construction, et PostgreSQL le relit d'un
seul cast `::jsonb` au lieu d'une dizaine de `regexp_match` (voir README §6).

**L'ancien format reste lu** : les stations déjà synchronisées le portent. Le
décodage l'accepte et le convertit ; la première réécriture les fait passer en
JSON, sans jamais toucher au texte humain.

Les valeurs sont **validées à l'écriture comme à la lecture** contre les
référentiels (`referentiels.py`) : un code hors liste n'est pas écrit, et un code
hérité est converti au passage. Ce module ne dépend que de la bibliothèque
standard.
"""
import json
import re

try:  # importable dans le paquet (plugin) comme en isolation (tests)
    from . import referentiels as ref
except ImportError:  # pragma: no cover - repli hors paquet
    import referentiels as ref

# Ré-exports : les formulaires peuplent leurs menus depuis ces listes.
NIVEAUX_ENJEU = ref.NIVEAUX_ENJEU
ETATS_CONSERVATION = ref.ETATS_CONSERVATION
ZONES_HUMIDES = ref.ZONES_HUMIDES

# --- Description des clés du bloc. -------------------------------------------
# Codes fermés : {clé: (codes valides, alias des codes hérités)}.
_CODE_FIELDS = {
    "statut": (ref.codes(ref.STATUTS_VALIDATION), {}),
    "enjeu": (ref.codes(ref.NIVEAUX_ENJEU), ref.ALIAS_ENJEU),
    "etat_conservation": (ref.codes(ref.ETATS_CONSERVATION), ref.ALIAS_ETAT),
    "dynamique": (ref.codes(ref.DYNAMIQUES), {}),
    "restauration": (ref.codes(ref.RESTAURATIONS), {}),
    "typicite": (ref.codes(ref.TYPICITES), {}),
    "unite_vegetale": (ref.codes(ref.UNITES_VEGETALES), {}),
    "nature_observation": (ref.codes(ref.NATURES_OBSERVATION), {}),
    "zone_humide": (ref.codes(ref.ZONES_HUMIDES), ref.ALIAS_ZONE_HUMIDE),
}
_TEXT_FIELDS = ("critere", "remarque")
_LIST_FIELDS = {"pee": 3}  # plantes exotiques envahissantes : 3 taxons au plus

# --- Détermination hors HABREF et correspondances arbitrées. -----------------
# Deux clés STRUCTURÉES, seules de leur espèce dans le bloc :
#
#   "determination": {"nom": "Salicion pyrenaicae", "ancre": "CORINE_biotopes"}
#   "corresp": {"EUNIS": {"cd_hab": 5678, "src": "manuel"}}
#
# `determination` n'apparaît que lorsque le `cd_hab` de l'habitat est une ANCRE
# — un code emprunté à CORINE ou EUNIS parce que HABREF ne connaît pas
# l'alliance déterminée. Sans elle, personne ne saurait relire la donnée : rien
# ne distinguerait un code CORINE choisi comme détermination d'un code CORINE
# posé faute de mieux.
#
# `corresp` porte les correspondances INSCRITES dans la donnée, qui priment sur
# celles que la vue d'export recalcule depuis HABREF — c'est tout l'objet de la
# fonctionnalité : le calcul automatique n'est pas toujours juste, et le
# botaniste doit pouvoir trancher.
#
# `src` atteste d'un arbitrage humain (« manuel ») ou d'une reprise du catalogue
# (« catalogue »). Une valeur hors référentiel est ÉCARTÉE plutôt que corrigée :
# inventer « manuel » ferait croire à une vérification qui n'a pas eu lieu.
_TYPOLOGIES_CORRESP = {cle for cle, _libelle, _court in
                       ref.TYPOLOGIES_CORRESPONDANCE}
# Entiers bornés : {clé: (mini, maxi)}. `echelle` = échelle de numérisation,
# obligatoire au cahier des charges N2000 (ex. 5000 pour du 1:5 000).
_INT_FIELDS = {"echelle": (1, 1_000_000)}

# --- Convention d'encodage. ---------------------------------------------------
EVAL_START = "[ANA-EVAL]"
EVAL_END = "[/ANA-EVAL]"
_EVAL_RE = re.compile(re.escape(EVAL_START) + r"(.*?)" + re.escape(EVAL_END), re.DOTALL)


def normalize_enjeu(code):
    """Code d'enjeu courant correspondant à `code` (éventuellement hérité)."""
    return ref.normalize(code, ref.ALIAS_ENJEU)


def normalize_etat(code):
    """Code d'état de conservation courant correspondant à `code`."""
    return ref.normalize(code, ref.ALIAS_ETAT)


def _without_markers(text):
    """Retirer les balises du bloc d'un texte libre.

    Ce sont NOS délimiteurs : JSON échappe les guillemets, pas les crochets. Une
    balise saisie par l'utilisateur — ou collée avec un commentaire recopié
    depuis une autre station via l'interface web — ferait couper le bloc au
    mauvais endroit à la relecture, et ses valeurs seraient silencieusement
    perdues au premier réenregistrement.
    """
    return (text or "").replace(EVAL_START, "").replace(EVAL_END, "")


def _clean(key, value):
    """Valeur normalisée à écrire pour `key`, ou None si rien à écrire.

    Sert à l'encodage **et** au décodage : la validation et la conversion des
    codes hérités se font ainsi au même endroit, dans les deux sens.
    """
    if key == "zone_humide" and isinstance(value, bool):
        # Ancien format : le champ était une case à cocher. `True` vaut « oui » ;
        # `False` ne disait pas « non », seulement « pas coché » — donc rien.
        return "oui" if value else None
    if key in _CODE_FIELDS:
        valid, alias = _CODE_FIELDS[key]
        code = ref.normalize(value, alias)
        return code if code in valid else None
    if key == "recouvrement":
        return _valid_recouvrement(value)
    if key in _INT_FIELDS:
        mini, maxi = _INT_FIELDS[key]
        if isinstance(value, bool):
            return None
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
        return number if mini <= number <= maxi else None
    if key in _TEXT_FIELDS:
        text = _without_markers(value).strip() if isinstance(value, str) else ""
        return text or None
    if key in _LIST_FIELDS:
        if isinstance(value, str):  # une valeur seule vaut une liste d'un élément
            value = [value]
        items = [_without_markers(str(v)).strip() for v in (value or [])]
        items = [item for item in items if item]
        return items[: _LIST_FIELDS[key]] or None
    if key == "determination":
        return _clean_determination(value)
    if key == "corresp":
        return _clean_corresp(value)
    return None  # clé inconnue : ignorée, le bloc reste normalisé


def _texte(valeur):
    """Texte propre pour le bloc, ou None. Les balises sont retirées."""
    if not isinstance(valeur, str):
        return None
    return _without_markers(valeur).strip() or None


def _clean_determination(value):
    """{'nom': …, 'ancre': …} — le nom fait foi, l'ancre est facultative."""
    if not isinstance(value, dict):
        return None
    nom = _texte(value.get("nom"))
    if not nom:
        return None  # une détermination sans nom ne dit rien
    propre = {"nom": nom}
    ancre = value.get("ancre")
    if ancre in _TYPOLOGIES_CORRESP:
        propre["ancre"] = ancre
    return propre


def _clean_corresp(value):
    """{typologie: {'cd_hab': int, 'src': str}} — validé typologie par
    typologie. Code et libellé sont retrouvés depuis HABREF à la lecture/export.

    Une typologie inconnue est écartée (le bloc reste normalisé) ; une entrée
    sans `cd_hab` exploitable aussi, car c'est le `cd_hab` qui fait la
    correspondance.
    """
    if not isinstance(value, dict):
        return None
    propre = {}
    for typologie, detail in value.items():
        if typologie not in _TYPOLOGIES_CORRESP or not isinstance(detail, dict):
            continue
        cd_hab = detail.get("cd_hab")
        if isinstance(cd_hab, bool):
            continue
        try:
            cd_hab = int(cd_hab)
        except (TypeError, ValueError):
            continue
        if cd_hab <= 0:
            continue
        entree = {"cd_hab": cd_hab}
        if detail.get("src") in ref.SOURCES_CORRESPONDANCE:
            entree["src"] = detail["src"]
        propre[typologie] = entree
    return propre or None


def _raw_block(text):
    """Contenu brut entre les balises, ou None s'il n'y a pas de bloc."""
    match = _EVAL_RE.search(text or "")
    return match.group(1).strip() if match else None


def _parse_legacy(raw):
    """Ancien format `clé=valeur | clé=valeur` → dict."""
    result = {}
    for part in raw.split("|"):
        if "=" in part:
            key, value = (piece.strip() for piece in part.split("=", 1))
            if value:
                result[key] = value
    return result


def bloc_brut(text):
    """Contenu du bloc TEL QU'ÉCRIT, sans validation ni normalisation. {} si aucun.

    `decode_eval` est la lecture normale : elle rend la donnée conforme au format
    courant, et écarte donc ce qui n'en fait plus partie. Constater qu'un bloc
    porte encore un champ abandonné — pour le réécrire — demande de voir ce qui
    est réellement stocké, d'où cette lecture-ci.
    """
    raw = _raw_block(text)
    if raw is None:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def decode_eval(text):
    """Extraire {clé: valeur} depuis un champ libre. {} si aucun bloc.

    Accepte le bloc JSON comme l'ancien `clé=valeur`. Les valeurs renvoyées sont
    **déjà normalisées** (codes hérités convertis, valeurs hors référentiel
    écartées, `zone_humide` en booléen, `recouvrement` en nombre) : les appelants
    n'ont rien à retraiter.
    """
    raw = _raw_block(text)
    if raw is None:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = _parse_legacy(raw)
    result = {}
    for key, value in data.items():
        cleaned = _clean(key, value)
        if cleaned is not None:
            result[key] = cleaned
    return result


def strip_eval(text):
    """Retourner le texte humain seul (bloc retiré), pour l'affichage."""
    return _EVAL_RE.sub("", text or "").strip()


def encode_eval(text, **values):
    """Insérer/mettre à jour le bloc SANS écraser le texte libre existant.

    Chaque valeur est validée (`_clean`) : une clé inconnue, vide ou hors
    référentiel n'est pas écrite. Les clés sont triées pour que deux
    enregistrements successifs d'une même saisie produisent le même texte (sans
    quoi la détection de conflit verrait une différence à chaque fois).
    """
    # strip_eval retire les blocs complets ; _without_markers, les balises
    # orphelines qui feraient dérailler la prochaine relecture.
    human = _without_markers(strip_eval(text)).strip()

    data = {}
    for key, value in values.items():
        cleaned = _clean(key, value)
        if cleaned is not None:
            data[key] = cleaned

    if not data:
        return human  # rien à encoder → seul le texte humain subsiste

    block = "%s %s %s" % (
        EVAL_START, json.dumps(data, ensure_ascii=False, sort_keys=True), EVAL_END,
    )
    return ("%s\n\n%s" % (human, block)).strip() if human else block


def merge_eval(text, **values):
    """Mettre à jour CERTAINES clés du bloc, en conservant les autres.

    `encode_eval` remplace le bloc entier : il convient au formulaire, qui
    connaît toutes les valeurs. Pour une écriture partielle — changer le seul
    statut de validation sans rouvrir la station — il faut relire l'existant et
    fusionner, sinon l'enjeu, la typicité et le reste seraient effacés au
    passage. Une valeur à None **supprime** la clé.
    """
    data = decode_eval(text)
    for key, value in values.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return encode_eval(text, **data)


def _valid_recouvrement(value):
    """Normaliser un pourcentage de recouvrement (0<v<=100), ou None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    if not 0 < val <= 100:
        return None
    return int(val) if val == int(val) else val


def cover_class(percentage):
    """Classe ABONDANCE_HAB (cd_nomenclature 1..5) correspondant à un % de recouvrement.

    1 : < 5 % · 2 : 5-25 % · 3 : 25-50 % · 4 : 50-75 % · 5 : > 75 %.
    """
    pct = _valid_recouvrement(percentage)
    if pct is None:
        return None
    if pct < 5:
        return 1
    if pct < 25:
        return 2
    if pct < 50:
        return 3
    if pct <= 75:
        return 4
    return 5


# --- Aides pour les QComboBox (le code est stocké en itemData). --------------
def fill_eval_combo(combo, items, placeholder="— non renseigné —"):
    """Peupler une combo avec un placeholder (data None) puis (code, libellé)."""
    combo.clear()
    combo.addItem(placeholder, None)
    for code, label in items:
        combo.addItem(label, code)


def select_combo_data(combo, code):
    """Sélectionner l'entrée dont l'itemData vaut `code` (placeholder sinon)."""
    index = combo.findData(code) if code else -1
    combo.setCurrentIndex(index if index >= 0 else 0)
