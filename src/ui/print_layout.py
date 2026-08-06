# SPDX-FileCopyrightText: 2026 Cédric Roy <it@ariegenature.fr>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Créer une mise en page QGIS à partir d'un gabarit ANA.

Le gabarit (`.qpt`) apporte tout ce qui ne change pas d'une carte à l'autre :
bandeau vert, logo, adresse, mentions légales, place des cadres. Ce module ne
fait que le charger et remplir ce qui varie — titre, sous-titre, emprise,
légende, échelle, fond cité.

Il ne DÉPLACE aucun cadre : la charte est celle de la structure, pas la nôtre.
La seule chose qu'il ajuste dans le gabarit est la **taille du texte de la
légende**, parce qu'elle seule dépend du nombre d'habitats — et qu'une légende
trop haute est tronquée par QGIS sans le moindre avertissement.
"""
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsLegendStyle,
    QgsExpressionContextUtils,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemPage,
    QgsLayoutItemScaleBar,
    QgsLegendRenderer,
    QgsPrintLayout,
    QgsProject,
    QgsReadWriteContext,
    QgsUnitTypes,
)

from ..processing import gabarits as gb
from ..processing import mise_en_page as mep

#: Unité de la barre d'échelle. L'énumération a changé de place entre les
#: versions de QGIS ; `QgsUnitTypes` la porte dans toutes.
_METRES = getattr(Qgis, "DistanceUnit", QgsUnitTypes).Meters \
    if hasattr(Qgis, "DistanceUnit") else QgsUnitTypes.DistanceMeters

#: Unité de mise en page. `Qgis.LayoutUnit` remplace `QgsUnitTypes` à partir de
#: QGIS 3.30, sans que l'ancien disparaisse.
_MILLIMETRES = getattr(getattr(Qgis, "LayoutUnit", QgsUnitTypes), "Millimeters",
                       None) or QgsUnitTypes.LayoutMillimeters

#: Marge de la page de légende, en millimètres. 12 passent sur toutes les
#: imprimantes de bureau, dont la zone non imprimable atteint couramment 6 mm.
MARGE_PAGE = 12.0
#: Écart gardé entre la légende et l'habillage qui l'encadre.
GOUTTIERE_PAGE = 4.0
#: Part de la largeur de page à partir de laquelle un objet est tenu pour un
#: BANDEAU — il borne alors la hauteur disponible et non la largeur.
PART_BANDEAU = 0.6

#: Marge ajoutée autour de l'emprise demandée, en part de sa largeur. Un cadrage
#: au ras des polygones donne une carte étouffée, et coupe les étiquettes.
MARGE_EMPRISE = 0.04


class GabaritIntrouvable(Exception):
    """Le fichier `.qpt` n'existe pas ou n'est pas lisible."""


class GabaritIllisible(Exception):
    """Le fichier existe mais QGIS n'en tire pas de mise en page."""


def creer(chemin_gabarit, titre, couche=None, couches_carte=None, emprise=None,
          crs=None, sous_titre="", fond="", pied="", projet=None, logger=None):
    """Construire la mise en page et l'ajouter au projet.

    Returns:
        (mise en page, avertissements) — la liste dit ce que la planche ne peut
        pas tenir, à commencer par une légende trop fournie pour son cadre. Elle
        est vide quand tout est en place.

    Args:
        chemin_gabarit: fichier `.qpt`.
        titre: nom de la mise en page — c'est lui que le bandeau affiche, les
            gabarits ANA titrant par l'expression `@layout_name`.
        couche: couche d'habitats — celle que la LÉGENDE détaille.
        couches_carte: couches à dessiner, dans l'ordre du canevas. C'est ce qui
            garde le fond de plan : restreindre la carte à la seule couche
            d'habitats effacerait l'ortho sous les polygones.
        emprise: `QgsRectangle` à cadrer, exprimé dans `crs`.
        crs: système de coordonnées de `emprise` ET de la carte.
        sous_titre: texte du cartouche sous le titre.
        fond: clé de fond de plan à citer (cf. `gabarits.FONDS`).
        pied: texte du pied de page.
    """
    projet = projet or QgsProject.instance()
    mise = _charger(chemin_gabarit, projet)
    nom = _nom_unique(projet, titre or "Carte des habitats")
    mise.setName(nom)

    avertissements = []
    carte = _carte(mise)
    if carte is None:
        avertissements.append(
            "Ce gabarit ne contient aucun cadre de carte : la planche est "
            "créée telle quelle, sans cartographie."
        )
    else:
        _cadrer(carte, couche, couches_carte, emprise, crs, projet)
        _lier_echelle(mise, carte)
        avertissements += _lier_legende(mise, carte, couche)

    sous = mise.itemById(gb.ID_SOUS_TITRE)
    if isinstance(sous, QgsLayoutItemLabel):
        # Un gabarit livré avec « Sous-titre ou texte complémentaire » afficherait
        # ce texte d'exemple sur la carte imprimée : on l'efface même si l'appelant
        # n'a rien à mettre à la place.
        sous.setText(sous_titre or "")

    variables = gb.variables_fond(fond)
    if pied:
        variables[gb.VAR_PIED] = pied
    for nom, valeur in variables.items():
        QgsExpressionContextUtils.setLayoutVariable(mise, nom, valeur)

    avertissements += _sans_webkit(mise, fond)
    _habiller_pages_suivantes(mise)

    # `addLayout` DÉTRUIT la mise en page si le nom est déjà pris — l'objet
    # Python survit mais son C++ a disparu, et le premier accès lève
    # « wrapped C/C++ object has been deleted ». D'où le nom unique plus haut,
    # et ce garde-fou : on ne touche plus à `mise` si l'ajout a échoué.
    if not projet.layoutManager().addLayout(mise):
        raise GabaritIllisible(
            "QGIS a refusé d'ajouter la mise en page « %s » au projet." % nom
        )
    if logger:
        logger.info("Mise en page « %s » créée depuis %s", nom, chemin_gabarit)
    return mise, avertissements


