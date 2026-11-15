# scribe-voice

Worker de dictée vocale **local** : reconnaissance vocale avec
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), piloté par une application
cliente via un protocole **JSON Lines** sur stdin/stdout.

- Un seul processus permanent : PyAudio et le modèle Whisper restent en mémoire entre les dictées.
- Transcription locale. Le réseau sert seulement à obtenir le modèle depuis Hugging Face
  lorsqu'aucun modèle local ne correspond. Avec `"offline": true`, le worker n'utilise que des
  modèles déjà présents sur le disque et ne télécharge rien.
- Détection d'un mot-clé en début de phrase (par défaut `Scribe`) et commande de
  confirmation oui/non.

Version du worker : **1.1.1** ; version du protocole : **4**.

## Utilisation

### Binaire Windows x64

Télécharger `voice_worker.exe` (ou le zip) depuis les
[Releases](https://github.com/nico2511/scribe-voice/releases), vérifier le SHA-256 (voir plus bas),
puis le lancer comme sous-processus avec stdin et stdout en pipes :

```python
import json, subprocess
p = subprocess.Popen(["voice_worker.exe"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
send = lambda o: (p.stdin.write((json.dumps(o) + "\n").encode()), p.stdin.flush())
send({"cmd": "init", "config": {"language": "fr", "model_size": "small"}})
send({"cmd": "start"})    # démarre l'enregistrement
# ... parler ...
send({"cmd": "stop"})     # arrête -> événements transcribing / transcript
for line in p.stdout:
    evt = json.loads(line.decode("utf-8"))
    if evt["type"] == "transcript":
        print(evt["text"]); break
send({"cmd": "shutdown"})
```

`toggle` reste disponible : il démarre l'enregistrement s'il est arrêté, et l'arrête sinon.

### Depuis les sources

```bash
pip install -r requirements.txt
python voice_worker.py
```

Le code n'est spécifique à Windows que pour le bip de début et de fin (`winsound`, ignoré
ailleurs) et pour le passage de stdout en mode binaire. Seul un binaire Windows x64 est
construit et publié. Hors Windows, la CI ne lance les tests qu'avec de faux modules
(`tests/fakes/`).

### Mot-clé et confirmation

```python
send({
    "cmd": "init",
    "config": {
        "language": "fr",
        "model_size": "small",
        "keyword": "Scribe",
        "keyword_aliases": ["scrybe"],   # variantes produites par la reconnaissance
        "app_id": "mon-app",             # journal séparé pour cette application
    },
})
# Événement transcript :
#   evt["text"]          -> transcription brute
#   evt.get("command")   -> {"keyword": "Scribe", "text": "ouvre les paramètres."}
#                           seulement si la phrase commence par le mot-clé ou un alias

send({"cmd": "confirm", "timeout": 4})
# Événement confirmation -> {"answer": "yes" | "no" | "unknown", "text": "..."}
```

Le worker n'exécute aucune action : il renvoie le texte et la classification, et c'est
l'application cliente qui décide quoi faire.

### Modèles

Le dossier des modèles est choisi dans cet ordre de priorité :

1. `models_dir` dans la `config` de `init` ;
2. la variable d'environnement `SCRIBE_VOICE_MODELS_DIR` ;
3. le dossier par défaut `~/Documents/CyberScribeNote/models`.

