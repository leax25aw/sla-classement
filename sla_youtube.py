#!/usr/bin/env python3
"""
Collecte les vidéos YouTube de Solo Leveling: ARISE sur les 3 modes
(POC = Puissance de Calamité, Boss de Guilde, Battlefield of Time),
puis classe les chaînes sur la SEMAINE EN COURS : BOT par chrono, Boss de Guilde
par Rage Count, POC par dégâts (une ligne par chaîne, sa meilleure vidéo).

La semaine commence chaque jeudi à 01h00 (heure de Paris) et dure 7 jours.
Seules les vidéos publiées pendant la semaine en cours comptent. Le jeudi à
01h00, le classement repart de zéro. Le classement de chaque semaine est
conservé dans le dossier "archives".

Utilisation (Windows) :
    set YOUTUBE_API_KEY=ta_clé
    py sla_youtube.py            # met à jour le classement de la semaine
    py sla_youtube.py --refaire  # refait la recherche depuis le début de la semaine
    py sla_youtube.py --local    # SANS YouTube (0 unité de quota) : importe les fichiers
                                 # resultats_claude*.csv et refait les classements à partir
                                 # de sla_videos.sqlite. Ne cherche pas les nouvelles vidéos :
                                 # pour cela, lancer sans --local (1 ou 2 fois par jour).

Résultats (semaine en cours) : classement_poc.csv (par dégâts), classement_bot.csv
(par chrono), classement_gb.csv (par Rage Count), chaines.csv (par nombre de
vidéos), videos.csv, archives/
Aucun appel à Claude : le script ne consomme pas ta limite.

Vidéos sans chiffre lisible : elles sont mises de côté dans a_identifier.csv
(avec leurs miniatures dans le dossier "miniatures"). Claude les identifie et
rend un fichier resultats_claude*.csv (resultats_claude.csv ou seulement un
fichier d'ajout) : à placer dans ce dossier, le script l'importe au lancement
suivant, le garde en mémoire (sla_videos.sqlite) et le range dans
resultats_importes. Inutile de redonner le fichier complet à Claude.

Vidéos illisibles sur miniature (valeur vide) : rangées à part, toutes semaines
confondues, dans a_revoir.csv, en attente d'une identification en regardant la
vidéo. Le résultat de cette 2e passe se donne dans resultats_claude.csv avec la
colonne facultative « passe » = 2 (10 s au début et à la fin). Si elle ne donne rien
(valeur vide), la vidéo passe en 3e passe : images sur TOUTE la vidéo (passe = 3).
Une valeur vide en passe 3 = illisible aussi sur toute la vidéo (définitif).
"""
import argparse
import json
import csv
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

API = "https://www.googleapis.com/youtube/v3"
KEY = os.environ.get("YOUTUBE_API_KEY")
DB = "sla_videos.sqlite"

# Remise à zéro hebdomadaire : jeudi (0 = lundi ... 3 = jeudi) à 01h00.
JOUR_RESET = 3
HEURE_RESET = 1
FUSEAU = "Europe/Paris"

# Requêtes de recherche (chaque page de résultats coûte 100 unités de quota).
QUERIES = [
    # Mode 1 : Puissance de Calamité = POC (même mode)
    "Solo Leveling Arise Puissance de Calamité",
    "SLA Puissance de Calamité",
    "Solo Leveling Arise POC",
    "SLA POC",
    "SLA Power of Calamity",
    # Mode 2 : Boss de Guilde
    "Solo Leveling Arise Boss de Guilde",
    "SLA Boss de Guilde",
    "Solo Leveling Arise guild boss",
    "SLA guild boss",
    "SLA BDG",
    # Mode 3 : Battlefield of Time
    "Solo Leveling Arise Battlefield of Time",
    "SLA Battlefield of Time",
    "SLA BOT",
]
# 3 pages x 50 vidéos par requête : 13 requêtes x 3 pages x 100 = 3900 unités
# au maximum (quota gratuit habituel : 10 000 par jour).
MAX_PAGES = 3

# 3 modes seulement. Mots-clés cherchés dans le titre, puis la description.
MODES = {
    "poc": ["puissance de calamité", "puissance de calamite",
            "power of calamity", "재앙의 권좌", "poc"],
    "boss_guilde": ["boss de guilde", "boss guilde", "guild boss", "길드 보스", "bdg"],
    "battlefield_of_time": ["battlefield of time", "battle field of time",
                            "시간의 전장", "bot"],
}

# La vidéo doit parler du jeu : "solo leveling" ou le mot "SLA".
# Quelques termes coréens/japonais du jeu sont ajoutés : certains titres
# (ex. "POC 160T / 재앙의 권좌") n'écrivent ni "Solo Leveling" ni "SLA".
MOTS_JEU = [r"solo leveling", r"\bsla\b", r"나혼렙", r"나\s?혼자만\s?레벨업",
            r"俺アラ", r"俺だけレベルアップ", r"재앙의 권좌", r"시간의 전장"]


class LimiteAPI(Exception):
    """YouTube refuse de répondre (trop de requêtes ou quota du jour atteint)."""


ATTENTES = [30, 90, 180]  # secondes d'attente avant de réessayer après une erreur 429
PAUSE_RECHERCHE = 3  # secondes entre deux recherches (évite l'erreur 429)