def _a_reporter(item):
    """Cet objet a-t-il sa place sur la page de légende ?

    Non pour les cartes, la légende elle-même — c'est le contenu de la page — et
    la barre d'échelle : une échelle sans carte à laquelle se rapporter ne veut
    rien dire, et elle ferait croire que la page est une carte.
    """
    from qgis.core import (QgsLayoutItem, QgsLayoutItemLegend, QgsLayoutItemMap,
                           QgsLayoutItemPage, QgsLayoutItemScaleBar)

    # `mise.items()` rend aussi les objets graphiques internes de Qt (poignées,
    # cadres de page) : seuls les vrais objets de mise en page savent s'écrire.
    if not isinstance(item, QgsLayoutItem):
        return False
    return not isinstance(item, (QgsLayoutItemMap, QgsLayoutItemLegend,
                                 QgsLayoutItemPage, QgsLayoutItemScaleBar))


def _habiller_pages_suivantes(mise):
    """Reporter le bandeau, le logo et les mentions sur la page de légende.

    Une page de légende nue ne s'identifie pas : sortie du PDF, imprimée seule,
    plus rien ne dit de quelle carte elle est la légende ni qui l'a produite.
    On y recopie donc tout ce que la page 1 porte hors carte — titre,
    sous-titre, logo, adresse, sources, pied de page, fond de bandeau — à la
    même place dans la page.

    Par sérialisation XML : les objets de mise en page n'ont pas de `clone()`
    en Python, mais ils savent tous s'écrire et se relire.
    """
    from qgis.PyQt.QtXml import QDomDocument
    from qgis.core import (QgsApplication, QgsLayoutPoint, QgsReadWriteContext)

    pages = mise.pageCollection()
    if pages.pageCount() < 2:
        return

    modeles = [i for i in mise.items()
               if _a_reporter(i) and pages.pageNumberForPoint(i.pos()) == 0]
    if not modeles:
        return

    for numero in range(1, pages.pageCount()):
        for modele in modeles:
            copie = _copier_item(modele, mise, QDomDocument, QgsApplication,
                                 QgsReadWriteContext)
            if copie is None:
                continue
            haut_page = pages.page(0).pos().y() if pages.page(0) else 0.0
            copie.attemptMove(
                QgsLayoutPoint(modele.pos().x(),
                               modele.pos().y() - haut_page, _MILLIMETRES),
                page=numero,
            )
            copie.setId("")  # l'identifiant reste celui de la page 1
    _recadrer_legende(mise)