Le worker accepte une racine de cache Hugging Face (`models--Systran--faster-whisper-small/...`),
des dossiers plats (`small/`, `faster-whisper-small/`, `whisper-small/`) ou le chemin direct d'un
modèle CTranslate2. Avec `"offline": true`, aucun téléchargement n'a lieu et un dossier de modèles
doit être indiqué. Détails : [docs/PROTOCOL.md](docs/PROTOCOL.md#configuration-config).

```python
send({"cmd": "init", "config": {
    "model_size": "small",
    "models_dir": "/chemin/vers/modeles",
    "offline": True,
}})
```

### Journal

- Fichier `~/Documents/CyberScribeNote/voice_worker.log`, ou
  `~/Documents/CyberScribeNote/<app_id>/voice_worker.log` après un `init` avec `app_id`.
- stdout est réservé au protocole.
- Par défaut, le texte transcrit n'est pas écrit dans le journal. Pour l'inclure, lancer le
  worker avec la variable d'environnement `SCRIBE_VOICE_LOG_TRANSCRIPTS=1` (ou `true`, `yes`, `on`).

## Protocole (résumé)

| Commandes (stdin) | Événements (stdout) |
|---|---|
| `init`, `preload`, `start`, `stop`, `toggle`, `confirm`, `ping`, `shutdown` | `deps`, `ready`, `status`, `model`, `recording`, `transcribing`, `transcript`, `confirmation`, `error`, `pong` |

La spécification complète est dans [docs/PROTOCOL.md](docs/PROTOCOL.md), et l'historique des
versions dans [CHANGELOG.md](CHANGELOG.md).

## Build

Windows x64, CPython **3.11** (la CI de release utilise 3.11.9) :

```powershell
.\build.ps1 -Version v1.1.1
# -> release\voice_worker.exe, release\scribe-voice-v1.1.1-win-x64.zip, release\SHA256SUMS
```

`build.ps1` installe `requirements-build.txt`, lance PyInstaller avec `voice_worker.spec`, puis
rejette le build si des fichiers PyAV ou FFmpeg (`av.libs`, `x264`, `x265`, `avcodec`) se trouvent
dans `dist/` ou `build/`. Le zip contient l'exe, `LICENSE`, `THIRD_PARTY_NOTICES.md` et `README.md`.
Sans `-Version`, la version vaut `dev`.

- `requirements.txt` : dépendances d'exécution, à versions figées.
- `requirements-build.txt` : `requirements.txt` plus PyInstaller et ses dépendances, à versions figées.
- `requirements-dev.txt` : dépendances des tests (`pytest`, `numpy`).
- `voice_worker.spec` : spec PyInstaller en un seul fichier, en mode console. Elle embarque les
  données de faster-whisper (dont `silero_vad_v6.onnx`, nécessaire au VAD) et exclut `av`.
- `build_sidecar.ps1` : ancien script d'intégration Tauri. Il suppose un dossier `voice/` et
  copie l'exe dans `src-tauri/binaries/`. Ni `build.ps1` ni la CI ne l'utilisent.

### CI

- `.github/workflows/ci.yml` lance les tests sous Windows et Linux (Python 3.11) à chaque push sur
  `main` et `release/**`, et sur chaque pull request.
- `.github/workflows/release.yml` se déclenche sur un tag `v*` ou à la main. Il lance les tests
  sous Windows, construit l'exe, puis fait un smoke test : `deps`, `ready`, `ping`, `shutdown`.
  Si la référence est un tag, il publie `voice_worker.exe`, le zip et `SHA256SUMS` dans la release GitHub.

### Smoke test

```bash
python tools/smoke_exe.py release/voice_worker.exe
```

Ce script vérifie `deps`, `ready`, `pong` et un code de sortie 0. Un test de transcription
hors ligne est ajouté si `SCRIBE_SMOKE_MODELS_DIR` est défini. Ce test utilise `voice_worker.py`
avec l'interpréteur courant, pas l'exe. Variables associées :

- `SCRIBE_SMOKE_MODEL` : taille du modèle, `small` par défaut ;
- `SCRIBE_SMOKE_WAV` : fichier WAV mono 16 kHz. Sans lui, le script génère un sinus d'une seconde.

La CI de release ne définit pas `SCRIBE_SMOKE_MODELS_DIR` : ce test de transcription n'y est donc pas exécuté.

`tools/bench_hallucination.py` est un banc manuel : il envoie du bruit synthétique au modèle
`base` réel. pytest ne l'exécute pas.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Les tests ne demandent ni micro ni modèle : `tests/fakes/` fournit de faux modules `pyaudio`,
`faster_whisper` et `winsound`. Les tests de protocole lancent le vrai `voice_worker.py` en sous-processus.

## Vérification SHA-256

Télécharger `SHA256SUMS` à côté des fichiers de la release, puis :

```powershell
# Windows (PowerShell)
Get-FileHash .\voice_worker.exe -Algorithm SHA256
Get-Content .\SHA256SUMS      # le hash doit correspondre (casse indifférente)
```

```bash
# Linux / macOS / Git Bash
sha256sum -c SHA256SUMS --ignore-missing
```

Les builds PyInstaller ne sont pas reproductibles bit à bit : `SHA256SUMS` permet de vérifier
l'intégrité du fichier publié par la CI, mais pas son égalité avec un build local.

## Licence

[MIT](LICENSE) © 2026 nico2511 (Nicolas L). Pour les composants tiers, voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
