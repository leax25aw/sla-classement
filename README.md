# sla-classement
## Page web des classements

La page est dans le dossier `docs/` (HTML, CSS et JavaScript, sans dépendance). Elle lit les trois fichiers `docs/data/classement_bot.csv`, `classement_gb.csv` et `classement_poc.csv`.

- Activer la page : Settings, Pages, Source « Deploy from a branch », branche `main`, dossier `/docs`.
- Mise à jour chaque semaine : après `py sla_youtube.py`, déposer les trois `classement_*.csv` dans `docs/data/` (Add file, Upload files).
- Ne jamais mettre de clé API ni la base `sla_videos.sqlite` dans le dépôt.
