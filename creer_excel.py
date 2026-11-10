#!/usr/bin/env python3
"""
Transforme les fichiers CSV du projet SLA en beaux fichiers Excel (.xlsx).
Chaque fichier a son propre design, en rapport avec ce qu'il représente :
  classement_bot.csv  -> bleu nuit / cyan   (Battlefield of Time : le chrono)
  classement_gb.csv   -> rouge / or         (Boss de Guilde : le Rage Count)
  classement_poc.csv  -> violet / magenta   (POC : la Puissance de Calamité)
Pour le Boss de Guilde et le POC, chaque ligne (une vidéo) montre le score de la
1re équipe, celui de la 2e équipe et le total ; le classement se fait sur le total.
  chaines.csv         -> rouge YouTube      (les chaînes recensées)
  videos.csv          -> gris ardoise       (toutes les vidéos)
  a_revoir.csv        -> orange             (vidéos illisibles, à revoir)
  a_identifier.csv    -> turquoise          (vidéos à faire identifier)

Les couleurs de mise en valeur sont écrites directement dans les cellules (pas de
règles automatiques), pour que l'affichage soit le même dans Excel, Google Sheets,
LibreOffice ou l'aperçu d'un téléphone.

Installation (une seule fois) :   py -m pip install openpyxl
Utilisation, dans le dossier SLA :   py creer_excel.py
Les fichiers Excel sont créés dans le dossier « excel ». À relancer après
chaque lancement de sla_youtube.py. Ferme les fichiers Excel avant de relancer.
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter as L
    from openpyxl.worksheet.properties import PageSetupProperties
except ImportError:
    sys.exit("openpyxl manque. Installe-le avec :   py -m pip install openpyxl")

POLICE = "Arial"
SORTIE = Path("excel")
# lignes de la feuille
R_TITRE, R_SOUS, R_FILET, R_KPI_L, R_KPI_V, R_ENTETE, R0 = 1, 2, 3, 4, 5, 7, 8
OR, ARGENT, BRONZE = "F5C518", "C9CED6", "D08A4B"

THEMES = {
    "bot": dict(fond="0B1E3A", accent="22D3EE", entete="12355B", zebra="EAF6FB"),
    "gb": dict(fond="4A0A12", accent="F2B632", entete="8B1220", zebra="FBEDEE"),
    "poc": dict(fond="2A0F4D", accent="E879F9", entete="5B21B6", zebra="F6EEFC"),
    "chaines": dict(fond="1F1F1F", accent="FF3B3B", entete="B91C1C", zebra="F4F4F4"),
    "videos": dict(fond="1E293B", accent="38BDF8", entete="334155", zebra="F1F5F9"),
    "revoir": dict(fond="78350F", accent="FBBF24", entete="B45309", zebra="FEF3C7"),
    "identifier": dict(fond="134E4A", accent="2DD4BF", entete="0F766E", zebra="ECFDF5"),
}
COULEUR_MODE = {"poc": "5B21B6", "gb": "8B1220", "bot": "12355B"}


def fond(couleur):
    return PatternFill("solid", start_color=couleur, end_color=couleur)


def lire_csv(nom):
    if not Path(nom).exists():
        return None
    with open(nom, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def entete_csv(nom):
    """Noms des colonnes d'un CSV (liste vide si le fichier n'existe pas)."""
    if not Path(nom).exists():
        return []
    with open(nom, encoding="utf-8-sig", newline="") as f:
        return next(csv.reader(f, delimiter=";"), [])


def nombre(texte):
    try:
        return float(str(texte).replace(",", "."))
    except (TypeError, ValueError):
        return None


def valeur_cellule(cell, type_, texte, col):
    """Écrit la valeur d'une cellule selon son type, avec le bon format."""
    texte = (texte or "").strip()
    if type_ == "texte":
        cell.value = texte
    elif type_ == "rang":
        cell.value = int(nombre(texte) or 0) or None
        cell.number_format = "0"
    elif type_ == "entier":
        n = nombre(texte)
        cell.value = None if n is None else int(round(n))
        cell.number_format = "#,##0"
    elif type_ == "decimal":
        cell.value = nombre(texte)
        cell.number_format = "0.00"
    elif type_ == "degats":
        cell.value = nombre(texte)
        cell.number_format = '0.00" T"'
    elif type_ in ("chrono", "duree"):
        n = nombre(texte)
        cell.value = None if n is None else n / 86400  # temps Excel
        cell.number_format = "m:ss.000" if type_ == "chrono" else "h:mm:ss"
    elif type_ == "date":
        try:
            cell.value = datetime.strptime(texte[:10], "%Y-%m-%d")
        except ValueError:
            cell.value = texte or None
        cell.number_format = "dd/mm/yyyy"
    elif type_ == "lien":
        if texte.startswith("http"):
            cell.value = col.get("texte_lien", "Voir")
            cell.hyperlink = texte
            cell.font = Font(name=POLICE, size=10, color="1155CC", underline="single")
    cell.alignment = Alignment(horizontal=col.get("align", "left"), vertical="center")