def appel(endpoint, params):
    params = {**params, "key": KEY}
    for essai in range(len(ATTENTES) + 1):
        r = requests.get(f"{API}/{endpoint}", params=params, timeout=30)
        if r.status_code == 403 and "quota" in r.text.lower():
            raise LimiteAPI("quota YouTube épuisé pour aujourd'hui")
        if r.status_code == 429:
            if essai < len(ATTENTES):
                print(f"YouTube demande de ralentir (erreur 429). "
                      f"Pause de {ATTENTES[essai]} secondes, puis nouvel essai...")
                time.sleep(ATTENTES[essai])
                continue
            raise LimiteAPI("YouTube refuse trop de requêtes (erreur 429)")
        r.raise_for_status()
        return r.json()


def init_db():
    db = sqlite3.connect(DB)
    db.execute(
        """CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY, channel_id TEXT, channel TEXT, title TEXT,
            description TEXT, published TEXT, duration_s INTEGER,
            views INTEGER, modes TEXT)"""
    )
    db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    # Valeurs identifiées par Claude pour les vidéos sans chiffre lisible
    # (valeur vide = Claude a regardé mais n'a rien pu lire).
    db.execute(
        """CREATE TABLE IF NOT EXISTS valeurs_claude (
            video_id TEXT, mode TEXT, valeur REAL, remarque TEXT,
            PRIMARY KEY (video_id, mode))"""
    )
    # passe : 1 = identification sur miniature, 2 = identification en regardant
    # la vidéo. Migration silencieuse des anciennes bases.
    colonnes = [c[1] for c in db.execute("PRAGMA table_info(valeurs_claude)")]
    if "passe" not in colonnes:
        db.execute("ALTER TABLE valeurs_claude ADD COLUMN passe INTEGER DEFAULT 1")
        db.commit()
    # valeur = 1re équipe de la vidéo ; valeur2 = 2e équipe ; total = leur somme.
    # degats = dégâts totaux en T (Boss de Guilde) : sert à départager deux chaînes
    # à égalité de Rage Count.
    # Migration silencieuse des anciennes bases.
    for col in ("valeur2", "total", "degats"):
        if col not in colonnes:
            db.execute(f"ALTER TABLE valeurs_claude ADD COLUMN {col} REAL")
    # element1 / element2 = élément de l'équipe 1 / 2 (feu, vent, eau, lumiere, tenebres),
    # affiché dans les colonnes « Équipe (élément) » de la page web.
    for col in ("element1", "element2"):
        if col not in colonnes:
            db.execute(f"ALTER TABLE valeurs_claude ADD COLUMN {col} TEXT")
    db.commit()
    return db


def duree_secondes(iso):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def modes_dans(texte):
    """Liste des modes dont un mot-clé apparaît dans le texte."""
    texte = texte.lower()
    trouves = []
    for mode, mots in MODES.items():
        for mot in mots:
            # mots courts (poc, bdg, bot) : mot entier uniquement
            motif = rf"\b{re.escape(mot)}\b" if len(mot) <= 4 else re.escape(mot)
            if re.search(motif, texte):
                trouves.append(mode)
                break
    return trouves


def detecter_modes(titre, description):
    """Le TITRE décide en priorité. La description n'est utilisée que si le
    titre ne contient aucun mode, et seulement si elle n'en cite qu'un seul
    (une description qui liste tous les modes est ignorée : trop vague)."""
    complet = (titre + " " + description).lower()
    if not any(re.search(m, complet) for m in MOTS_JEU):
        return ""
    dans_titre = modes_dans(titre)
    if dans_titre:
        return ",".join(dans_titre)
    dans_desc = modes_dans(description)
    if len(dans_desc) == 1:
        return dans_desc[0]
    return ""


