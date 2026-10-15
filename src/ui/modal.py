# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialogues et menus modaux détruits après usage.

Un dialogue ou un menu créé avec un parent vit aussi longtemps que lui : sans
destruction explicite, chaque fiche station, chaque fiche habitat, chaque menu
contextuel ouvert restait en mémoire jusqu'au déchargement de l'extension. Sous
Windows, une fenêtre affichée une fois garde sa fenêtre native et sa mémoire
d'affichage (des objets USER et GDI, quelques mégaoctets) tant qu'elle n'est pas
détruite. Une journée de saisie en accumulait des centaines, jusqu'à épuiser les
ressources du processus — et QGIS finissait par tomber.
"""


def executer(fenetre, *args):
    """`fenetre.exec(*args)`, puis destruction DIFFÉRÉE de la fenêtre.

    `deleteLater` n'agit qu'au retour à la boucle d'événements d'où il a été
    appelé, et jamais dans une boucle imbriquée (boîte de message, autre
    dialogue) : les résultats du dialogue restent lisibles jusqu'à la fin du
    traitement en cours.
    """
    try:
        return fenetre.exec(*args)
    finally:
        fenetre.deleteLater()