def construire(csv_nom, xlsx_nom, theme_nom, titre, sous_titre, colonnes, kpis,
               regles=(), note=""):
    lignes = lire_csv(csv_nom)
    if lignes is None:
        print(f"  (ignoré : {csv_nom} introuvable)")
        return
    th = THEMES[theme_nom]
    nc, n = len(colonnes), len(lignes)
    last = R0 + max(n, 1) - 1
    cle_vers_lettre = {c["cle"]: L(i) for i, c in enumerate(colonnes, 1)}

    def plage(cle):
        lettre = cle_vers_lettre[cle]
        return f"${lettre}${R0}:${lettre}${last}"

    wb = Workbook()
    ws = wb.active
    ws.title = titre[:31]
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = th["accent"]

    # --- bandeau titre ---
    for r in (R_TITRE, R_SOUS, R_FILET):
        for c in range(1, nc + 1):
            ws.cell(r, c).fill = fond(th["accent"] if r == R_FILET else th["fond"])
    ws.merge_cells(start_row=R_TITRE, start_column=1, end_row=R_TITRE, end_column=nc)
    ws.merge_cells(start_row=R_SOUS, start_column=1, end_row=R_SOUS, end_column=nc)
    t = ws.cell(R_TITRE, 1, titre)
    t.font = Font(name=POLICE, size=22, bold=True, color="FFFFFF")
    t.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    s = ws.cell(R_SOUS, 1, f"{sous_titre}  ·  généré le {datetime.now():%d/%m/%Y à %H:%M}")
    s.font = Font(name=POLICE, size=10, italic=True, color=th["accent"])
    s.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[R_TITRE].height = 42
    ws.row_dimensions[R_SOUS].height = 20
    ws.row_dimensions[R_FILET].height = 4

    # --- bande de chiffres clés (formules) ---
    for r in (R_KPI_L, R_KPI_V):
        for c in range(1, nc + 1):
            ws.cell(r, c).fill = fond(th["zebra"])
    for k in kpis:
        c1, c2 = k["col"], k["col"] + k.get("span", 1) - 1
        for r in (R_KPI_L, R_KPI_V):
            if c2 > c1:
                ws.merge_cells(start_row=r, start_column=c1, end_row=r, end_column=c2)
        lab = ws.cell(R_KPI_L, c1, k["label"].upper())
        lab.font = Font(name=POLICE, size=8, bold=True, color="6B7280")
        lab.alignment = Alignment(horizontal="left", vertical="bottom", indent=1)
        formule = k["formule"]
        for cle, lettre in cle_vers_lettre.items():
            formule = formule.replace("{" + cle + "}", plage(cle))
        val = ws.cell(R_KPI_V, c1, formule if n else "—")
        val.font = Font(name=POLICE, size=16, bold=True, color=th["fond"] if theme_nom != "videos" else "1E293B")
        val.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        if k.get("format"):
            val.number_format = k["format"]
    ws.row_dimensions[R_KPI_L].height = 20
    ws.row_dimensions[R_KPI_V].height = 30
    ws.row_dimensions[R_KPI_V + 1].height = 10

    # --- en-têtes ---
    for i, col in enumerate(colonnes, 1):
        c = ws.cell(R_ENTETE, i, col["titre"])
        c.fill = fond(col.get("entete", th["entete"]))
        c.font = Font(name=POLICE, size=10, bold=True, color="FFFFFF")
        c.alignment = Alignment(horizontal=col.get("align", "left") if col.get("align") == "center" else "center",
                                vertical="center", wrap_text=True)
        c.border = Border(bottom=Side(style="medium", color=th["accent"]))
        ws.column_dimensions[L(i)].width = col["larg"]
    ws.row_dimensions[R_ENTETE].height = 30

    # --- données ---
    bord = Border(bottom=Side(style="thin", color="D9DEE5"))
    for i, ligne in enumerate(lignes):
        r = R0 + i
        ws.row_dimensions[r].height = 20
        for j, col in enumerate(colonnes, 1):
            cell = ws.cell(r, j)
            if col["type"] == "ecart_temps":
                ref = cle_vers_lettre[col["ref"]]
                cell.value = f"={ref}{r}-${ref}${R0}"
                cell.number_format = '"+"m:ss.000;"-"m:ss.000;"—"'
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col["type"] == "ecart_ratio":
                ref = cle_vers_lettre[col["ref"]]
                cell.value = f'=IF(${ref}${R0}=0,"",{ref}{r}/${ref}${R0})'
                cell.number_format = "0.0%"
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col["type"] == "barre":
                ref = cle_vers_lettre[col["ref"]]
                maxi = plage(col["ref"])
                cell.value = (f'=IF(MAX({maxi})=0,"",'
                              f'REPT("█",ROUND({ref}{r}/MAX({maxi})*20,0)))')
                cell.alignment = Alignment(horizontal="left", vertical="center")
            else:
                valeur_cellule(cell, col["type"], ligne.get(col["csv"]), col)
            if cell.font is None or cell.font.name != POLICE or col["type"] != "lien":
                cell.font = Font(name=POLICE, size=10)
            if col["type"] == "barre":
                cell.font = Font(name=POLICE, size=9, color=col["couleur"])
            cell.border = bord
            if i % 2 == 1:
                cell.fill = fond(th["zebra"])
        # mises en valeur fixes : la première règle qui correspond, par colonne
        deja_colorees = set()
        for r_ in regles:
            genre, cle = r_[0], r_[1]
            if genre not in ("contient", "egal") or cle in deja_colorees:
                continue
            j = list(cle_vers_lettre).index(cle) + 1
            texte = (ligne.get(colonnes[j - 1]["csv"]) or "").strip()
            ok = (r_[2].lower() in texte.lower()) if genre == "contient" else (texte == r_[2])
            if ok:
                cc = ws.cell(r, j)
                cc.fill = fond(r_[3])
                cc.font = Font(name=POLICE, size=10, bold=True, color=r_[4])
                deja_colorees.add(cle)
        # podium : médailles sur le rang et nom en gras pour les 3 premiers
        if i < 3 and colonnes[0]["type"] == "rang":
            cell = ws.cell(r, 1)
            cell.fill = fond([OR, ARGENT, BRONZE][i])
            cell.font = Font(name=POLICE, size=11, bold=True, color="1F2937")
            cell.alignment = Alignment(horizontal="center", vertical="center")
            nom = ws.cell(r, 2)
            nom.font = Font(name=POLICE, size=10, bold=True)

    if n == 0:
        ws.merge_cells(start_row=R0, start_column=1, end_row=R0, end_column=nc)
        m = ws.cell(R0, 1, "Aucune donnée pour le moment : lance d'abord sla_youtube.py.")
        m.font = Font(name=POLICE, size=10, italic=True, color="6B7280")
        m.alignment = Alignment(horizontal="center", vertical="center")

    # --- pied de page, filtre, volets figés, impression ---
    pied = ws.cell(last + 2, 1, f"Source : {csv_nom}. {note}".strip())
    pied.font = Font(name=POLICE, size=8, italic=True, color="6B7280")
    ws.freeze_panes = f"A{R0}"
    if n:
        ws.auto_filter.ref = f"A{R_ENTETE}:{L(nc)}{last}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = f"{R_ENTETE}:{R_ENTETE}"

    SORTIE.mkdir(exist_ok=True)
    chemin = SORTIE / xlsx_nom
    try:
        wb.save(chemin)
        print(f"  {chemin}  ({n} lignes)")
    except PermissionError:
        print(f"  ÉCHEC : {chemin} est ouvert dans Excel. Ferme-le puis relance.")