def maintenant_local():
    """Heure actuelle à Paris. Si le fuseau n'est pas disponible sur
    l'ordinateur, on utilise l'heure de l'ordinateur."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(FUSEAU))
    except Exception:
        return datetime.now().astimezone()


def debut_semaine(now):
    """Dernier jeudi 01h00 (heure locale) avant 'now'."""
    jours = (now.weekday() - JOUR_RESET) % 7
    debut = (now - timedelta(days=jours)).replace(
        hour=HEURE_RESET, minute=0, second=0, microsecond=0)
    if debut > now:  # jeudi avant 01h00 : on est encore dans la semaine d'avant
        debut -= timedelta(days=7)
    return debut


def iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def chercher(since, ids, db, refaire=False):
    """Remplit 'ids' au fur et à mesure. Chaque recherche terminée est
    enregistrée : si YouTube bloque en cours de route, le lancement suivant
    saute les recherches déjà faites et reprend à celle qui a échoué."""
    cle = f"done:{since}"
    if refaire:
        db.execute("DELETE FROM meta WHERE k LIKE 'done:%'")
        db.commit()
    ligne = db.execute("SELECT v FROM meta WHERE k=?", (cle,)).fetchone()
    faites = set(json.loads(ligne[0])) if ligne else set()
    if faites:
        print(f"{len(faites)} recherche(s) déjà terminée(s) lors du lancement précédent : on les saute.")
    for n, q in enumerate(QUERIES, 1):
        if q in faites:
            continue
        print(f"Recherche {n}/{len(QUERIES)} : {q}")
        token = None
        for _ in range(MAX_PAGES):
            params = {
                "part": "id", "q": q, "type": "video", "order": "date",
                "maxResults": 50, "publishedAfter": since,
            }
            if token:
                params["pageToken"] = token
            data = appel("search", params)
            time.sleep(PAUSE_RECHERCHE)  # pause entre deux recherches
            ids.update(i["id"]["videoId"] for i in data.get("items", []))
            token = data.get("nextPageToken")
            if not token:
                break
        faites.add(q)
        db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                   (cle, json.dumps(sorted(faites))))
        db.commit()


def details(db, ids):
    deja = {r[0] for r in db.execute("SELECT id FROM videos")}
    nouveaux = sorted(ids - deja)  # une vidéo n'est analysée qu'une seule fois
    for i in range(0, len(nouveaux), 50):
        lot = nouveaux[i : i + 50]
        data = appel("videos", {
            "part": "snippet,contentDetails,statistics", "id": ",".join(lot),
        })
        for v in data.get("items", []):
            s = v["snippet"]
            modes = detecter_modes(s["title"], s.get("description", ""))
            db.execute(
                "INSERT OR REPLACE INTO videos VALUES (?,?,?,?,?,?,?,?,?)",
                (v["id"], s["channelId"], s["channelTitle"], s["title"],
                 s.get("description", ""), s["publishedAt"],
                 duree_secondes(v["contentDetails"]["duration"]),
                 int(v["statistics"].get("viewCount", 0)), modes),
            )
        db.commit()
    return len(nouveaux)


def recalculer_modes(db):
    """Réapplique la détection à toutes les vidéos déjà en cache (local,
    gratuit) : les anciennes vidéos profitent des règles à jour."""
    for vid, titre, desc in db.execute(
        "SELECT id, title, description FROM videos"
    ).fetchall():
        db.execute("UPDATE videos SET modes=? WHERE id=?",
                   (detecter_modes(titre or "", desc or ""), vid))
    db.commit()


def rafraichir_vues(db, debut_utc, fin_utc):
    """Met à jour les vues des vidéos retenues de la semaine en cours
    (1 unité de quota pour 50 vidéos)."""
    ids = [r[0] for r in db.execute(
        "SELECT id FROM videos WHERE modes != '' "
        "AND published >= ? AND published < ?", (debut_utc, fin_utc))]
    for i in range(0, len(ids), 50):
        lot = ids[i : i + 50]
        data = appel("videos", {"part": "statistics", "id": ",".join(lot)})
        for v in data.get("items", []):
            db.execute("UPDATE videos SET views=? WHERE id=?",
                       (int(v["statistics"].get("viewCount", 0)), v["id"]))
    db.commit()


# ----- Lecture des chiffres : d'abord le TITRE, puis la DESCRIPTION -----
# Les descriptions contiennent beaucoup de chiffres sans rapport (horodatages,
# abonnés, liens...). On y est donc plus strict : unité obligatoire et mot du
# jeu à proximité.
SAISON = r"(?i)(season|saison|시즌|シーズン|\bs)\s*-?\s*\d+(?:-\d+)?"
CTX_BOT = re.compile(r"(?i)\b(?:tarr?|bot|chrono|clear|battlefield|battle field)\b"
                     r"|타르|タール|시간의 전장|時の戦場")
CTX_POC = re.compile(r"(?i)\b(?:poc|damage|dmg|d[ée]g[âa]ts|total)\b"
                     r"|재앙|데미지|피해|ダメージ")
UNITES_DEGATS = {"t": 1e12, "조": 1e12, "兆": 1e12,   # trillion
                 "b": 1e9, "억": 1e8, "億": 1e8, "m": 1e6}


def autour(texte, m, rayon=60):
    return texte[max(0, m.start() - rayon): m.end() + rayon]


def extraire_chrono(titre):
    """Chrono du BOT en secondes, lu dans le TITRE (ex. 'Tarr 29.219s' ->
    29.219, 'Tarr 33초' -> 33). None si introuvable."""
    t = re.sub(SAISON, " ", titre)
    m = re.search(r"(?<![\d.,;A-Za-z])(\d{2,3}(?:[.,;]\d{1,3})?)\s*(?:s\b|sec|秒|초|🕒)", t, re.I)
    if not m:  # sans unité : un nombre à virgule (ex. '29.224 タール')
        m = re.search(r"(?<![\w.,])(\d{2}[.,]\d{1,3})(?![\w%])", t)
    if not m:
        return None
    v = float(m.group(1).replace(",", ".").replace(";", "."))
    return v if 10 <= v <= 180 else None


def chrono_description(desc):
    """Chrono du BOT dans la DESCRIPTION : unité obligatoire (s, sec, 초, 秒)
    et un mot du mode (Tarr, BOT, chrono...) à proximité."""
    t = re.sub(SAISON, " ", desc)
    for m in re.finditer(r"(?<![\d.,:;A-Za-z])(\d{2,3}(?:[.,;]\d{1,3})?)\s*(?:s\b|sec|秒|초)(?![\w:])", t, re.I):
        v = float(m.group(1).replace(",", ".").replace(";", "."))
        if 10 <= v <= 180 and CTX_BOT.search(autour(t, m)):
            return v
    return None


def _rc_etiquete(texte):
    m = re.search(r"(?<![\w.])(\d{2,3})\s*(?:rc\b|rage count|iras\b)", texte, re.I)
    if not m:
        m = re.search(r"\b(?:rc|rage count)\s*[:=]?\s*(\d{2,3})\b", texte, re.I)
    if m and 50 <= int(m.group(1)) <= 500:
        return int(m.group(1))
    return None


def rc_deux_equipes(texte):
    """'174 + 178 RC' ou '174+178 Rage Count' : renvoie (equipe_1, equipe_2),
    sinon None. Sans cela, seul le dernier nombre serait lu (178 au lieu de 352)."""
    m = re.search(r"(?<![\w.])(\d{2,3})\s*\+\s*(\d{2,3})\s*(?:rc\b|rage count|iras\b)",
                  texte, re.I)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 20 <= a <= 300 and 20 <= b <= 300:
            return a, b
    return None


def extraire_rc(titre):
    """Rage Count du Boss de Guilde, lu dans le TITRE ('184 RC', '171RC',
    '171 IRAS' en espagnol...). Renvoie (valeur, source) ou None.
    Dernier recours : un nombre derrière un élément ('WIND 180!'), signalé
    'titre sans RC écrit' car moins sûr."""
    v = _rc_etiquete(titre)
    if v is not None:
        return v, "titre"
    m = re.search(r"(?i)\b(?:wind|fire|water|light|dark|vent|feu|eau)\s*(\d{3})(?![\d%.])", titre)
    if m and 100 <= int(m.group(1)) <= 300:
        return int(m.group(1)), "titre sans RC écrit"
    return None


def rc_description(desc):
    """Rage Count dans la DESCRIPTION : seulement s'il est écrit 'RC'."""
    return _rc_etiquete(desc)


