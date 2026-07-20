# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Champs métier ANA (niveau d'enjeu, état de conservation, recouvrement).

OccHab n'a pas de champ natif exposé pour ces notions. On les stocke, de façon
normalisée, dans les champs libres OccHab (`comment` de la station,
`technical_precision` de l'habitat) via un bloc balisé non destructif :

    Texte libre saisi par l'utilisateur.

    [ANA-EVAL] enjeu=fort | etat_conservation=moyen | recouvrement=3 [/ANA-EVAL]

- enjeu / etat_conservation : CODE issu d'un référentiel fermé (NIVEAUX_ENJEU,
  ETATS_CONSERVATION).
- recouvrement : pourcentage (0-100) ; il pilote aussi la nomenclature Abondance
  via `cover_class()` (côté formulaire habitat).

N'écrire que des codes/valeurs normalisés permet une ré-extraction fiable côté
PostgreSQL (voir README §6, vue `ana_occhab.v_occhab_complet` ; pour recouvrement,
capturer `[0-9.]+`).

Ce module ne dépend que de la bibliothèque standard.
"""
import re

# --- Référentiels fermés (codes normalisés). ---------------------------------
# À terme, adosser ces codes à une nomenclature GeoNature dédiée
# (mnémoniques ANA_ENJEU / ANA_ETAT_CONSERV).
NIVEAUX_ENJEU = [
    ("faible", "Faible"),
    ("moyen", "Moyen"),
    ("fort", "Fort"),
    ("majeur", "Majeur"),
]

ETATS_CONSERVATION = [
    ("bon", "Bon"),
    ("moyen", "Moyen / altéré"),
    ("mauvais", "Mauvais / dégradé"),
    ("nd", "Non déterminé"),
]

CODES_ENJEU = {code for code, _ in NIVEAUX_ENJEU}
CODES_ETAT = {code for code, _ in ETATS_CONSERVATION}

# --- Convention d'encodage. ---------------------------------------------------
EVAL_START = "[ANA-EVAL]"
EVAL_END = "[/ANA-EVAL]"
_EVAL_RE = re.compile(re.escape(EVAL_START) + r"(.*?)" + re.escape(EVAL_END), re.DOTALL)


def decode_eval(text):
    """Extraire {clé: code} depuis un champ libre. {} si aucun bloc."""
    if not text:
        return {}
    match = _EVAL_RE.search(text)
    if not match:
        return {}
    result = {}
    for part in match.group(1).split("|"):
        if "=" in part:
            key, value = (piece.strip() for piece in part.split("=", 1))
            if value:
                result[key] = value
    return result


def strip_eval(text):
    """Retourner le texte humain seul (bloc retiré), pour l'affichage."""
    return _EVAL_RE.sub("", text or "").strip()


def encode_eval(text, enjeu=None, etat_conservation=None, recouvrement=None):
    """Insérer/mettre à jour le bloc SANS écraser le texte libre existant.

    enjeu/etat_conservation sont validés contre leur référentiel (valeur hors
    liste ignorée). `recouvrement` est un pourcentage 0-100 (nombre).
    """
    human = strip_eval(text)

    pairs = []
    if enjeu in CODES_ENJEU:
        pairs.append("enjeu=%s" % enjeu)
    if etat_conservation in CODES_ETAT:
        pairs.append("etat_conservation=%s" % etat_conservation)
    pct = _valid_recouvrement(recouvrement)
    if pct is not None:
        pairs.append("recouvrement=%s" % pct)

    if not pairs:
        return human  # rien à encoder → seul le texte humain subsiste

    block = "%s %s %s" % (EVAL_START, " | ".join(pairs), EVAL_END)
    return ("%s\n\n%s" % (human, block)).strip() if human else block


def _valid_recouvrement(value):
    """Normaliser un pourcentage de recouvrement (0<v<=100), ou None."""
    if value is None:
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


def label_for(items, code, default=""):
    """Libellé d'un code dans un référentiel (NIVEAUX_ENJEU / ETATS_CONSERVATION)."""
    for value, label in items:
        if value == code:
            return label
    return default


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