def classement(csv_nom, xlsx_nom, theme, titre, sous, colonne_valeur, type_valeur,
               titre_valeur, ecart, kpi_label, kpi_formule, kpi_format, note,
               equipes=None):
    """equipes = (colonne équipe 1, colonne équipe 2, colonne total, titre du total).
    Si le CSV contient ces colonnes, la feuille montre équipe 1, équipe 2 et total
    (classement sur le total) ; sinon, l'ancienne présentation à une seule valeur."""
    avec_equipes = bool(equipes) and equipes[2] in entete_csv(csv_nom)
    colonnes = [
        dict(cle="rang", csv="rang", titre="Rang", larg=13, type="rang", align="center"),
        dict(cle="chaine", csv="chaine", titre="Chaîne", larg=32, type="texte"),
    ]
    if avec_equipes:
        colonnes += [
            dict(cle="e1", csv=equipes[0], titre="Équipe 1", larg=17, type=type_valeur,
                 align="center"),
            dict(cle="e2", csv=equipes[1], titre="Équipe 2", larg=17, type=type_valeur,
                 align="center"),
            dict(cle="val", csv=equipes[2], titre=equipes[3], larg=18, type=type_valeur,
                 align="center"),
        ]
    else:
        colonnes.append(dict(cle="val", csv=colonne_valeur, titre=titre_valeur, larg=18,
                             type=type_valeur, align="center"))
    colonnes += [
        dict(cle="ecart", csv=None, titre="Écart avec le 1er" if ecart == "ecart_temps"
             else "% du 1er", larg=18, type=ecart, ref="val", align="center"),
        *([dict(cle="barre", csv=None, titre="Niveau", larg=24, type="barre", ref="val",
                couleur={"gb": "8B1220", "poc": "7C3AED"}[theme])]
          if ecart == "ecart_ratio" else []),
        dict(cle="src", csv="lu_dans", titre="Lu dans", larg=20, type="texte", align="center"),
        dict(cle="titre", csv="titre_video", titre="Vidéo", larg=62, type="texte"),
        dict(cle="date", csv="date", titre="Date", larg=13, type="date", align="center"),
        dict(cle="lien", csv="url", titre="Lien", larg=14, type="lien", texte_lien="▶ Voir",
             align="center"),
    ]
    col_val = [c["cle"] for c in colonnes].index("val") + 1
    kpis = [
        dict(col=2, label="Chaînes classées", formule="=COUNT({rang})", format="0"),
        dict(col=3, span=(col_val - 3) + 2, label=kpi_label, formule=kpi_formule,
             format=kpi_format),
        dict(col=[c["cle"] for c in colonnes].index("titre") + 1, label="Chaîne en tête",
             formule=f"=B{R0}"),
    ]
    regles = [("contient", "src", "claude", "FDE7C8", "92400E")]
    if avec_equipes:
        note = (note + " Équipe 1 / équipe 2 : le score de chaque équipe montrée dans la "
                "vidéo ; le classement est fait sur le total.").strip()
    construire(csv_nom, xlsx_nom, theme, titre, sous, colonnes, kpis, regles, note)