def _recadrer_legende(mise):
    """Replacer la légende dans la bande laissée libre par l'habillage.

    Elle avait été posée à la marge de la page, avant que le bandeau, le logo et
    les mentions n'y soient recopiés : elle passait donc sous le titre. On la
    repose entre ce qui occupe le haut de la page et ce qui en occupe le bas, et
    on rejoue le choix de la taille et des colonnes pour la nouvelle boîte.
    """
    from qgis.core import (QgsLayoutItem, QgsLayoutItemLegend, QgsLayoutItemPage,
                           QgsLayoutPoint, QgsLayoutSize)

    pages = mise.pageCollection()
    legendes = [i for i in mise.items() if isinstance(i, QgsLayoutItemLegend)]
    if not legendes or pages.pageCount() < 2:
        return
    legende = legendes[0]
    numero = pages.pageNumberForPoint(legende.pos())
    page = pages.page(numero)
    if page is None or numero == 0:
        return

    largeur_page = page.pageSize().width()
    hauteur_page = page.pageSize().height()
    haut_page = page.pos().y()
    gauche, droite = MARGE_PAGE, largeur_page - MARGE_PAGE
    haut, bas = MARGE_PAGE, hauteur_page - MARGE_PAGE

    for item in mise.items():
        if not isinstance(item, QgsLayoutItem) or item is legende:
            continue
        if isinstance(item, QgsLayoutItemPage):
            continue
        if pages.pageNumberForPoint(item.pos()) != numero:
            continue
        x, y = item.pos().x(), item.pos().y() - haut_page
        l, h = item.rect().width(), item.rect().height()
        if h >= hauteur_page * 0.9 and l >= largeur_page * 0.9:
            continue  # fond de page : il ne borne rien

        # Un bandeau barre toute la largeur : il mange de la HAUTEUR. Un
        # cartouche qui n'occupe qu'une colonne mange de la LARGEUR. Traiter le
        # second comme le premier coûtait 46 mm de hauteur à la légende entière
        # pour un bloc large d'un quart de page.
        if l >= largeur_page * PART_BANDEAU:
            if y + h / 2.0 < hauteur_page / 2.0:
                haut = max(haut, y + h + GOUTTIERE_PAGE)
            else:
                bas = min(bas, y - GOUTTIERE_PAGE)
        elif x + l / 2.0 >= largeur_page / 2.0:
            droite = min(droite, x - GOUTTIERE_PAGE)
        else:
            gauche = max(gauche, x + l + GOUTTIERE_PAGE)

    largeur, hauteur = droite - gauche, bas - haut
    if largeur <= 0 or hauteur <= 0:
        return
    legende.setResizeToContents(True)
    _essayer(legende, largeur, hauteur)
    legende.attemptMove(QgsLayoutPoint(gauche, haut, _MILLIMETRES), page=numero)
    legende.setResizeToContents(False)
    legende.attemptResize(QgsLayoutSize(largeur, hauteur, _MILLIMETRES))
    legende.updateLegend()


def _copier_item(modele, mise, QDomDocument, QgsApplication, QgsReadWriteContext):
    """Recréer un objet de mise en page à l'identique, ou None."""
    document = QDomDocument()
    racine = document.createElement("occhab")
    document.appendChild(racine)
    if not modele.writeXml(racine, document, QgsReadWriteContext()):
        return None
    element = racine.firstChildElement()
    if element.isNull():
        return None
    # Effacer l'identifiant unique AVANT relecture : `readXml` le reprend tel
    # quel s'il est là, et la copie devient un homonyme parfait de l'original.
    # QGIS ne sait alors plus lequel des deux il manipule — à l'écran les deux
    # se dessinent, mais à l'EXPORT la page de légende ressortait nue, bandeau
    # et logo compris. En l'absence d'attribut, QGIS en fabrique un neuf.
    for attribut in ("uuid", "templateUuid"):
        element.removeAttribute(attribut)
    fabrique = QgsApplication.layoutItemRegistry()
    copie = fabrique.createItem(modele.type(), mise)
    if copie is None:
        return None
    # `includeUuid=False` : sans cela la copie hérite de l'identifiant unique de
    # l'original, et QGIS ne sait plus lequel des deux il manipule.
    if not copie.readXml(element, document, QgsReadWriteContext()):
        return None
    mise.addLayoutItem(copie)
    # Relire le XML ne suffit pas : une image embarquée en base64 et une
    # étiquette en expression ne sont décodées qu'au rafraîchissement. Sans lui,
    # le bandeau et le titre existaient bel et bien sur la page de légende — à
    # la bonne place, à la bonne taille — mais s'imprimaient blancs.
    for methode in ("refreshPicture", "refresh"):
        rafraichir = getattr(copie, methode, None)
        if callable(rafraichir):
            try:
                rafraichir()
            except Exception:  # noqa: BLE001 - un rendu ne doit pas tomber ici
                pass
    return copie


