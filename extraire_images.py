#!/usr/bin/env python3
"""
Deuxième passe : extrait des images des vidéos que la miniature n'a pas permis
d'identifier (celles de a_revoir.csv, statut « à revoir »), pour que Claude les
lise ensuite. Aucun appel à Claude, aucun quota YouTube.

Les écrans qui montrent le résultat (chrono, Rage Count, dégâts) apparaissent
dans les 10 premières ou les 10 dernières secondes de la vidéo (réglable avec
--secondes) : le script ne télécharge que ces deux morceaux, prend une image
toutes les 4 secondes, puis les range en PLANCHES (6 images par planche). Avec
10 secondes, il y a en général 1 seule planche par vidéo.

Installation (une seule fois, sous Windows) :
    py -m pip install yt-dlp imageio-ffmpeg

Utilisation, dans le dossier SLA, après avoir lancé sla_youtube.py :
    py extraire_images.py              # traite 5 vidéos à revoir
    py extraire_images.py --max 10     # traite 10 vidéos
    py extraire_images.py --video ID   # une vidéo à revoir précise (son identifiant)
    py extraire_images.py --video ID1 ID2 --mode gb   # vidéos DÉJÀ classées, à relire (ex. dégâts)
    py extraire_images.py --secondes 30  # 30 s au début et à la fin (10 par défaut)
    py extraire_images.py --video ID --mode gb --toute   # TOUTE la vidéo (le score peut s'afficher n'importe quand)
    py extraire_images.py --video ID --mode poc --toute --pas 6   # une image toutes les 6 s (10 par défaut)
    py extraire_images.py --refaire    # refait aussi les vidéos déjà extraites
    py extraire_images.py --ajouter    # garde le contenu de a_envoyer et le complète

3e PASSE AUTOMATIQUE : une vidéo dont la 2e passe (10 s au début et à la fin) n'a
montré aucun score (ligne rendue par Claude avec passe = 2 et valeur vide, statut
« à revoir sur toute la vidéo » dans a_revoir.csv) est reprise AUTOMATIQUEMENT, au
lancement suivant de py extraire_images.py, avec la méthode --toute ci-dessous :
images sur toute la vidéo. Claude rend alors passe = 3 (la colonne passe_a_rendre
de liste.csv le dit pour chaque vidéo). Valeur vide en passe 3 = définitif : la
vidéo n'est plus reprise. Chaque vidéo traitée ainsi donne en général plusieurs
planches (environ 1 par minute de vidéo) : compter ce coût avant de lancer, et
utiliser --max pour limiter le nombre de vidéos.

Option --toute (avec --video et --mode, ou --fichier) : pour les vidéos dont le
score peut apparaître à n'importe quel moment (titre annonçant deux éléments,
écran de résultat absent du début et de la fin). Le script télécharge TOUTE la
vidéo (qualité limitée, sans son), prend une image toutes les --pas secondes
(10 par défaut) et les range en planches nommées
<id_video>_<mode>_toute_planche_NN.jpg ; l'instant de chaque image est écrit
sous la forme minutes:secondes dans liste.csv. Au plus --max-images images
(180 par défaut) : au-delà, le pas est augmenté automatiquement et le script le
dit. Compter 6 images par planche : une vidéo de 10 minutes au pas de 10 s donne
10 planches.

Tester les réglages sur une vidéo déjà présente sur ton ordinateur :
    py extraire_images.py --fichier ma_video.mp4 --mode bot

Résultat : un dossier « a_envoyer » qui contient UNIQUEMENT ce qu'il faut
envoyer à Claude pour ce lancement : les planches (nommées
<id_video>_<mode>_planche_01.jpg, donc impossibles à confondre) et liste.csv
(quoi chercher et dans quel ordre sont les images de chaque planche). Envoie à
Claude TOUT le contenu de ce dossier : il rend un fichier d'ajout
resultats_claude_ajout.csv avec la colonne passe indiquée dans la colonne
passe_a_rendre de liste.csv (2 = début et fin, 3 = vidéo entière).
Au lancement suivant, le contenu précédent de « a_envoyer » est rangé dans
images_a_revoir\\archives\\<date>\\ (--ajouter pour le garder et compléter).
Les planches restent aussi dans images_a_revoir\\<id_video>\\.

Réglages : le fichier reglages_images.json (créé au premier lancement).
Attention : YouTube interdit en général le téléchargement de ses vidéos en
dehors de ses outils. Le script ne télécharge que les deux morceaux utiles, en
basse qualité, et SUPPRIME les morceaux après avoir gardé les images
(--garder pour l'éviter).
"""
import argparse
import copy
import csv
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DB = "sla_videos.sqlite"
DOSSIER = Path("images_a_revoir")
ENVOI = Path("a_envoyer")                 # ce qu'on envoie à Claude
ARCHIVES = DOSSIER / "archives"           # anciens contenus de a_envoyer
REGLAGES = Path("reglages_images.json")

