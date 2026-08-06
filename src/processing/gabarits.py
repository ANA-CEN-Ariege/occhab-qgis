# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Repérage des gabarits de mise en page `.qpt` (module pur, testable).

Les gabarits de l'ANA portent le bandeau, le logo, l'adresse et les mentions
légales. Rien de tout cela n'a à être réinventé par le plugin : il suffit de les
retrouver, de les proposer, et de remplir ce qui varie.

Ils vivent là où l'organisation les a mis — dossier partagé, profil QGIS — d'où
une recherche dans plusieurs dossiers plutôt qu'un chemin en dur.
"""
import os

EXTENSION = ".qpt"
#: Objets que le plugin sait remplir dans un gabarit. Les identifiants sont ceux
#: des gabarits ANA ; un gabarit qui ne les porte pas reste utilisable, seul ce
#: qui manque n'est pas renseigné.
ID_CARTE = "Carte principale"
ID_APERCU = "Carte d'aperçu"
ID_LEGENDE = "Légende"
ID_ECHELLE = "Échelle"
ID_SOUS_TITRE = "Sous-titre"
#: Variables du gabarit, lues par ses étiquettes en expression.
VAR_FOND = {
    "bd_ortho": "fond_bd_ortho",
    "scan25": "fond_scan25",
    "cartes_ign": "fond_cartes_ign",
}
VAR_PIED = "footer_text"
VAR_ATTRIBUTIONS = "other_attributions"

#: Mention de source, telle que les gabarits ANA la rédigent. Reprise mot pour
#: mot : quand le cadre HTML doit être remplacé (cf. `print_layout`), le texte
#: qu'on écrit à sa place doit être celui qu'aurait produit le gabarit.
MENTIONS_FOND = {
    "bd_ortho": "<strong>Fond.</strong> BD ORTHO®, IGN.",
    "scan25": "<strong>Fond.</strong> SCAN25®, IGN.",
    "cartes_ign": "<strong>Fond.</strong> Cartes IGN.",
    "": "",
}
#: Début de la mention, pour reconnaître le cadre à corriger.
DEBUT_MENTION_FOND = "<strong>Fond.</strong>"

#: Fonds de plan citables, dans l'ordre où on les rencontre sur le terrain.
FONDS = [
    ("", "— aucun fond cité —"),
    ("bd_ortho", "BD ORTHO® (IGN)"),
    ("scan25", "SCAN25® (IGN)"),
    ("cartes_ign", "Cartes IGN"),
]


def libelle(chemin):
    """Nom lisible d'un gabarit, tiré de son nom de fichier."""
    base = os.path.basename(chemin or "")
    if base.lower().endswith(EXTENSION):
        base = base[: -len(EXTENSION)]
    return base.replace("_", " ").strip() or "gabarit"


def trouver(dossiers):
    """Gabarits `.qpt` des `dossiers`, dédoublonnés, triés par libellé.

    Un même gabarit peut se trouver dans deux dossiers — le partage réseau et la
    copie locale du profil QGIS. On garde le **premier** rencontré, l'ordre des
    dossiers valant priorité, sans quoi la liste proposerait deux fois la même
    carte sans qu'on sache laquelle part à l'impression.
    """
    vus, trouves = set(), []
    for dossier in dossiers or []:
        if not dossier or not os.path.isdir(dossier):
            continue
        try:
            noms = sorted(os.listdir(dossier))
        except OSError:  # dossier réseau déconnecté : on passe au suivant
            continue
        for nom in noms:
            if not nom.lower().endswith(EXTENSION):
                continue
            if nom.lower() in vus:
                continue
            chemin = os.path.join(dossier, nom)
            if os.path.isfile(chemin):
                vus.add(nom.lower())
                trouves.append(chemin)
    return sorted(trouves, key=lambda c: libelle(c).lower())


def variables_fond(code):
    """Variables à poser pour citer ce fond de plan (toutes les autres à vide).

    Le gabarit choisit sa mention par un `case` sur trois variables : les laisser
    telles quelles ferait citer un fond qu'on n'utilise pas — une erreur de
    source sur une carte diffusée.
    """
    return {nom: ("1" if cle == code else "") for cle, nom in VAR_FOND.items()}