def _nom_unique(projet, souhaite):
    """Nom libre dans le gestionnaire, en numérotant si besoin.

    Refaire une carte est le geste ordinaire — on recadre, on change de fond —
    et deux planches ne peuvent pas porter le même nom.
    """
    gestionnaire = projet.layoutManager()
    pris = {m.name() for m in gestionnaire.layouts()}
    if souhaite not in pris:
        return souhaite
    for numero in range(2, 100):
        candidat = "%s (%d)" % (souhaite, numero)
        if candidat not in pris:
            return candidat
    return "%s (%d)" % (souhaite, len(pris) + 1)


def _webkit_disponible():
    """QtWebKit est-il de la partie ?

    Plusieurs paquets QGIS de Debian et d'Ubuntu sont construits sans lui. QGIS
    remplace alors chaque cadre HTML par un pavé rouge « WebKit not available »,
    à l'écran comme dans le PDF exporté.
    """
    try:
        from qgis.PyQt import QtWebKitWidgets  # noqa: F401
        return True
    except ImportError:
        return False


def _sans_webkit(mise, fond):
    """Remplacer les cadres HTML par des étiquettes quand WebKit manque.

    Les mentions légales, l'adresse et la ligne « Sources » des gabarits ANA sont
    des `QgsLayoutItemHtml`, seul objet de mise en page à réclamer WebKit. Une
    **étiquette en mode HTML** rend le même balisage — `<strong>`, `<br />` —
    par le moteur de texte de Qt, présent partout.

    On convertit donc plutôt que d'avertir : sans cela, la carte part à
    l'impression avec trois pavés rouges à la place de l'adresse et des sources,
    et la seule issue serait de modifier le gabarit de la structure.
    """
    from qgis.core import QgsLayoutItemHtml

    cadres = [m for m in mise.multiFrames() if isinstance(m, QgsLayoutItemHtml)]
    if not cadres or _webkit_disponible():
        return []

    remplaces = 0
    for multiframe in cadres:
        remplaces += _en_etiquettes(mise, multiframe, fond)
    if not remplaces:
        return []
    return [
        "Ce QGIS est construit sans WebKit : les %d cadres HTML du gabarit "
        "(adresse, sources, mention du fond) ont été convertis en étiquettes "
        "pour rester lisibles, à l'écran comme au PDF. Le gabarit d'origine "
        "n'est pas modifié." % remplaces
    ]


def _corps_de_texte(etiquette, taille_pt):
    """Imposer le corps à l'étiquette elle-même, pas seulement en CSS.

    En mode HTML, QGIS part de la police de l'OBJET et n'applique le style en
    ligne que par-dessus. Une feuille de style seule laissait l'adresse au corps
    par défaut, à cheval sur le bandeau de pied.
    """
    from qgis.core import QgsTextFormat

    if hasattr(etiquette, "setTextFormat"):
        format_texte = QgsTextFormat(etiquette.textFormat())
        police = format_texte.font()
        police.setPointSizeF(taille_pt)
        format_texte.setFont(police)
        format_texte.setSize(taille_pt)
        etiquette.setTextFormat(format_texte)
    elif hasattr(etiquette, "setFont"):
        police = QFont(etiquette.font())
        police.setPointSizeF(taille_pt)
        etiquette.setFont(police)


def _habiller(html, taille_pt):
    """Fragment HTML enveloppé d'un corps de texte, sans toucher au balisage."""
    return ('<div style="font-family:sans-serif; font-size:%.1fpt; '
            'line-height:1.15;">%s</div>' % (taille_pt, html))