QUOI = {"bot": "chrono en secondes", "gb": "Rage Count (RC)",
        "poc": "dégâts en T (billions)"}

# Réglages par défaut. Pour chaque mode :
#   segments : liste de morceaux de la vidéo où prendre des images
#              ["debut", de_s, a_s]  = de « de_s » à « a_s » secondes depuis le début
#              ["fin", de_s, a_s]    = de « de_s » à « a_s » secondes AVANT la fin
#   pas_s    : une image toutes les X secondes
#   zone     : null = image entière, ou [x, y, largeur, hauteur] en fractions de
#              l'image (0 à 1), ex. [0.0, 0.8, 1.0, 0.2] = bande du bas
DUREE_DEFAUT = 10  # secondes prises au début et à la fin (option --secondes)
MODE_DEFAUT = {"segments": [["debut", 0, DUREE_DEFAUT - 2], ["fin", DUREE_DEFAUT, 2]],
               "pas_s": 4, "zone": None}
DEFAUT = {
    "bot": MODE_DEFAUT,
    "gb": MODE_DEFAUT,
    "poc": MODE_DEFAUT,
    # planche : nombre de colonnes x lignes d'images par planche, et largeur
    # de chaque image. 2 x 3 à 760 px = bien lisible une fois envoyé à Claude.
    "planche": {"colonnes": 2, "lignes": 3, "largeur_tuile": 760},
    "qualite_telechargement_max": 720,
}


