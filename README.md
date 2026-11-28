# scribe-voice

Worker de dictée vocale **local** : reconnaissance vocale avec
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), piloté par une application
cliente via un protocole **JSON Lines** sur stdin/stdout.

Version du worker : **1.3.0** ; version du protocole : **5**.

## À quoi ça sert

`scribe-voice` est un processus fils de reconnaissance vocale **100 % local** (hors ligne
une fois les modèles sur le disque). L'application qui lance le worker lui envoie des
commandes JSON sur **stdin** et lit des événements JSON sur **stdout**. PyAudio et le
modèle Whisper restent en mémoire entre les dictées, ce qui évite de relancer Python et
de recharger le modèle à chaque prise.

## Cas d'usage

Ces cas décrivent uniquement ce que le code fait aujourd'hui :

- **Dictée push-to-talk** : le parent envoie `start` pour enregistrer le micro,
  `stop` (ou un second `toggle`) pour arrêter ; le worker émet `transcript` avec le
  texte reconnu. `toggle` démarre ou arrête selon l'état courant. Option
  `end_on_silence_ms` sur `start` ou `confirm` : arrêt automatique après fin de parole.
- **Commandes vocales** : si la transcription commence par le mot-clé configuré
  (défaut `Majordome`) ou un de ses alias, l'événement `transcript` contient un champ
  `command` avec le mot-clé et le reste de la phrase. Le worker n'exécute aucune action.
- **Confirmation oui/non** : la commande `confirm` lance une courte écoute et renvoie
  `confirmation` avec `answer` (`yes`, `no` ou `unknown`) et le texte entendu.
- **Plusieurs applications** : `app_id` dans la config de `init` sépare les fichiers
  journaux (`~/Documents/scribe-voice/<app_id>/voice_worker.log`).
- **Sans réseau** : avec `"offline": true` et un `models_dir` (ou
  `SCRIBE_VOICE_MODELS_DIR`) qui pointe vers des modèles déjà présents, aucun
  téléchargement Hugging Face n'a lieu.
- **Confidentialité des journaux** : par défaut, le texte transcrit n'est pas écrit dans
  `voice_worker.log` ; seules des métadonnées (durée, RMS, etc.) y figurent.

## Architecture

- Un seul processus permanent : PyAudio et le modèle Whisper restent en mémoire entre les dictées.
- Transcription locale. Le réseau sert seulement à obtenir le modèle depuis Hugging Face
  lorsqu'aucun modèle local ne correspond. Avec `"offline": true`, le worker n'utilise que des
  modèles déjà présents sur le disque et ne télécharge rien.
- Détection d'un mot-clé en début de phrase (par défaut `Majordome`) et commande de
  confirmation oui/non.

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
        "keyword": "Majordome",
        "keyword_aliases": ["Major dome"],  # remplace la liste par défaut si fournie
        "app_id": "mon-app",             # journal séparé pour cette application
    },
})
# Événement transcript :
#   evt["text"]          -> transcription brute
#   evt.get("command")   -> {"keyword": "Majordome", "text": "ouvre les paramètres."}
#                           seulement si la phrase commence par le mot-clé ou un alias