def _en_etiquettes(mise, multiframe, fond):
    """Convertir un cadre HTML en étiquette(s) de même position. Renvoie le compte."""
    from qgis.core import QgsLayoutItemLabel, QgsLayoutPoint, QgsLayoutSize

    texte = multiframe.html() or ""
    if texte.strip().startswith(gb.DEBUT_MENTION_FOND):
        # Ce cadre-là est figé sur le fond du gabarit d'origine — SCAN25 dans
        # les nôtres. Le laisser tel quel citerait une source qu'on n'affiche
        # pas ; c'est l'erreur que le choix « Fond de plan cité » sert à éviter.
        texte = gb.MENTIONS_FOND.get(fond, "")

    geometries = [(f.id(), f.pos().x(), f.pos().y(),
                   f.rect().width(), f.rect().height(),
                   f.frameEnabled(), f.hasBackground())
                  for f in (multiframe.frame(i)
                            for i in range(multiframe.frameCount()))
                  if f is not None]
    if not geometries:
        return 0

    mode = getattr(getattr(QgsLayoutItemLabel, "Mode", QgsLayoutItemLabel),
                   "ModeHtml")
    for identifiant, x, y, largeur, hauteur, cadre, fond_plein in geometries:
        if not texte.strip():
            continue  # rien à dire : ne pas poser une étiquette vide
        etiquette = QgsLayoutItemLabel(mise)
        etiquette.setMode(mode)
        # La feuille de style du cadre HTML ne survit pas à la conversion, et une
        # étiquette ne réduit jamais son texte : sans corps imposé, l'adresse
        # s'affiche à la taille par défaut, trois fois trop grosse, à cheval sur
        # le pied de page.
        corps = mep.taille_pour_bloc(texte, largeur, hauteur)
        etiquette.setText(_habiller(texte, corps))
        _corps_de_texte(etiquette, corps)
        mise.addLayoutItem(etiquette)
        etiquette.attemptMove(QgsLayoutPoint(x, y, _MILLIMETRES))
        etiquette.attemptResize(QgsLayoutSize(largeur, hauteur, _MILLIMETRES))
        if identifiant:
            etiquette.setId(identifiant)
        etiquette.setFrameEnabled(cadre)
        etiquette.setBackgroundEnabled(fond_plein)

    # Retirer le multiframe APRÈS avoir relevé ses cadres : il les emporte.
    mise.removeMultiFrame(multiframe)
    for i in range(multiframe.frameCount() - 1, -1, -1):
        cadre_html = multiframe.frame(i)
        if cadre_html is not None:
            mise.removeLayoutItem(cadre_html)
    return len(geometries)


def _charger(chemin, projet):
    try:
        with open(chemin, encoding="utf-8") as fichier:
            contenu = fichier.read()
    except OSError as exc:
        raise GabaritIntrouvable(str(exc))
    document = QDomDocument()
    if not document.setContent(contenu):
        raise GabaritIllisible("le fichier n'est pas un gabarit QGIS valide")
    mise = QgsPrintLayout(projet)
    resultat = mise.loadFromTemplate(document, QgsReadWriteContext(), True)
    # `loadFromTemplate` rend (objets chargés, succès) ; un gabarit vide rend une
    # liste vide sans lever d'erreur, et donnerait une page blanche.
    charges = resultat[0] if isinstance(resultat, tuple) else resultat
    if not charges:
        raise GabaritIllisible("aucun objet dans le gabarit")
    return mise


def _carte(mise):
    """Cadre de carte à cadrer : celui du gabarit, sinon le plus grand.

    Le repli couvre les gabarits d'une autre provenance, dont les cadres ne
    portent pas les identifiants de l'ANA. Le plus grand cadre est la carte
    principale dans toutes les planches vues jusqu'ici — la carte d'aperçu est un
    encart.
    """
    carte = mise.itemById(gb.ID_CARTE)
    if isinstance(carte, QgsLayoutItemMap):
        return carte
    cartes = [i for i in mise.items() if isinstance(i, QgsLayoutItemMap)]
    if not cartes:
        return None
    return max(cartes, key=lambda c: c.rect().width() * c.rect().height())


def _cadrer(carte, couche, couches_carte, emprise, crs, projet):
    """Poser le système de coordonnées, l'emprise et les couches de la carte."""
    if crs is not None and crs.isValid():
        carte.setCrs(crs)
    if couches_carte:
        # Figer la pile de couches TELLE QU'À L'ÉCRAN, fond de plan compris :
        # sans cela la carte suit l'arbre du projet, et une couche allumée après
        # coup s'inviterait sur une planche déjà validée.
        carte.setLayers(list(couches_carte))
        carte.setFollowVisibilityPreset(False)
    if emprise is None and couche is not None:
        emprise = couche.extent()
        depart = couche.crs()
        cible = carte.crs()
        if depart.isValid() and cible.isValid() and depart != cible:
            emprise = QgsCoordinateTransform(depart, cible, projet) \
                .transformBoundingBox(emprise)
    if emprise is None or emprise.isEmpty():
        return
    carte.zoomToExtent(_agrandir(emprise, MARGE_EMPRISE))


def _agrandir(emprise, part):
    """Copie de l'emprise, élargie de `part` de son plus grand côté.

    Une copie, car `grow` mute en place : l'appelant nous passe souvent
    l'emprise de sa couche ou de son canevas, qu'on n'a pas à modifier.
    """
    agrandie = type(emprise)(emprise)
    agrandie.grow(max(agrandie.width(), agrandie.height()) * part)
    return agrandie