def extraire_degats(texte, strict=False):
    """Dégâts du POC en billions (T = 10^12) : '160T' -> 160.0, '160조' -> 160.0,
    '2.5B' -> 0.0025. S'il y a plusieurs nombres, on garde le plus grand.
    strict=True (descriptions) : seulement T/조/兆/억 (pas B ni M, trop courants
    pour des abonnés ou des vues) et un mot comme POC/damage/total à proximité."""
    t = re.sub(SAISON, " ", texte)
    unites = r"조|兆|억|億|[Tt]" if strict else r"조|兆|억|億|[TtBbMm]"
    valeurs = []
    for m in re.finditer(rf"(?<![\w.,:])(\d+(?:[.,]\d+)?)\s*({unites})(?![A-Za-z])", t):
        if strict and not CTX_POC.search(autour(t, m)):
            continue
        nombre = float(m.group(1).replace(",", "."))
        valeurs.append(nombre * UNITES_DEGATS[m.group(2).lower()] / 1e12)
    return max(valeurs) if valeurs else None


def ecrire_csv(chemin, entete, lignes):
    # utf-8-sig : Excel affiche correctement les noms coréens, accents, etc.
    # delimiter=";" : l'Excel français sépare les colonnes avec des points-virgules.
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(entete)
        w.writerows(lignes)


def somme(e1, e2):
    return None if e1 is None and e2 is None else (e1 or 0) + (e2 or 0)


ELEMENTS = {
    "feu": r"(?i)\b(?:fire|feu)\b|🔥",
    "vent": r"(?i)\b(?:wind|vent)\b|🍃|🌪",
    "eau": r"(?i)\b(?:water|eau)\b|💧",
    "lumiere": r"(?i)\b(?:light|lumi[èe]re)\b",
    "tenebres": r"(?i)\b(?:dark|t[ée]n[èe]bres)\b",
}


def nombre_de_rc(titre):
    """Combien de RC différents le titre écrit-il (ex. « 150 RC ... 160 RC » : 2) ?"""
    nombres = set(re.findall(r"(?i)(?<![\w.])(\d{2,3})\s*(?:rc\b|rage count|iras\b)", titre))
    nombres |= set(re.findall(r"(?i)\b(?:rc|rage count)\s*[:=]?\s*(\d{2,3})\b", titre))
    return len({n for n in nombres if 50 <= int(n) <= 500})


def deux_elements(titre):
    """Vrai si le titre cite au moins deux éléments (ex. « Fire - Wind - RC: 348 ») et
    un seul RC. Ce chiffre est alors le total des deux équipes, pas le RC d'une seule
    run : on ne le met pas en équipe 1. Avec deux RC dans le titre, rien ne change."""
    return (sum(1 for motif in ELEMENTS.values() if re.search(motif, titre)) >= 2
            and nombre_de_rc(titre) == 1)


def lire_valeurs(titre, desc, liste, vid=None, claude=None):
    """Valeurs de chaque mode pour une vidéo. Renvoie un dict
    {mode: (equipe_1, equipe_2, total, source)} avec source = titre /
    description / claude. Le BOT n'a qu'une valeur (equipe_2 vide, total = chrono).
    Pour le POC et le Boss de Guilde, un nombre lu dans un titre ou une
    description est le score d'UNE équipe, sauf si le mot « total » l'accompagne
    (POC) : il compte alors comme le total, sans détail par équipe.
    Les valeurs lues par Claude (miniature ou images de la vidéo) passent AVANT le titre
    et la description : elles viennent de l'écran du jeu, donc plus précises (par exemple
    32,833 s au lieu de « 32 s » écrit dans une description)."""
    out = {}
    for cle in ("bot", "gb", "poc"):
        if claude and (vid, cle) in claude:
            e1, e2, tot = claude[(vid, cle)]
            if tot is None:
                tot = somme(e1, e2)
            out[cle] = (e1, e2, tot, "claude")
    if "battlefield_of_time" in liste and "bot" not in out:
        v = extraire_chrono(titre)
        if v is not None:
            out["bot"] = (v, None, v, "titre")
        else:
            v = chrono_description(desc)
            if v is not None:
                out["bot"] = (v, None, v, "description")
    if "boss_guilde" in liste and "gb" not in out:
        r = extraire_rc(titre)
        deux = rc_deux_equipes(titre) or rc_deux_equipes(desc)
        if deux:
            out["gb"] = (deux[0], deux[1], deux[0] + deux[1],
                         "titre" if rc_deux_equipes(titre) else "description")
        elif r is not None:
            if deux_elements(titre):  # ex. « Fire - Wind - RC: 348 » : total des deux équipes
                out["gb"] = (None, None, r[0], r[1])
            else:
                out["gb"] = (r[0], None, r[0], r[1])
        else:
            v = rc_description(desc)
            if v is not None:
                out["gb"] = (v, None, v, "description")
    if "poc" in liste and "poc" not in out:
        for texte, strict, src in ((titre, False, "titre"), (desc, True, "description")):
            v = extraire_degats(texte, strict=strict)
            if v is not None:
                if re.search(r"(?i)\btotal\b", texte):
                    out["poc"] = (None, None, v, src)
                else:
                    out["poc"] = (v, None, v, src)
                break
    return out