send({"cmd": "confirm", "timeout": 4})
send({"cmd": "confirm", "timeout": 6, "end_on_silence_ms": 700})
# Événement confirmation -> {"answer": "yes" | "no" | "unknown", "text": "..."}
```

Le worker n'exécute aucune action : il renvoie le texte et la classification, et c'est
l'application cliente qui décide quoi faire.

### Lanceur vocal (démo)

`examples/voice_launcher.py` pilote le worker comme le client de démo, mais exécute
des actions lorsqu'un événement `transcript` contient un champ `command`. Les actions
sont déclarées dans un fichier JSON (par défaut `examples/launcher_actions.example.json`).

```bash
python examples/voice_launcher.py
python examples/voice_launcher.py --actions chemin/vers/actions.json --dry-run
```

Chaque entrée du fichier JSON contient :

- `phrases` : liste de formulations reconnues (comparaison sur `command.text`, normalisée) ;
- `action` : `run` (`args` en liste, sans shell), `open` (`target` URL ou chemin), ou `say` (`message`) ;
- `confirm` : si `true`, le lanceur annonce la question à l'écran et à voix haute, attend
  la fin de la lecture, puis envoie `confirm` au worker (délai par défaut 3,5 s, `--confirm-timeout`).
  `--verbose` affiche le délai entre la fin de la question et l'événement `confirmation`.

**Synthèse vocale optionnelle (Kokoro)** — pour guider l'utilisateur (question de confirmation,
résultat de l'action). Sans ces paquets, le lanceur se contente d'afficher les messages :

```bash
pip install -r examples/requirements-launcher.txt
```

Le modèle [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (~82 M de paramètres,
environ 350 Mo dans le cache Hugging Face) est **préchargé en parallèle** du modèle Whisper au
démarrage (sauf `--dry-run`). Voix française par défaut : `ff_siwis` (`--tts-voice`). Options :
`--tts auto` (défaut), `kokoro`, `none`. Si le modèle est déjà dans le cache HF, le lanceur force
`HF_HUB_OFFLINE=1` sauf avec `--tts-online` (premier téléchargement). Annonce « Lanceur prêt »
quand Whisper et Kokoro sont prêts.

`--exe` accepte un chemin relatif (résolu depuis le répertoire courant, pas la racine du dépôt).

Hors ligne : laisser Hugging Face mettre le modèle en cache lors d'une première exécution en ligne
(`--tts-online`), ou copier le dossier `models--hexgrad--Kokoro-82M` du cache vers la machine cible
(`HF_HOME` / `~/.cache/huggingface/hub`).

Kokoro est sous licence [Apache-2.0](https://github.com/hexgrad/kokoro) ; il n'est pas embarqué
dans `voice_worker.exe` (voir `THIRD_PARTY_NOTICES.md` pour les composants du binaire).

### Lanceur graphique (démo)

`examples/voice_launcher_gui.py` est une petite interface Tkinter (un seul fichier) qui
réutilise la logique de `voice_launcher.py`. Le moteur vocal **`voice_worker.exe` reste un
exécutable séparé** : il n'est ni importé ni embarqué dans le lanceur graphique PyInstaller.
Pour mettre à jour le moteur, **remplacez seulement `voice_worker.exe`** à côté du lanceur
(ou au chemin indiqué par `--exe` / `SCRIBE_VOICE_WORKER`) — inutile de reconstruire le
lanceur graphique.

**Résolution du worker** (dans cet ordre) :

1. `--exe` ;
2. variable d'environnement `SCRIBE_VOICE_WORKER` ;
3. `voice_worker.exe` dans le même dossier que le lanceur graphique (script ou exe gelé).

Lancement depuis les sources :

```powershell
pip install -r requirements.txt
pip install -r examples/requirements-launcher.txt
python examples/voice_launcher_gui.py
```

**F8** démarre ou arrête l'enregistrement (raccourci **global** sous Windows via `RegisterHotKey`
; ailleurs F8 seulement lorsque la fenêtre a le focus). La version et le numéro de **protocole**
lus sur l'événement `ready` s'affichent dans la fenêtre et le journal. L'arrêt automatique après
silence (`end_on_silence_ms`, défaut 700) n'est utilisé que si le protocole du worker est **≥ 5**
; sinon un message l'indique et l'arrêt se fait manuellement avec F8. Un protocole plus récent
ne bloque pas le lanceur : champs et événements inconnus sont ignorés.

Dossier des modèles Whisper : `--models-dir` ou `SCRIBE_VOICE_MODELS_DIR`. Les autres options
(`--actions`, `--offline`, `--tts`, etc.) ont les mêmes défauts que le lanceur console.

Binaire fenêtré (sans console) — la commande n'est pas exécutée automatiquement en CI :

```powershell
pip install -r requirements-build.txt
pip install -r examples/requirements-launcher.txt
pyinstaller examples/voice_launcher_gui.spec
```

Sortie : `dist/voice_launcher_gui.exe` ; placez `voice_worker.exe` dans le même dossier.

### Essayer avec le client de démo

À la racine du dépôt, après `pip install -r requirements.txt` :

```bash
python examples/demo_client.py
```

Le client lance `python voice_worker.py` à côté du dépôt. Options utiles :
`--exe` (binaire à la place du script), `--model`, `--models-dir`, `--offline`, `--keyword`.
Après le chargement du modèle, **Entrée** démarre et arrête l'enregistrement ; **q** + Entrée
envoie `shutdown` et quitte. Les événements du protocole s'affichent dans la console.

### Modèles

Le dossier des modèles est choisi dans cet ordre de priorité :

1. `models_dir` dans la `config` de `init` ;
2. la variable d'environnement `SCRIBE_VOICE_MODELS_DIR` ;
3. le dossier par défaut `~/Documents/scribe-voice/models`.

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

- Fichier `~/Documents/scribe-voice/voice_worker.log`, ou
  `~/Documents/scribe-voice/<app_id>/voice_worker.log` après un `init` avec `app_id`.
- stdout est réservé au protocole.
- Par défaut, le texte transcrit n'est pas écrit dans le journal. Pour l'inclure, activer
  `log_transcripts` à `true` dans `config`, ou lancer le worker avec la variable
  d'environnement `SCRIBE_VOICE_LOG_TRANSCRIPTS=1` (ou `true`, `yes`, `on`). Priorité : la
  variable d'environnement force l'activation si elle vaut vrai ; sinon `log_transcripts`
  dans la config ; défaut désactivé.

## Protocole (résumé)

| Commandes (stdin) | Événements (stdout) |
|---|---|
| `init`, `preload`, `start`, `stop`, `toggle`, `confirm`, `ping`, `shutdown` | `deps`, `ready`, `status`, `model`, `recording`, `transcribing`, `transcript`, `confirmation`, `error`, `pong` |

La spécification complète est dans [docs/PROTOCOL.md](docs/PROTOCOL.md), et l'historique des
versions dans [CHANGELOG.md](CHANGELOG.md).

## Build

Windows x64, CPython **3.11** (la CI de release utilise 3.11.9) :

```powershell
.\build.ps1 -Version v1.3.0
# -> release\voice_worker.exe, release\scribe-voice-v1.3.0-win-x64.zip, release\SHA256SUMS
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