def _lier_echelle(mise, carte):
    """Rattacher la barre d'échelle à la carte, en mètres ou kilomètres.

    Une barre restée sur les unités de la carte affiche « 0 … 1 » quand la couche
    est en degrés : une échelle fausse est pire qu'une échelle absente.
    """
    echelle = mise.itemById(gb.ID_ECHELLE)
    if not isinstance(echelle, QgsLayoutItemScaleBar):
        candidats = [i for i in mise.items() if isinstance(i, QgsLayoutItemScaleBar)]
        echelle = candidats[0] if candidats else None
    if echelle is None:
        return
    echelle.setLinkedMap(carte)
    unites = _METRES
    echelle.setUnits(unites)
    echelle.setUnitLabel("m")
    # `applyDefaultSize` recalcule le pas des segments d'après l'échelle réelle
    # de la carte : c'est lui qui remplace le « 0 … 1 » hérité du gabarit par
    # une graduation ronde (0, 250, 500 m).
    echelle.applyDefaultSize(unites)
    echelle.update()


def _lier_legende(mise, carte, couche):
    """Rattacher la légende, la restreindre à la couche, l'ajuster à sa place.

    Returns:
        les avertissements à remonter (légende trop fournie, notamment).
    """
    legende = mise.itemById(gb.ID_LEGENDE)
    if not isinstance(legende, QgsLayoutItemLegend):
        candidats = [i for i in mise.items() if isinstance(i, QgsLayoutItemLegend)]
        legende = candidats[0] if candidats else None
    if legende is None:
        return ["Ce gabarit ne contient pas de légende."]
    legende.setLinkedMap(carte)
    legende.setLegendFilterByMapEnabled(True)
    if couche is not None:
        # Modèle figé sur la seule couche d'habitats : le modèle automatique
        # reprend tout l'arbre du projet, fonds de plan compris, et la colonne
        # déborde avant même d'avoir listé les habitats.
        legende.setAutoUpdateModel(False)
        _restreindre(legende, couche)
    alerte = _ajuster(legende)
    legende.updateLegend()
    return [alerte] if alerte else []


def _restreindre(legende, couche):
    """Ne garder que `couche`, et effacer les intitulés techniques.

    Laissés tels quels, la légende s'ouvre sur « OccHab (exports) » puis
    « Occhab complet (2026-01-01 → 2026-12-31) [bandes proportionnelles] » :
    le nom du groupe de couches et celui du fichier chargé. Ce sont des repères
    de travail, pas des postes de légende — sur une carte diffusée, ils font
    lire un nom de fichier avant les habitats.
    """
    modele = legende.model()
    racine = modele.rootGroup()
    for enfant in list(racine.children()):
        _elaguer(racine, enfant, couche.id())
    _degrouper(racine)
    for noeud in racine.findLayers():
        # Nom de couche masqué : les vrais intitulés sont les grands milieux,
        # que le rendu par règles porte déjà en sous-groupes.
        cache = _style_legende("Hidden")
        if cache is not None:
            QgsLegendRenderer.setNodeLegendStyle(noeud, cache)
    legende.setTitle("")  # le gabarit a déjà son cartouche « Légende »


def _degrouper(racine):
    """Remonter les couches hors des groupes du projet.

    « OccHab (exports) » est un rangement du panneau des couches ; il n'a rien à
    dire sur une carte imprimée.

    Par CLONES : `removeChildNode` détruit le nœud, et le déplacer reviendrait à
    ajouter un objet déjà supprimé — Qt lève alors « wrapped C/C++ object of type
    QgsLayerTreeLayer has been deleted ».
    """
    couches = [noeud.clone() for noeud in racine.findLayers()]
    for enfant in list(racine.children()):
        racine.removeChildNode(enfant)
    for noeud in couches:
        racine.addChildNode(noeud)


def _elaguer(parent, noeud, id_couche):
    """Supprimer le nœud s'il ne mène pas à la couche voulue."""
    if hasattr(noeud, "layerId"):
        if noeud.layerId() != id_couche:
            parent.removeChildNode(noeud)
        return
    for enfant in list(noeud.children()):
        _elaguer(noeud, enfant, id_couche)
    if not noeud.children():
        parent.removeChildNode(noeud)