def main():
    print("Création des fichiers Excel :")
    classement("classement_bot.csv", "classement_bot.xlsx", "bot",
               "Battlefield of Time", "Classement des chaînes par chrono (le plus court gagne)",
               "chrono_s", "chrono", "Chrono (m:ss.000)", "ecart_temps",
               "Meilleur chrono", "=MIN({val})", "m:ss.000",
               "Chrono affiché en minutes:secondes.millièmes.")
    classement("classement_gb.csv", "classement_gb.xlsx", "gb",
               "Boss de Guilde", "Classement des chaînes par Rage Count (RC)",
               "rc", "entier", "Rage Count (RC)", "ecart_ratio",
               "Record de RC", "=MAX({val})", "#,##0",
               "Plus le RC est élevé, mieux c'est.",
               equipes=("rc_equipe_1", "rc_equipe_2", "rc_total", "Total RC"))
    classement("classement_poc.csv", "classement_poc.xlsx", "poc",
               "Puissance de Calamité (POC)", "Classement des chaînes par dégâts",
               "degats_T", "degats", "Dégâts (T)", "ecart_ratio",
               "Record de dégâts", "=MAX({val})", '0.00" T"',
               "T = billions de dégâts.",
               equipes=("equipe_1_T", "equipe_2_T", "total_T", "Total dégâts (T)"))

    construire(
        "chaines.csv", "chaines.xlsx", "chaines", "Chaînes recensées",
        "Chaînes classées par nombre de vidéos sur les 3 modes",
        [
            dict(cle="rang", csv="rang", titre="Rang", larg=13, type="rang", align="center"),
            dict(cle="chaine", csv="chaine", titre="Chaîne", larg=34, type="texte"),
            dict(cle="nb", csv="nb_videos", titre="Vidéos", larg=12, type="entier", align="center"),
            dict(cle="poc", csv="nb_poc", titre="POC", larg=12, type="entier", align="center",
                 entete=COULEUR_MODE["poc"]),
            dict(cle="gb", csv="nb_boss_guilde", titre="Boss de Guilde", larg=15, type="entier",
                 align="center", entete=COULEUR_MODE["gb"]),
            dict(cle="bot", csv="nb_battlefield_of_time", titre="Battlefield of Time", larg=19,
                 type="entier", align="center", entete=COULEUR_MODE["bot"]),
            dict(cle="vues", csv="vues_totales", titre="Vues totales", larg=16, type="entier",
                 align="center"),
            dict(cle="lien", csv="url_chaine", titre="Chaîne", larg=16, type="lien",
                 texte_lien="▶ Ouvrir", align="center"),
        ],
        [
            dict(col=2, label="Chaînes", formule="=COUNT({rang})", format="0"),
            dict(col=3, span=2, label="Vidéos recensées", formule="=SUM({nb})", format="#,##0"),
            dict(col=5, span=2, label="Vues cumulées", formule="=SUM({vues})", format="#,##0"),
        ],
        regles=[])

    # Boss de Guilde et POC : score de l'équipe 1, de l'équipe 2 et total (nouveau
    # format de videos.csv) ; sinon, l'ancienne colonne unique.
    ent_videos = entete_csv("videos.csv")
    if "rc_total" in ent_videos:
        COLONNES_RC = [
            dict(cle="rc1", csv="rc_equipe_1", titre="RC éq. 1", larg=11, type="entier",
                 align="center", entete=COULEUR_MODE["gb"]),
            dict(cle="rc2", csv="rc_equipe_2", titre="RC éq. 2", larg=11, type="entier",
                 align="center", entete=COULEUR_MODE["gb"]),
            dict(cle="rc", csv="rc_total", titre="RC total", larg=11, type="entier",
                 align="center", entete=COULEUR_MODE["gb"]),
        ]
        COLONNES_DEGATS = [
            dict(cle="dg1", csv="degats_equipe_1_T", titre="Dégâts éq. 1", larg=13, type="degats",
                 align="center", entete=COULEUR_MODE["poc"]),
            dict(cle="dg2", csv="degats_equipe_2_T", titre="Dégâts éq. 2", larg=13, type="degats",
                 align="center", entete=COULEUR_MODE["poc"]),
            dict(cle="degats", csv="degats_total_T", titre="Dégâts total", larg=13, type="degats",
                 align="center", entete=COULEUR_MODE["poc"]),
        ]
    else:
        COLONNES_RC = [dict(cle="rc", csv="rc", titre="RC Boss de Guilde", larg=22, type="entier",
                            align="center", entete=COULEUR_MODE["gb"])]
        COLONNES_DEGATS = [dict(cle="degats", csv="degats_T", titre="Dégâts POC", larg=13,
                                type="degats", align="center", entete=COULEUR_MODE["poc"])]

    modes_cf = [("contient", "modes", "poc", "EDE4FA", "5B21B6"),
                ("contient", "modes", "boss_guilde", "FBE4E6", "8B1220"),
                ("contient", "modes", "battlefield", "DDF1F9", "12355B")]
    construire(
        "videos.csv", "videos.xlsx", "videos", "Toutes les vidéos",
        "Vidéos de la semaine et résultats lus (titre, description ou Claude)",
        [
            dict(cle="chaine", csv="chaine", titre="Chaîne", larg=26, type="texte"),
            dict(cle="titre", csv="titre", titre="Titre", larg=58, type="texte"),
            dict(cle="date", csv="date", titre="Date", larg=13, type="date", align="center"),
            dict(cle="duree", csv="duree_s", titre="Durée", larg=10, type="duree", align="center"),
            dict(cle="vues", csv="vues", titre="Vues", larg=12, type="entier", align="center"),
            dict(cle="modes", csv="modes", titre="Modes", larg=30, type="texte"),
            dict(cle="chrono", csv="chrono_s", titre="Chrono BOT", larg=13, type="chrono",
                 align="center", entete=COULEUR_MODE["bot"]),
            *COLONNES_RC,
            *COLONNES_DEGATS,
            dict(cle="src", csv="lu_dans", titre="Lu dans", larg=20, type="texte", align="center"),
            dict(cle="lien", csv="url", titre="Lien", larg=12, type="lien", texte_lien="▶ Voir",
                 align="center"),
        ],
        [
            dict(col=1, label="Vidéos", formule="=COUNTA({chaine})", format="#,##0"),
            dict(col=2, label="Vues cumulées", formule="=SUM({vues})", format="#,##0"),
            dict(col=6, label="Résultats lus", format="0",
                 formule="=COUNT({chrono})+COUNT({rc})+COUNT({degats})"),
        ],
        regles=modes_cf + [("contient", "src", "claude", "FDE7C8", "92400E")],
        note="Chrono en minutes:secondes.millièmes ; dégâts en T (billions).")

    mode_cf = [("egal", "mode", m, c, "FFFFFF") for m, c in COULEUR_MODE.items()]
    construire(
        "a_revoir.csv", "a_revoir.xlsx", "revoir", "Vidéos à revoir",
        "Vidéos dont la miniature est illisible : à identifier en regardant la vidéo",
        [
            dict(cle="id", csv="id_video", titre="Identifiant", larg=14, type="texte"),
            dict(cle="mode", csv="mode", titre="Mode", larg=9, type="texte", align="center"),
            dict(cle="quoi", csv="quoi_chercher", titre="À chercher", larg=24, type="texte"),
            dict(cle="statut", csv="statut", titre="Statut", larg=38, type="texte"),
            dict(cle="chaine", csv="chaine", titre="Chaîne", larg=26, type="texte"),
            dict(cle="titre", csv="titre", titre="Vidéo", larg=54, type="texte"),
            dict(cle="date", csv="date", titre="Date", larg=13, type="date", align="center"),
            dict(cle="lien", csv="url", titre="Lien", larg=12, type="lien", texte_lien="▶ Voir",
                 align="center"),
            dict(cle="rem", csv="remarque_passe_precedente", titre="Remarque", larg=40,
                 type="texte"),
        ],
        [
            dict(col=1, span=2, label="Vidéos listées", formule="=COUNTA({id})", format="0"),
            dict(col=4, label="À revoir en vidéo", formule='=COUNTIF({statut},"à revoir*")',
                 format="0"),
            dict(col=5, label="Illisibles (définitif)",
                 formule='=COUNTIF({statut},"illisible*")', format="0"),
        ],
        regles=mode_cf + [("contient", "statut", "définitif", "E5E7EB", "374151"),
                          ("contient", "statut", "à revoir", "FDE68A", "92400E")])

    construire(
        "a_identifier.csv", "a_identifier.xlsx", "identifier", "Vidéos à identifier",
        "Vidéos dont la valeur n'est pas dans le titre ni la description",
        [
            dict(cle="id", csv="id_video", titre="Identifiant", larg=14, type="texte"),
            dict(cle="mode", csv="mode", titre="Mode", larg=9, type="texte", align="center"),
            dict(cle="quoi", csv="quoi_chercher", titre="À chercher", larg=24, type="texte"),
            dict(cle="chaine", csv="chaine", titre="Chaîne", larg=26, type="texte"),
            dict(cle="titre", csv="titre", titre="Vidéo", larg=54, type="texte"),
            dict(cle="date", csv="date", titre="Date", larg=13, type="date", align="center"),
            dict(cle="lien", csv="url", titre="Lien", larg=12, type="lien", texte_lien="▶ Voir",
                 align="center"),
            dict(cle="desc", csv="description_debut", titre="Début de la description", larg=70,
                 type="texte"),
        ],
        [dict(col=1, span=2, label="Vidéos à identifier", formule="=COUNTA({id})", format="0")],
        regles=mode_cf)
    print("Terminé. Ouvre le dossier « excel ».")


if __name__ == "__main__":
    main()
