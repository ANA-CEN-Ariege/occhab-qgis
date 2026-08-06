# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mise en TSV d'un tableau, pour coller dans un tableur (module pur, testable).

Le TSV est ce que LibreOffice et Excel collent sans rien demander : une tabulation
sépare les colonnes, un saut de ligne sépare les lignes. Encore faut-il que les
données n'en contiennent pas — or elles en contiennent. Un commentaire de station
tient sur plusieurs lignes, un nom cité peut porter une tabulation venue d'un
copier-coller. Sans échappement, une seule cellule décale tout le tableau, et
l'erreur ne se voit qu'après coup, une fois les colonnes mélangées.

D'où les guillemets de la convention CSV, que les deux tableurs comprennent dans
un flux TSV : la cellule est encadrée, et ses propres guillemets doublés.
"""

SEPARATEUR = "\t"
FIN_DE_LIGNE = "\r\n"  # attendu par Excel sous Windows, accepté partout ailleurs
_A_PROTEGER = ("\t", "\n", "\r", '"')


def cellule(valeur):
    """Une valeur en cellule TSV, échappée si elle peut casser le tableau."""
    texte = "" if valeur is None else str(valeur)
    if any(marque in texte for marque in _A_PROTEGER):
        return '"%s"' % texte.replace('"', '""')
    return texte


def tsv(lignes):
    """Lignes de valeurs (listes) en un bloc TSV prêt pour le presse-papiers."""
    return FIN_DE_LIGNE.join(
        SEPARATEUR.join(cellule(valeur) for valeur in ligne)
        for ligne in lignes or []
    )