def _ajuster(legende):
    """Contenir la légende dans la colonne du gabarit, ou lui donner une page.

    La taille du texte se règle sur la LARGEUR autant que sur la hauteur : QGIS
    ne coupe pas les libellés d'une légende, il ÉLARGIT le cadre. Un nom de
    syntaxon à rallonge pousse donc la légende par-dessus la carte, hors de la
    colonne du gabarit — c'est le débordement qu'on voit en premier.

    Aucune de ces tailles n'est calculée : elles sont **essayées**, et c'est QGIS
    qui mesure ce que ça donne (cf. `_essayer`).
    """
    libelles = _libelles(legende)
    largeur, hauteur = mep.espace_libre(_cadre(legende), _voisins(legende),
                                        _page(legende.layout()))
    if _essayer(legende, largeur, hauteur, colonnes=(1,)) is not None:
        _borner(legende, largeur, hauteur)
        return ""
    # Elle ne rentre pas dans la colonne du gabarit : plutôt que de la couper,
    # on lui donne une page. La carte y gagne — dans les gabarits ANA elle
    # occupe déjà toute la page, la colonne de légende était posée par-dessus.
    return _page_dediee(legende, len(libelles), largeur, hauteur)


def _essayer(legende, largeur, hauteur, colonnes=mep.COLONNES):
    """Chercher (taille, colonnes) qui tienne VRAIMENT, en mesurant à chaque fois.

    Estimer l'encombrement d'une légende à partir du nombre de caractères donne
    un résultat plausible et faux : la hauteur d'une entrée dépend du symbole,
    des marges de groupe et du rendu de la police. On applique donc chaque
    combinaison, on demande sa taille à QGIS, et on garde la première qui entre.

    Returns:
        (taille, colonnes) retenus, ou None si rien ne tient.
    """
    legende.setResizeToContents(True)
    for nombre in colonnes:
        legende.setColumnCount(nombre)
        legende.setEqualColumnWidth(nombre > 1)
        legende.setSplitLayer(nombre > 1)
        for taille in mep.TAILLES:
            _polices(legende, taille)
            legende.updateLegend()
            mesure = _mesurer(legende)
            if mesure is None:
                return taille, nombre  # mesure impossible : ne pas bloquer
            if mesure.width() <= largeur and mesure.height() <= hauteur:
                return taille, nombre
    return None


def _mesurer(legende):
    """Encombrement réel de la légende, en millimètres, ou None.

    `rect()` ne convient pas : hors écran, il rend la taille du cadre et non
    celle du contenu, et une légende trop haute paraît alors tenir. C'est
    `QgsLegendRenderer.minimumSize()` qui donne la place vraiment nécessaire —
    symboles, marges de groupe et rendu de police compris.
    """
    from qgis.core import QgsLayoutUtils, QgsLegendRenderer

    mise = legende.layout()
    if mise is None:
        return None
    try:
        contexte = QgsLayoutUtils.createRenderContextForLayout(mise, None)
        rendu = QgsLegendRenderer(legende.model(), legende.legendSettings())
        return rendu.minimumSize(contexte)
    except Exception:  # noqa: BLE001 - API mouvante ; on ne bloque pas la planche
        return None


def _style_legende(nom):
    """Composant de légende par son nom, quelle que soit la version de QGIS.

    `QgsLegendStyle.Style` est une énumération de portée, apparue après les
    constantes posées directement sur la classe. Les deux coexistent dans les
    versions récentes ; sur une 3.28 — la version minimale annoncée — seule la
    seconde existe, et y accéder par la première lève un `AttributeError`.
    """
    portee = getattr(QgsLegendStyle, "Style", None)
    return getattr(portee, nom, None) if portee is not None else \
        getattr(QgsLegendStyle, nom, None)


def _polices(legende, taille):
    """Poser le corps du texte sur tous les niveaux de la légende."""
    for composant in ("Symbol", "SymbolLabel", "Subgroup", "Group", "Title"):
        style = _style_legende(composant)
        if style is None:
            continue
        # `setStyleFont` et non `style(...).setTextFormat(...)` : cette dernière
        # travaille sur un objet TEMPORAIRE, détruit dès la fin de l'expression,
        # et Qt lève « wrapped C/C++ object has been deleted » à l'écriture.
        police = QFont(legende.style(style).textFormat().font())
        entete = composant in ("Group", "Subgroup", "Title")
        police.setPointSizeF(taille + 0.5 if entete else taille)
        if entete:
            police.setWeight(QFont.Weight.Bold)
        legende.setStyleFont(style, police)