def charger_reglages():
    if not REGLAGES.exists():
        REGLAGES.write_text(json.dumps(DEFAUT, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        print(f"Fichier de réglages créé : {REGLAGES} (valeurs par défaut).")
    reglages = json.loads(REGLAGES.read_text(encoding="utf-8"))
    for cle, val in DEFAUT.items():
        reglages.setdefault(cle, val)
    for mode in QUOI:  # compatibilité avec l'ancien format (un seul « segment »)
        r = reglages[mode]
        if "segments" not in r:
            r["segments"] = [r["segment"]] if "segment" in r else MODE_DEFAUT["segments"]
        r.setdefault("pas_s", 4)
        r.setdefault("zone", None)
    return reglages


def appliquer_duree(reglages, secondes):
    """Impose « secondes » au début et à la fin, quel que soit le contenu de
    reglages_images.json (--secondes passe avant le fichier de réglages)."""
    s = max(4, int(secondes))
    for mode in QUOI:
        reglages[mode]["segments"] = [["debut", 0, s - 2], ["fin", s, 2]]


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        sys.exit("ffmpeg introuvable. Installe-le avec :\n"
                 "    py -m pip install imageio-ffmpeg")


def instants(segment, pas):
    """Instants (secondes) d'un segment, dans l'ordre chronologique."""
    repere, de, a = segment
    pas = max(1, int(pas))
    de, a = float(de), float(a)
    t, liste = de, []
    if repere == "fin":            # de « de » s avant la fin jusqu'à « a » s avant
        while t >= a:
            liste.append(t)
            t -= pas
    else:                          # de « de » s après le début jusqu'à « a » s
        while t <= a:
            liste.append(t)
            t += pas
    return liste


def duree_fichier(source):
    """Durée (secondes) d'un fichier vidéo, lue avec ffmpeg ; None si introuvable."""
    r = subprocess.run([ffmpeg_exe(), "-i", str(source)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def reglages_toute(reglages, modes, duree, pas, max_images):
    """Copie des réglages pour la vidéo ENTIÈRE : une image toutes les « pas »
    secondes, de 0 à la fin, sans dépasser max_images images (le pas est alors
    augmenté). Renvoie (reglages, pas_utilise)."""
    pas = max(1, int(pas))
    fin = max(0, int(duree) - 1)
    if max_images and fin // pas + 1 > max_images:
        pas = -(-fin // max(1, max_images - 1))
        print(f"    vidéo longue : pas porté à {pas} s pour rester sous {max_images} images")
    neuf = copy.deepcopy(reglages)
    for mode in modes:
        neuf[mode] = {"segments": [["debut", 0, fin]], "pas_s": pas, "zone": None,
                      "toute": True}
    return neuf, pas


def filtre_video(zone, largeur):
    morceaux = []
    if zone:
        x, y, w, h = (float(v) for v in zone)
        morceaux.append(f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}")
    morceaux.append(f"scale={int(largeur)}:-2")
    return ",".join(morceaux)


def extraire_cadres(fichiers, regle, largeur, dossier):
    """Extrait les images de tous les segments, dans l'ordre chronologique.
    Renvoie une liste de (fichier_image, description)."""
    ffmpeg = ffmpeg_exe()
    dossier.mkdir(parents=True, exist_ok=True)
    vf = filtre_video(regle.get("zone"), largeur)
    cadres, n = [], 0
    for seg in regle["segments"]:
        repere = seg[0]
        source = fichiers.get(repere) or fichiers.get("tout")
        if not source:
            continue
        for t in instants(seg, regle["pas_s"]):
            if repere == "fin":
                pos, desc = ["-sseof", f"-{max(t, 0.5)}"], f"fin -{int(t)}s"
            elif regle.get("toute"):
                pos, desc = ["-ss", str(t)], f"{int(t) // 60}:{int(t) % 60:02d}"
            else:
                pos, desc = ["-ss", str(t)], f"début {int(t)}s"
            n += 1
            nom = dossier / f"cadre_{n:03d}.jpg"
            cmd = [ffmpeg, "-y", "-loglevel", "error", *pos, "-i", str(source),
                   "-frames:v", "1", "-vf", vf, "-q:v", "3", str(nom)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0 and nom.exists() and nom.stat().st_size > 0:
                cadres.append((nom, desc))
            else:
                n -= 1  # numérotation continue pour l'assemblage
    return cadres


def faire_planches(cadres, planche, sortie, prefixe):
    """Assemble les images en planches. Renvoie (fichiers, description de l'ordre)."""
    if not cadres:
        return [], ""
    cols, lignes = int(planche["colonnes"]), int(planche["lignes"])
    par_planche = cols * lignes
    ffmpeg = ffmpeg_exe()
    dossier = cadres[0][0].parent
    modele = str(sortie / f"{prefixe}_planche_%02d.jpg")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-framerate", "1", "-start_number", "1",
           "-i", str(dossier / "cadre_%03d.jpg"),
           "-vf", f"tile={cols}x{lignes}:padding=4:color=black", "-q:v", "3", modele]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("assemblage des planches impossible : " + r.stderr[-200:])
    fichiers = sorted(sortie.glob(f"{prefixe}_planche_*.jpg"))
    ordre = []
    for i, f in enumerate(fichiers):
        morceau = cadres[i * par_planche:(i + 1) * par_planche]
        ordre.append(f"{f.name} (de gauche à droite, puis ligne par ligne) : "
                     + ", ".join(d for _, d in morceau))
    return fichiers, " | ".join(ordre)


def _yt(vid, nom, tmp, qualite, section=None):
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--quiet", "--no-warnings",
           "--ffmpeg-location", str(ffmpeg_exe()),
           "-f", f"bv*[height<={qualite}]/b[height<={qualite}]",
           "-o", str(tmp / f"{nom}.%(ext)s")]
    if section:
        cmd += ["--download-sections", section]
    cmd.append(f"https://www.youtube.com/watch?v={vid}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    fichiers = [f for f in tmp.glob(f"{nom}.*") if f.suffix not in (".part", ".ytdl")]
    if r.returncode != 0 or not fichiers:
        raise RuntimeError((r.stderr or r.stdout or "échec du téléchargement").strip()[-300:])
    return fichiers[0]


def telecharger(vid, regles, duree_s, reglages, tmp, toute=False):
    """Télécharge seulement les morceaux utiles (vidéo sans son, qualité limitée).
    Renvoie un dict {"debut": fichier, "fin": fichier} ou {"tout": fichier}."""
    tmp.mkdir(parents=True, exist_ok=True)
    qualite = int(reglages["qualite_telechargement_max"])
    if toute:  # vidéo entière
        return {"tout": _yt(vid, "tout", tmp, qualite)}
    segs = [s for r in regles for s in r["segments"]]
    besoin_fin = max([s[1] for s in segs if s[0] == "fin"], default=None)
    besoin_debut = max([s[2] for s in segs if s[0] == "debut"], default=None)
    if not duree_s or (besoin_fin is not None and besoin_debut is not None
                       and duree_s <= besoin_fin + besoin_debut + 40):
        return {"tout": _yt(vid, "tout", tmp, qualite)}  # vidéo courte ou durée inconnue
    fichiers = {}
    if besoin_debut is not None:
        fichiers["debut"] = _yt(vid, "debut", tmp, qualite, f"*0-{int(besoin_debut) + 10}")
    if besoin_fin is not None:
        debut = max(0, int(duree_s - besoin_fin - 10))
        fichiers["fin"] = _yt(vid, "fin", tmp, qualite, f"*{debut}-inf")
    return fichiers


def videos_a_revoir(video_ids=None, mode=None):
    """Vidéos à traiter. Par défaut : celles de a_revoir.csv. Avec --video et --mode :
    les vidéos données, même déjà classées (ex. relire les dégâts d'une vidéo)."""
    if not Path(DB).exists():
        sys.exit(f"{DB} introuvable : lance d'abord sla_youtube.py dans ce dossier.")
    db = sqlite3.connect(DB)
    groupes = {}
    if video_ids and mode:  # vidéos choisies à la main, quel que soit leur statut
        for vid in video_ids:
            r = db.execute("SELECT id, channel, title, duration_s FROM videos WHERE id = ?",
                           (vid,)).fetchone()
            if r is None:
                print(f"Vidéo {vid} inconnue de {DB} : lance sla_youtube.py puis réessaie.")
                continue
            groupes[vid] = {"vid": vid, "modes": [mode], "chaine": r[1], "titre": r[2],
                            "duree": r[3], "toute": False}
        return groupes
    # Vidéos sans valeur lue : passe < 2 = miniature seulement -> 10 s au début et à la
    # fin ; passe 2 = ces 10 s n'ont rien donné -> images sur TOUTE la vidéo (passe 3).
    # Passe 3 sans valeur = définitif : plus jamais reprise.
    try:
        lignes = db.execute(
            "SELECT v.video_id, v.mode, i.channel, i.title, i.duration_s, COALESCE(v.passe, 1) "
            "FROM valeurs_claude v JOIN videos i ON i.id = v.video_id "
            "WHERE v.valeur IS NULL AND v.total IS NULL AND COALESCE(v.passe, 1) < 3 "
            "ORDER BY i.published DESC").fetchall()
    except sqlite3.OperationalError:
        sys.exit("Mets d'abord à jour sla_youtube.py et relance-le une fois.")
    for vid, mode_v, chaine, titre, duree, passe in lignes:
        if video_ids and vid not in video_ids:
            continue
        toute = passe >= 2
        cle = f"{vid}_toute" if toute else vid  # une même vidéo peut avoir les deux cas
        g = groupes.setdefault(cle, {"vid": vid, "modes": [], "chaine": chaine, "titre": titre,
                                     "duree": duree, "toute": toute})
        g["modes"].append(mode_v)
    return groupes


def preparer_envoi(ajouter=False):
    """Prépare le dossier a_envoyer. Sauf avec --ajouter, son contenu précédent
    est rangé dans images_a_revoir\\archives\\<date> (rien n'est supprimé)."""
    ENVOI.mkdir(exist_ok=True)
    anciens = [f for f in ENVOI.iterdir() if f.is_file()]
    if anciens and not ajouter:
        dest = ARCHIVES / datetime.now().strftime("%Y%m%d_%H%M%S")
        dest.mkdir(parents=True, exist_ok=True)
        for f in anciens:
            shutil.move(str(f), str(dest / f.name))


def ecrire_liste(lignes):
    ENVOI.mkdir(exist_ok=True)
    chemin = ENVOI / "liste.csv"
    nouveau = not chemin.exists()
    with open(chemin, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if nouveau:
            w.writerow(["id_video", "mode", "quoi_chercher", "chaine", "titre",
                        "dossier_images", "nb_planches", "ordre_des_images",
                        "passe_a_rendre"])
        w.writerows(lignes)


def traiter(vid, modes, fichiers, reglages, sortie, envoi=None, suffixe="", passe=2):
    """Une planche par jeu de réglages distinct (3 modes identiques = 1 seul jeu).
    passe = valeur de la colonne « passe » que Claude doit rendre (2 = début et fin,
    3 = vidéo entière), écrite dans liste.csv."""
    sortie.mkdir(parents=True, exist_ok=True)
    deja, lignes = {}, []
    for mode in modes:
        r = reglages[mode]
        cle = json.dumps([r["segments"], r["pas_s"], r["zone"]])
        if cle not in deja:
            prefixe = mode if len(deja) == 0 else f"{mode}_{len(deja) + 1}"
            prefixe = f"{vid}_{prefixe}{suffixe}"  # l'identifiant de la vidéo dans chaque nom
            tmp_cadres = sortie / f"_cadres_{prefixe}"
            cadres = extraire_cadres(fichiers, r, reglages["planche"]["largeur_tuile"],
                                     tmp_cadres)
            planches, ordre = faire_planches(cadres, reglages["planche"], sortie, prefixe)
            shutil.rmtree(tmp_cadres, ignore_errors=True)
            if envoi is not None:  # copie dans a_envoyer (noms uniques)
                for f in planches:
                    shutil.copy2(f, envoi / f.name)
            deja[cle] = (planches, ordre)
        planches, ordre = deja[cle]
        lignes.append([vid, mode, QUOI[mode], "", "",
                       str(envoi if envoi is not None else sortie), len(planches), ordre,
                       passe])
    return lignes


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--max", type=int, default=5, help="nombre de vidéos par lancement")
    p.add_argument("--video", nargs="+", help="identifiant(s) de vidéo ; avec --mode, même si déjà classée")
    p.add_argument("--refaire", action="store_true")
    p.add_argument("--ajouter", action="store_true",
                   help="garder le contenu actuel de a_envoyer et le compléter")
    p.add_argument("--garder", action="store_true", help="ne pas supprimer les morceaux téléchargés")
    p.add_argument("--secondes", type=int, default=DUREE_DEFAUT,
                   help="secondes prises au début ET à la fin de la vidéo (10 par défaut)")
    p.add_argument("--toute", action="store_true",
                   help="images sur TOUTE la vidéo (avec --video et --mode, ou --fichier)")
    p.add_argument("--pas", type=int, default=10,
                   help="avec --toute : une image toutes les X secondes (10 par défaut)")
    p.add_argument("--max-images", type=int, default=180,
                   help="avec --toute : nombre maximal d'images par vidéo (180 par défaut)")
    p.add_argument("--fichier", help="vidéo locale (test des réglages)")
    p.add_argument("--mode", choices=["bot", "gb", "poc"], help="mode, avec --fichier ou --video")
    a = p.parse_args()
    reglages = charger_reglages()
    appliquer_duree(reglages, a.secondes)

    if a.fichier:  # test sur un fichier déjà présent sur l'ordinateur
        if not a.mode:
            sys.exit("Ajoute --mode bot, gb ou poc.")
        sortie = DOSSIER / "test"
        shutil.rmtree(sortie, ignore_errors=True)
        suffixe = ""
        if a.toute:
            d = duree_fichier(a.fichier)
            if not d:
                sys.exit("Durée du fichier illisible.")
            reglages, _ = reglages_toute(reglages, [a.mode], d, a.pas, a.max_images)
            suffixe = "_toute"
        lignes = traiter("test", [a.mode], {"tout": Path(a.fichier)}, reglages, sortie,
                         suffixe=suffixe, passe=3 if a.toute else 2)
        print(f"{lignes[0][6]} planches dans {sortie}")
        print(lignes[0][7])
        return

    if a.toute and not (a.video and a.mode):
        sys.exit("--toute s'utilise avec --video ID et --mode bot, gb ou poc.")
    groupes = videos_a_revoir(a.video, a.mode)
    if not groupes:
        print("Aucune vidéo à revoir pour le moment.")
        return
    DOSSIER.mkdir(exist_ok=True)
    traitees = 0
    envoi_pret = False  # a_envoyer n'est vidé qu'à la 1re vidéo réellement traitée
    for g in groupes.values():
        vid = g["vid"]
        toute = a.toute or g["toute"]  # --toute à la main, ou 3e passe automatique
        if traitees >= a.max:
            print(f"Limite de {a.max} vidéos atteinte, relance pour continuer.")
            break
        sortie = DOSSIER / (f"{vid}_toute" if toute else vid)  # dossier à part pour --toute
        if sortie.exists() and any(sortie.glob("*.jpg")) and not a.refaire:
            continue
        print(f"[{traitees + 1}] {g['chaine']} — {g['titre'][:60]}"
              + ("  (3e passe : toute la vidéo)" if toute else ""))
        tmp = DOSSIER / f"_tmp_{vid}"
        try:
            fichiers = telecharger(vid, [reglages[m] for m in g["modes"]],
                                   g["duree"], reglages, tmp, toute=toute)
            reglages_v, suffixe = reglages, ""
            if toute:
                d = duree_fichier(fichiers["tout"]) or g["duree"]
                if not d:
                    raise RuntimeError("durée de la vidéo introuvable")
                reglages_v, pas = reglages_toute(reglages, g["modes"], d, a.pas, a.max_images)
                suffixe = "_toute"
                print(f"    vidéo entière : {int(d) // 60} min {int(d) % 60} s, une image toutes les {pas} s")
            if a.refaire:  # évite de garder d'anciennes planches mal nommées
                shutil.rmtree(sortie, ignore_errors=True)
            if not envoi_pret:
                preparer_envoi(a.ajouter)
                envoi_pret = True
            lignes = traiter(vid, g["modes"], fichiers, reglages_v, sortie, ENVOI,
                             suffixe=suffixe, passe=3 if toute else 2)
            for l in lignes:
                l[3], l[4] = g["chaine"], g["titre"]
                print(f"    {l[1]} : {l[6]} planche(s)")
            ecrire_liste(lignes)
            traitees += 1
        except Exception as e:  # une vidéo en échec ne bloque pas les autres
            print(f"    échec : {e}")
        finally:
            if not a.garder:
                shutil.rmtree(tmp, ignore_errors=True)
    if traitees:
        print(f"\n{traitees} vidéos traitées. Envoie à Claude TOUT le contenu du dossier "
              f"{ENVOI} (planches + liste.csv), rien d'autre.")
    else:
        print("\nRien de nouveau à envoyer (vidéos déjà extraites : --refaire pour "
              f"les refaire). Le dossier {ENVOI} n'a pas été modifié.")


if __name__ == "__main__":
    main()