ELEMENTS_NOMS = {"feu": "feu", "fire": "feu", "vent": "vent", "wind": "vent",
                 "eau": "eau", "water": "eau", "lumiere": "lumiere", "lumière": "lumiere",
                 "light": "lumiere", "tenebres": "tenebres", "ténèbres": "tenebres",
                 "dark": "tenebres"}


def element_normalise(texte):
    """feu / vent / eau / lumiere / tenebres (ou vide si non reconnu)."""
    return ELEMENTS_NOMS.get((texte or "").strip().lower(), "")


def importer_fichier_claude(db, chemin):
    """Lit un fichier de résultats de Claude (colonnes : id_video;mode;valeur;remarque),
    rempli par Claude, et l'ajoute à la mémoire du script. Sans effet si le
    fichier n'existe pas. mode = bot, gb ou poc ; valeur vide = illisible.
    Colonnes facultatives :
      valeur2 : score de la 2e équipe, si la vidéo en montre deux (POC, Boss de Guilde)
      total   : total des deux équipes (sinon calculé : valeur + valeur2)
      passe   : 1 = miniature (défaut), 2 = vidéo regardée (début et fin),
                3 = vidéo regardée en entier (--toute ; valeur vide = définitif).
      degats  : dégâts totaux en T (Boss de Guilde), pour départager des égalités de RC.
      element1, element2 : élément de l'équipe 1 et de l'équipe 2 (feu, vent, eau, lumiere,
                tenebres ; fire, wind... acceptés), pour la page web."""
    if not os.path.exists(chemin):
        return 0
    with open(chemin, newline="", encoding="utf-8-sig") as f:
        contenu = f.read()
    delim = ";" if contenu.splitlines()[0].count(";") >= 2 else ","
    n = 0
    for r in csv.DictReader(contenu.splitlines(), delimiter=delim):
        vid, mode = (r.get("id_video") or "").strip(), (r.get("mode") or "").strip().lower()
        if not vid or mode not in ("bot", "gb", "poc"):
            continue
        def nombre(cle):
            brut = (r.get(cle) or "").strip().replace(",", ".")
            try:
                return float(brut) if brut else None
            except ValueError:
                return None
        valeur, valeur2, total = nombre("valeur"), nombre("valeur2"), nombre("total")
        degats = nombre("degats")
        element1, element2 = element_normalise(r.get("element1")), element_normalise(r.get("element2"))
        if total is None and (valeur is not None or valeur2 is not None):
            total = somme(valeur, valeur2)
        try:
            passe = min(3, max(1, int((r.get("passe") or 1))))
        except ValueError:
            passe = 1
        ancien = db.execute("SELECT passe, degats, valeur, total, element1, element2 "
                            "FROM valeurs_claude WHERE video_id=? AND mode=?", (vid, mode)).fetchone()
        if degats is None and ancien:
            degats = ancien[1]  # une ligne sans dégâts n'efface pas ceux déjà connus
        if ancien:  # une ligne sans élément n'efface pas ceux déjà connus
            element1, element2 = element1 or ancien[4] or "", element2 or ancien[5] or ""
        # Une lecture d'une passe plus ancienne n'écrase pas une passe plus récente. Seule
        # exception : une valeur lue peut remplacer une ancienne lecture restée vide.
        if ancien and (ancien[0] or 1) > passe:
            ancien_vide = ancien[2] is None and ancien[3] is None
            ligne_vide = valeur is None and total is None
            if ligne_vide or not ancien_vide:
                print(f"  {vid} ({mode}) : ligne de la passe {passe} ignorée, "
                      f"la lecture de la passe {ancien[0] or 1} est gardée.")
                continue
        db.execute("INSERT OR REPLACE INTO valeurs_claude "
                   "(video_id, mode, valeur, remarque, passe, valeur2, total, degats, "
                   "element1, element2) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (vid, mode, valeur, (r.get("remarque") or "").strip(), passe,
                    valeur2, total, degats, element1, element2))
        n += 1
    db.commit()
    return n