def _page_dediee(legende, nombre_entrees, largeur_colonne, hauteur_colonne):
    """Déplacer la légende sur une deuxième page, à elle seule.

    Une carte d'habitats peut compter quarante syntaxons : aucune colonne de
    planche ne les tient, à aucune taille lisible. Les couper serait le pire des
    cas — QGIS le fait sans un mot, et on lit une carte à laquelle il manque des
    postes sans pouvoir s'en apercevoir. Une page de légende, elle, se lit à
    côté de la carte et ne perd rien.
    """
    from qgis.core import QgsLayoutItemPage, QgsLayoutPoint, QgsLayoutSize

    mise = legende.layout()
    pages = mise.pageCollection()
    gabarit = pages.page(0)
    if gabarit is None:
        return ""

    page = QgsLayoutItemPage(mise)
    page.setPageSize(gabarit.pageSize())
    pages.addPage(page)
    index = pages.pageCount() - 1

    largeur = gabarit.pageSize().width() - 2 * MARGE_PAGE
    hauteur = gabarit.pageSize().height() - 2 * MARGE_PAGE
    legende.setTitle("Légende")
    retenu = _essayer(legende, largeur, hauteur)

    legende.attemptMove(QgsLayoutPoint(MARGE_PAGE, MARGE_PAGE, _MILLIMETRES),
                        page=index)
    if retenu is None:
        # Rien ne tient, même en pleine page : on laisse le cadre suivre son
        # contenu plutôt que de le figer, sinon QGIS couperait en silence. La
        # légende débordera de la page, ce qui se VOIT — et le message le dit.
        legende.setResizeToContents(True)
        legende.updateLegend()
        return (
            "La légende compte %d entrées : même sur une page entière, à %.1f pt "
            "et %d colonnes, elle ne tient pas. Passez à un gabarit A3."
            % (nombre_entrees, mep.TAILLES[-1], mep.COLONNES[-1])
        )

    taille, colonnes = retenu
    legende.setResizeToContents(False)
    legende.attemptResize(QgsLayoutSize(largeur, hauteur, _MILLIMETRES))
    legende.updateLegend()
    return (
        "La légende compte %d entrées : trop pour les %.0f × %.0f mm que le "
        "gabarit lui réserve, elle a donc été placée sur une DEUXIÈME PAGE, à "
        "%.1f pt sur %d colonne(s). Rien n'est coupé, et la carte occupe "
        "désormais toute la page 1."
        % (nombre_entrees, largeur_colonne, hauteur_colonne, taille, colonnes)
    )


def _borner(legende, largeur, hauteur):
    """Figer le cadre à la place disponible, plutôt que de le laisser courir."""
    from qgis.core import QgsLayoutSize

    if largeur <= 0 or hauteur <= 0:
        return
    legende.setResizeToContents(False)
    legende.attemptResize(QgsLayoutSize(largeur, hauteur, _MILLIMETRES))


def _cadre(item):
    """(x, y, largeur, hauteur) d'un objet de mise en page, en millimètres."""
    position, taille = item.pos(), item.rect()
    return (position.x(), position.y(), taille.width(), taille.height())


def _voisins(item):
    """Cadres des autres objets de la même page."""
    return [_cadre(autre) for autre in item.layout().items()
            if autre is not item and hasattr(autre, "pos") and hasattr(autre, "rect")
            and not isinstance(autre, QgsLayoutItemPage)]


def _page(mise):
    """(largeur, hauteur) de la première page, en millimètres."""
    collection = mise.pageCollection()
    if collection.pageCount() < 1:
        return (297.0, 210.0)  # A4 paysage, le format des gabarits ANA
    taille = collection.page(0).pageSize()
    return (taille.width(), taille.height())


def _libelles(legende):
    """Textes des entrées de la légende, pour en estimer l'encombrement."""
    textes = []

    def parcourir(noeud):
        for enfant in noeud.children():
            nom = getattr(enfant, "name", None)
            if callable(nom):
                textes.append(nom() or "")
            parcourir(enfant)

    modele = legende.model()
    parcourir(modele.rootGroup())
    # Les symboles d'une couche ne sont pas des nœuds d'arbre mais des entrées de
    # rendu : c'est là que vivent les noms d'habitats, donc l'essentiel du volume.
    for noeud in modele.rootGroup().findLayers():
        for symbole in modele.layerLegendNodes(noeud):
            textes.append(symbole.data(0) or "")
    return [t for t in textes if t]
