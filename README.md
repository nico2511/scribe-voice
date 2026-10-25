# scribe-voice

Worker vocal **local** de dictée (STT [faster-whisper](https://github.com/SYSTRAN/faster-whisper))
piloté par un protocole **JSON Lines** sur stdin/stdout. Partagé par
[CyberScribeNote](https://github.com/nico2511/CyberScribeNote) et Fresh Windows.

- Un seul processus permanent : PyAudio et le modèle Whisper restent en mémoire entre les dictées.
- 100 % hors ligne une fois le modèle téléchargé.
- Commandes vocales courtes « Scribe, … » fiabilisées (prompt/hotword, VAD adaptatif).

Le code (`voice_worker.py`, `voice_worker.spec`, `build_sidecar.ps1`) a été importé tel quel,
avec son historique, depuis le dossier `voice/` de CyberScribeNote.
**v1.0 = comportement strictement identique** à l'exe livré avec CyberScribeNote.

## Utilisation

Binaire Windows : télécharger `voice_worker.exe` (ou le zip) depuis les
[Releases](https://github.com/nico2511/scribe-voice/releases), vérifier le SHA-256 (voir plus bas), puis
le lancer comme sous-processus avec stdin/stdout en pipes :

```python
import json, subprocess
p = subprocess.Popen(["voice_worker.exe"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
send = lambda o: (p.stdin.write((json.dumps(o) + "\n").encode()), p.stdin.flush())
send({"cmd": "init", "config": {"language": "fr", "model_size": "small"}})
send({"cmd": "toggle"})   # démarre l'enregistrement
# ... parler ...
send({"cmd": "toggle"})   # arrête -> événements transcribing / transcript
for line in p.stdout:
    evt = json.loads(line.decode("utf-8"))
    if evt["type"] == "transcript":
        print(evt["text"]); break
send({"cmd": "shutdown"})
```

**Fresh Windows / commandes vocales (v1.1)** — mot-clé configurable et parsing côté worker :

```python
send({
    "cmd": "init",
    "config": {
        "language": "fr",
        "model_size": "small",
        "keyword": "Scribe",
        "keyword_aliases": ["scribe", "scrybe"],  # variantes ASR
        "app_id": "fresh-windows",
    },
})
# ... toggle dictée ...
# evt["type"] == "transcript" :
#   evt["text"]  -> transcription brute (inchangée pour les clients v1.0)
#   evt.get("command") -> {"keyword": "Scribe", "text": "ouvre les paramètres."} si la phrase commence par le mot-clé

send({"cmd": "confirm", "timeout": 4})  # écoute courte puis classification oui/non
# evt["type"] == "confirmation" -> {"answer": "yes"|"no"|"unknown", "text": "..."}
```

Depuis les sources : `pip install -r requirements.txt` puis `python voice_worker.py`.

- Modèles : par défaut `~/Documents/CyberScribeNote/models` (téléchargés au premier `init`
  si `offline` est false). Pour un dossier local (ex. disque D: sous Windows) :

```python
send({
    "cmd": "init",
    "config": {
        "language": "fr",
        "model_size": "small",
        "models_dir": r"D:\models\cyberscribe_models",
        "offline": True,
    },
})
```

  Équivalent côté processus : variable d'environnement `SCRIBE_VOICE_MODELS_DIR`
  (surchargée par `models_dir` dans `init`). Le worker accepte une racine de cache
  Hugging Face (`models--Systran--faster-whisper-small/...`), des dossiers plats
  (`small/`, `faster-whisper-small/`) ou un chemin direct vers un modèle CTranslate2.
  Voir [docs/PROTOCOL.md](docs/PROTOCOL.md#configuration-config).

- Journal : `~/Documents/CyberScribeNote/voice_worker.log` (ou
  `~/Documents/CyberScribeNote/<app_id>/voice_worker.log` si `app_id` est fourni).
  stdout reste réservé au protocole.

## Protocole (résumé)

| Commandes (stdin) | Événements (stdout) |
|---|---|
| `init`, `preload`, `toggle`, `confirm`, `ping`, `shutdown` | `deps`, `ready`, `status`, `model`, `recording`, `transcribing`, `transcript`, `confirmation`, `error`, `pong` |

Spécification complète : [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Build

Windows x64, CPython **3.11** (l'exe de référence utilise 3.11.9) :

```powershell
.\build.ps1 -Version v1.0.0
# -> release\voice_worker.exe, release\scribe-voice-v1.0.0-win-x64.zip, release\SHA256SUMS
```

- `requirements.txt` : dépendances d'exécution **figées** (versions relevées dans l'exe actuel).
- `requirements-build.txt` : + PyInstaller figé.
- `voice_worker.spec` : spec PyInstaller (inclut `silero_vad_v6.onnx` de faster-whisper, requis pour le VAD).
- `build_sidecar.ps1` : script historique de CyberScribeNote (copie l'exe dans `src-tauri/binaries`).

CI : `.github/workflows/ci.yml` lance les tests (Windows + Linux) à chaque push / PR ;
`.github/workflows/release.yml` construit l'exe sur un tag `v*`, le teste (ping/shutdown)
et publie `voice_worker.exe`, le zip et `SHA256SUMS` dans la release GitHub.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Aucun micro ni modèle requis : `tests/fakes/` fournit de faux `pyaudio`, `faster_whisper`
et `winsound`. Les tests de protocole lancent le vrai `voice_worker.py` en sous-processus.

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

Les builds PyInstaller ne sont pas reproductibles bit à bit : `SHA256SUMS` garantit l'intégrité
du fichier publié par la CI, pas l'égalité avec un build local.

## Licence

[MIT](LICENSE) © 2026 nico2511 (Nicolas L). Composants tiers : [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