def importer_resultats_claude(db, dossier="."):
    """Importe TOUS les fichiers resultats_claude*.csv du dossier (par ex.
    resultats_claude.csv, resultats_claude_ajout.csv), du plus ancien au plus
    récent : en cas de doublon, le plus récent l'emporte. Les valeurs sont
    gardées dans sla_videos.sqlite : il n'est donc plus nécessaire de
    redonner le fichier complet à Claude, un fichier d'ajout (seulement les
    nouvelles lignes) suffit. Chaque fichier importé est rangé ensuite dans le
    dossier resultats_importes (copie de sauvegarde, jamais réimporté)."""
    fichiers = sorted(
        (f for f in os.listdir(dossier)
         if re.fullmatch(r"resultats_claude.*\.csv", f, re.IGNORECASE)),
        key=lambda f: os.path.getmtime(os.path.join(dossier, f)))
    total = 0
    for nom in fichiers:
        chemin = os.path.join(dossier, nom)
        n = importer_fichier_claude(db, chemin)
        total += n
        try:
            rangement = os.path.join(dossier, "resultats_importes")
            os.makedirs(rangement, exist_ok=True)
            horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.move(chemin, os.path.join(rangement, f"{horodatage}_{nom}"))
        except OSError as e:
            print(f"Import de {nom} fait, mais impossible de le ranger : {e}")
        print(f"{nom} : {n} lignes importées")
    return total


def exporter_a_revoir(db, chemin="a_revoir.csv"):
    """Range à part, dans a_revoir.csv, toutes les vidéos que la miniature n'a
    pas permis d'identifier (toutes semaines confondues, rien n'est effacé).
    Elles attendent une identification en regardant la vidéo (passe 2), puis, si les
    10 s du début et de la fin n'ont rien donné, sur TOUTE la vidéo (passe 3).
    Une vidéo en sort dès qu'une valeur est donnée dans resultats_claude.csv ;
    si la passe 3 ne donne rien non plus, elle reste listée comme définitive."""
    quoi = {"bot": "chrono en secondes",
            "gb": "Rage Count (RC) : équipe 1, équipe 2 si les deux, total",
            "poc": "dégâts en T (billions) : équipe 1, équipe 2 si les deux, total"}
    lignes = []
    for vid, mode, passe, chaine, titre, pub, rem in db.execute(
            "SELECT v.video_id, v.mode, v.passe, i.channel, i.title, i.published, "
            "v.remarque FROM valeurs_claude v JOIN videos i ON i.id = v.video_id "
            "WHERE v.valeur IS NULL AND v.total IS NULL "
            "ORDER BY v.passe, i.published DESC"):
        if (passe or 1) < 2:
            statut = "à revoir en regardant la vidéo"
        elif passe == 2:
            statut = "à revoir sur toute la vidéo"
        else:
            statut = "illisible aussi sur toute la vidéo (définitif)"
        lignes.append([vid, mode, quoi.get(mode, ""), statut, chaine, titre, pub,
                       f"https://www.youtube.com/watch?v={vid}", rem or ""])
    ecrire_csv(chemin, ["id_video", "mode", "quoi_chercher", "statut", "chaine",
                        "titre", "date", "url", "remarque_passe_precedente"], lignes)
    return sum(1 for l in lignes if l[3].startswith("à revoir")), len(lignes)


