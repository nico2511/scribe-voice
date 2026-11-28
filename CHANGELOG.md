# Changelog

## Non publié

- Lanceur graphique de démonstration : `examples/voice_launcher_gui.py` (Tkinter),
  raccourci F8 (global sous Windows), spec `examples/voice_launcher_gui.spec`.
  Le worker reste un `voice_worker.exe` séparé (`--exe`, `SCRIBE_VOICE_WORKER`,
  ou à côté du lanceur graphique).

## v1.3.0 — 2026-11-28

Version du worker **1.3.0**. Le protocole passe à **5**.

- Protocole **5** : champ optionnel `end_on_silence_ms` sur `start` et `confirm` pour arrêter
  l'écoute après un silence continu une fois la parole détectée (détection Silero ou RMS).
- Lanceur : `--end-on-silence-ms` (défaut 700, `0` pour désactiver) transmis à `confirm`.
- Lanceur vocal de démonstration : `examples/voice_launcher.py` et fichier d'actions
  `examples/launcher_actions.example.json` (actions `run`, `open`, `say`, confirmation optionnelle).
- Synthèse vocale optionnelle Kokoro (`examples/requirements-launcher.txt`) : invitation à confirmer
  à voix haute, délai `confirm` porté à 6 s par défaut, annonces de résultat (`C'est fait.`, `Annule.`).
- Correspondance sur la première phrase de `command.text` ; oui/non dans la même prise ignorés pour
  la confirmation (repose de la question si besoin).
- Kokoro préchargé au démarrage (`repo_id` explicite), cache HF hors ligne par défaut,
  `--confirm-timeout` 3,5 s, `--exe` relatif résolu depuis le cwd, `--verbose` pour le délai confirm.

## v1.2.0

Version du worker **1.2.0**. Le protocole **4** ne change pas.

### Rupture : mot-clé par défaut

Le mot-clé vocal par défaut est désormais `Majordome` (au lieu de `Scribe`). Les
applications qui s'appuyaient sur l'ancien défaut doivent passer `"keyword": "Scribe"`
dans leur `config` de `init`, ou adopter le nouveau mot-clé. La liste par défaut
`keyword_aliases` couvre des variantes de transcription probables (`Major d'homme`,
`Major dome`, `Majordom`, `Majordomes`) uniquement lorsque le mot-clé effectif reste
`Majordome` et qu'aucun `keyword_aliases` n'est fourni ; un `keyword` personnalisé sans
`keyword_aliases` n'hérite pas de ces variantes. Une valeur fournie dans la config remplace
la liste entièrement (y compris `[]`).

- Client de démonstration : `examples/demo_client.py` (stdlib, console Windows).
- Correctif Windows du client de démo : les messages affichés sont en ASCII (`->` à la place de `→`), et stdout/stderr sont reconfigurés en UTF-8 (`errors=replace`) pour éviter un plantage quand la page de codes est cp1252.

### Rupture : dossiers par défaut

Le worker utilise désormais `~/Documents/scribe-voice` pour les journaux et
`~/Documents/scribe-voice/models` pour les modèles téléchargés (y compris
`voice_worker.log` et `<app_id>/voice_worker.log`). Les installations qui
laissaient modèles ou journaux dans l'ancien emplacement par défaut ne les
retrouveront pas sans les déplacer ou sans retélécharger les modèles.
Aucun repli automatique vers l'ancien dossier.

- `log_transcripts` dans `config` est pris en charge (booléen, défaut `false`). La variable
  d'environnement `SCRIBE_VOICE_LOG_TRANSCRIPTS` force l'activation lorsqu'elle vaut vrai ; sinon
  c'est la config qui s'applique.
- Une ligne JSON valide dont la racine n'est pas un objet produit
  `JSON invalide : un objet JSON est attendu` au lieu de terminer le worker.

## v1.1.1

- Correctif Windows : NumPy est maintenant importé au démarrage, sur le thread principal
  (`check_deps()`). Sous Windows, son premier import depuis un thread de transcription pouvait
  bloquer indéfiniment pendant l'initialisation d'OpenBLAS, et la transcription ne se terminait jamais.
- `deps` signale aussi l'absence de `numpy`.
- `requirements-dev.txt` : ajout de `numpy==2.4.6`, nécessaire aux tests.
- Version du worker **1.1.1**. Le protocole **4** ne change pas.

## v1.1.0

Le tag existe, mais aucun binaire n'a été publié pour cette version. La première release qui
contient ces changements est la v1.1.1. Le protocole passe à **4** (voir [docs/PROTOCOL.md](docs/PROTOCOL.md)).

### Commandes et protocole

- Nouvelles commandes `start` et `stop`, toutes deux idempotentes. `toggle` est conservé.
- `preload` attend la fin du chargement en arrière-plan : les autres commandes, comme `ping`,
  sont traitées pendant ce temps.
- Configuration `keyword` (par défaut `Scribe`) et `keyword_aliases`. Champ optionnel `command`
  sur `transcript` quand la phrase commence par le mot-clé.
- Nouvelle commande `confirm` : écoute courte, puis classification `yes`, `no` ou `unknown`
  dans l'événement `confirmation`.
- Champs `version` et `protocol` dans l'événement `ready`.

### Modèles

- Valeurs par défaut : `model_size` `small` et `language` `fr`.
- Choix du dossier des modèles par `models_dir` ou `SCRIBE_VOICE_MODELS_DIR`. Prise en charge des
  dossiers plats, du cache Hugging Face et des chemins directs vers un modèle CTranslate2.
- Option `offline` : aucun téléchargement Hugging Face, et une erreur explicite si le modèle est
  absent.

### Transcription des commandes courtes

- Prompt Whisper dérivé du mot-clé, et transcription vidée quand elle ne contient que le mot-clé.
- Porte VAD Silero sous 8 s, VAD Whisper seulement à partir de 3,5 s, et seconde passe sans VAD
  si le résultat est vide.
- Un second `toggle` pendant le délai de démarrage (~220 ms) annule l'enregistrement.

### Journal

- Le texte transcrit n'est plus écrit dans `voice_worker.log` par défaut. Pour l'inclure :
  variable d'environnement `SCRIBE_VOICE_LOG_TRANSCRIPTS`.
- Journal séparé par application avec `app_id`.

### Build

- PyAV n'est plus utilisé : l'audio PCM est passé directement à faster-whisper sous forme de
  tableau NumPy. `av` est exclu de l'exe, et `build.ps1` rejette tout build qui contient des
  fichiers PyAV ou FFmpeg (`av.libs`, `x264`, `x265`, `avcodec`).
- Smoke test : variable `SCRIBE_SMOKE_MODEL` (`small` par défaut) pour le test de transcription
  optionnel.