def telecharger_miniatures(ids, dossier="miniatures"):
    """Télécharge la miniature de chaque vidéo (sans quota YouTube) : elle
    affiche souvent le résultat, que Claude peut lire."""
    os.makedirs(dossier, exist_ok=True)
    for vid in ids:
        chemin = os.path.join(dossier, f"{vid}.jpg")
        if os.path.exists(chemin):
            continue
        try:
            r = requests.get(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", timeout=15)
            if r.status_code == 200:
                with open(chemin, "wb") as f:
                    f.write(r.content)
        except requests.RequestException:
            pass


def fm(cle, v):
    """Affichage d'un score : vide si absent ; RC en nombre entier ; dégâts en T
    arrondis à 3 décimales ; chrono tel quel."""
    if v is None:
        return ""
    if cle == "gb":
        return int(round(v))
    if cle == "poc":
        return round(v, 3)
    return v


def exporter(db, debut_utc, fin_utc, jour):
    """Écrit les fichiers de la semaine en cours + une copie dans archives/.
    'jour' = date du jeudi de début de semaine (ex. 2026-11-05)."""
    rows = db.execute(
        "SELECT id,channel_id,channel,title,description,published,duration_s,"
        "views,modes FROM videos WHERE modes != '' AND published >= ? "
        "AND published < ? ORDER BY published DESC", (debut_utc, fin_utc)
    ).fetchall()

    claude = {(v, m): (e1, e2, tot) for v, m, e1, e2, tot in db.execute(
        "SELECT video_id, mode, valeur, valeur2, total FROM valeurs_claude "
        "WHERE valeur IS NOT NULL OR total IS NOT NULL")}
    # Dégâts totaux connus (Boss de Guilde) : départagent les égalités de RC.
    degats_gb = {v: d for v, d in db.execute(
        "SELECT video_id, degats FROM valeurs_claude "
        "WHERE mode='gb' AND degats IS NOT NULL")}
    # Éléments des équipes (page web : colonnes « Équipe (vent) », « Équipe (feu) »...).
    elements = {(v, m): (e1 or "", e2 or "") for v, m, e1, e2 in db.execute(
        "SELECT video_id, mode, element1, element2 FROM valeurs_claude")}
    traites = {(v, m) for v, m in db.execute(
        "SELECT video_id, mode FROM valeurs_claude")}
    a_identifier = []
    quoi = {"bot": "chrono en secondes",
            "gb": "Rage Count (RC) : équipe 1, équipe 2 si les deux, total",
            "poc": "dégâts en T (billions) : équipe 1, équipe 2 si les deux, total"}
    videos, best = [], {"bot": {}, "gb": {}, "poc": {}}
    manque = {"bot": 0, "gb": 0, "poc": 0}
    mode_de = {"bot": "battlefield_of_time", "gb": "boss_guilde", "poc": "poc"}
    for vid, cid, chaine, titre, desc, pub, duree, vues, modes in rows:
        liste = modes.split(",")
        url = f"https://www.youtube.com/watch?v={vid}"
        vals = lire_valeurs(titre, desc or "", liste, vid, claude)
        for cle, mode in mode_de.items():
            if mode in liste and cle not in vals:
                manque[cle] += 1
                if (vid, cle) not in traites:  # pas encore regardée par Claude
                    a_identifier.append([vid, cle, quoi[cle], chaine, titre, pub,
                                         url, " ".join((desc or "").split())[:300]])
        for cle, (e1, e2, tot, src) in vals.items():
            if tot is None:
                continue
            # BOT : plus petit = meilleur ; GB et POC : plus grand total = meilleur
            # À égalité de RC : plus de dégâts d'abord, puis la vidéo publiée en premier.
            clef = (tot, 0) if cle == "bot" else (-tot, -(degats_gb.get(vid) or 0) if cle == "gb" else 0)
            actuel = best[cle].get(cid)
            if actuel is None or (clef, pub) < (actuel[0], actuel[1]):
                best[cle][cid] = (clef, pub, e1, e2, tot, chaine, titre, url, src)
        def v(cle, i):
            return fm(cle, vals[cle][i]) if cle in vals else ""
        videos.append([chaine, titre, pub, duree, vues, modes,
                       v("bot", 2),
                       v("gb", 0), v("gb", 1), v("gb", 2),
                       v("poc", 0), v("poc", 1), v("poc", 2),
                       " / ".join(x[3] for x in vals.values()), url])
    ecrire_csv("videos.csv",
               ["chaine", "titre", "date", "duree_s", "vues", "modes", "chrono_s",
                "rc_equipe_1", "rc_equipe_2", "rc_total",
                "degats_equipe_1_T", "degats_equipe_2_T", "degats_total_T",
                "lu_dans", "url"], videos)
    ecrire_csv("a_identifier.csv",
               ["id_video", "mode", "quoi_chercher", "chaine", "titre", "date",
                "url", "description_debut"], a_identifier)

    def classement(cle, fichier, colonnes, avec_degats=False):
        """BOT : une colonne (chrono). POC et Boss de Guilde : la même ligne
        donne la vidéo, le score de la 1re équipe, celui de la 2e et le total ;
        le classement est fait sur le total."""
        lignes = sorted(best[cle].values(), key=lambda x: (x[0], x[1]))
        sortie = []
        for i, (_, d, e1, e2, tot, c, t, u, src) in enumerate(lignes, 1):
            scores = [fm(cle, tot)] if cle == "bot" else [fm(cle, e1), fm(cle, e2), fm(cle, tot)]
            if cle != "bot":  # éléments des équipes (seulement si lus par Claude), dégâts GB
                vid = u.split("v=")[-1]
                e = elements.get((vid, cle), ("", "")) if src == "claude" else ("", "")
                scores += [e[0], e[1]]
                if avec_degats:
                    dg = degats_gb.get(vid) if src == "claude" else None
                    scores.append(round(dg, 3) if dg is not None else "")
            sortie.append([i, c, *scores, src, t, d, u])
        extra = [] if cle == "bot" else ["element_equipe_1", "element_equipe_2"]
        if avec_degats:
            extra.append("degats_total_T")
        ecrire_csv(fichier, ["rang", "chaine", *colonnes, *extra, "lu_dans", "titre_video",
                             "date", "url"], sortie)
        return len(lignes)

    n_poc = classement("poc", "classement_poc.csv",
                       ["equipe_1_T", "equipe_2_T", "total_T"])
    n_bot = classement("bot", "classement_bot.csv", ["chrono_s"])
    n_gb = classement("gb", "classement_gb.csv",
                      ["rc_equipe_1", "rc_equipe_2", "rc_total"], avec_degats=True)

    # --- classement des chaînes par nombre de vidéos (à égalité : plus de vues) ---
    lignes = db.execute(
        """SELECT channel, COUNT(*),
                  SUM(modes LIKE '%poc%'),
                  SUM(modes LIKE '%boss_guilde%'),
                  SUM(modes LIKE '%battlefield_of_time%'),
                  SUM(views), channel_id
           FROM videos WHERE modes != '' AND published >= ? AND published < ?
           GROUP BY channel_id
           ORDER BY COUNT(*) DESC, SUM(views) DESC""", (debut_utc, fin_utc)
    ).fetchall()
    ecrire_csv("chaines.csv",
               ["rang", "chaine", "nb_videos", "nb_poc", "nb_boss_guilde",
                "nb_battlefield_of_time", "vues_totales", "url_chaine"],
               [[i, *r[:6], f"https://www.youtube.com/channel/{r[6]}"]
                for i, r in enumerate(lignes, 1)])

    # Copie de la semaine : écrasée à chaque lancement de la semaine, donc la
    # dernière version reste en archive quand la semaine suivante commence.
    os.makedirs("archives", exist_ok=True)
    for nom in ("chaines", "videos", "classement_poc", "classement_bot",
                "classement_gb"):
        shutil.copyfile(f"{nom}.csv", f"archives/{nom}_{jour}.csv")
    return (n_poc, manque["poc"], n_bot, manque["bot"], n_gb, manque["gb"],
            a_identifier)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refaire", action="store_true",
                        help="refait la recherche depuis le début de la semaine")
    parser.add_argument("--local", action="store_true",
                        help="n'appelle pas YouTube (0 unité de quota) : importe les fichiers "
                             "resultats_claude*.csv et refait les classements")
    args = parser.parse_args()
    if args.local and args.refaire:
        parser.error("--local et --refaire ne vont pas ensemble (--refaire relance la recherche).")
    if not KEY and not args.local:
        sys.exit("Définis la variable d'environnement YOUTUBE_API_KEY "
                 "(ou lance avec --local pour ne pas appeler YouTube).")

    db = init_db()
    now = maintenant_local()
    debut = debut_semaine(now)
    fin = debut + timedelta(days=7)
    debut_utc, fin_utc = iso_utc(debut), iso_utc(fin)

    # On cherche depuis le dernier lancement (moins 1 jour de marge), mais
    # jamais avant le début de la semaine en cours.
    derniere = db.execute("SELECT v FROM meta WHERE k='last_run'").fetchone()
    since_dt = debut
    if derniere and not args.refaire:
        since_dt = max(debut, datetime.fromisoformat(derniere[0]) - timedelta(days=1))
    since = iso_utc(since_dt)

    ids, nb, complet = set(), 0, True
    if args.local:
        # Aucun appel à YouTube : on travaille sur ce qui est déjà dans sla_videos.sqlite.
        if db.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0:
            sys.exit("sla_videos.sqlite ne contient encore aucune vidéo : lance d'abord "
                     "py sla_youtube.py (sans --local).")
        print("Mode local : YouTube n'est pas appelé (0 unité de quota). Les nouvelles vidéos "
              "ne sont pas cherchées : lance py sla_youtube.py (sans --local) pour cela.")
        if not derniere or datetime.fromisoformat(derniere[0]) < debut:
            print("ATTENTION : aucun lancement complet depuis le début de cette semaine "
                  f"({debut:%d/%m/%Y %Hh%M}) : les classements restent vides ou incomplets "
                  "tant que py sla_youtube.py n'a pas été lancé sans --local.")
        recalculer_modes(db)
        complet = False  # pas de recherche faite : on ne touche pas à la date du dernier lancement
    else:
        try:
            chercher(since, ids, db, args.refaire)
        except LimiteAPI as e:
            complet = False
            print(f"\nATTENTION : {e}. La recherche s'arrête ici ({len(ids)} vidéos trouvées).")
        try:
            nb = details(db, ids)
        except LimiteAPI as e:
            complet = False
            print(f"\nATTENTION : {e}. Les détails de certaines vidéos manquent.")
        recalculer_modes(db)
        try:
            rafraichir_vues(db, debut_utc, fin_utc)
        except LimiteAPI:
            print("Les vues n'ont pas pu être mises à jour cette fois.")
    if args.local:
        pass
    elif complet:
        db.execute("INSERT OR REPLACE INTO meta VALUES ('last_run', ?)",
                   (datetime.now(timezone.utc).isoformat(),))
        db.execute("DELETE FROM meta WHERE k LIKE 'done:%'")
        db.commit()
    else:
        print("Relancez le script plus tard (dans 1 heure, ou demain si le quota est atteint) :\n"
              "il sautera les recherches déjà terminées et reprendra à celle qui a échoué.")
    importes = importer_resultats_claude(db)
    n_poc, sans_degats, n_bot, sans_chrono, n_gb, sans_rc, a_identifier = exporter(
        db, debut_utc, fin_utc, debut.strftime("%Y-%m-%d"))
    telecharger_miniatures({ligne[0] for ligne in a_identifier})
    n_revoir, n_revoir_total = exporter_a_revoir(db)
    print(f"Semaine du {debut:%d/%m/%Y %Hh%M} au {fin:%d/%m/%Y %Hh%M} (heure de Paris)")
    if args.local:
        print("Mode local : aucune recherche YouTube (0 unité de quota utilisée).")
    else:
        print(f"{len(ids)} vidéos trouvées, {nb} nouvelles analysées.")
    print(f"Classement POC : {n_poc} chaînes ({sans_degats} vidéos sans dégâts lisibles)")
    print(f"Classement BOT : {n_bot} chaînes ({sans_chrono} vidéos sans chrono lisible)")
    print(f"Classement Boss de Guilde : {n_gb} chaînes ({sans_rc} vidéos sans RC lisible)")
    if importes:
        print(f"{importes} valeurs identifiées par Claude importées (resultats_claude.csv)")
    print(f"{len(a_identifier)} vidéos à faire identifier par Claude : "
          "a_identifier.csv + dossier miniatures")
    print(f"{n_revoir} vidéos illisibles sur miniature, rangées à part dans a_revoir.csv "
          f"(à identifier en regardant la vidéo ; {n_revoir_total} lignes en tout)")
    print("Exports : classement_poc.csv, classement_bot.csv, classement_gb.csv, "
          "chaines.csv, videos.csv")


if __name__ == "__main__":
    main()
