# Protocole JSON Lines — scribe-voice v1.0

Le worker est un processus permanent. Le parent (CyberScribeNote, Fresh Windows…)
lui écrit des **commandes** sur **stdin** et lit des **événements** sur **stdout**.

- Une ligne = un objet JSON, terminé par `\n`. Les lignes vides sont ignorées.
- stdout est écrit en **UTF-8** brut sur le descripteur 1 (`ensure_ascii=False`),
  y compris sous Windows (mode binaire). Lire stdout en octets puis décoder en UTF-8.
- stdin est lu en mode texte Python (encodage par défaut de la plateforme) :
  envoyer de préférence du JSON ASCII (`\uXXXX` pour les caractères non ASCII).
- stdout ne contient **que** des événements ; les journaux vont dans
  `~/Documents/CyberScribeNote/voice_worker.log` (aucun changement en v1.0).
- Les événements peuvent être émis depuis des threads : leur ordre relatif
  n'est garanti que là où c'est indiqué ci-dessous.

## Démarrage

Dès le lancement, avant toute commande :

```json
{"type": "deps", "ok": true}
{"type": "ready"}
```

Si `pyaudio` ou `faster_whisper` est introuvable :
`{"type": "deps", "ok": false, "error": "<message ImportError>"}` puis `ready`
(le worker reste à l'écoute, mais `init` échouera).

## Commandes (stdin)

| Commande | Forme | Effet |
|---|---|---|
| `init` | `{"cmd": "init", "config": {…}}` | Ouvre PyAudio (une fois), crée ou recharge le modèle Whisper en arrière-plan. Non bloquant. |
| `preload` | `{"cmd": "preload", "config": {…}}` | Comme `init`, puis **bloque** (≤ 300 s) jusqu'à la fin du chargement et émet `model`. |
| `toggle` | `{"cmd": "toggle"}` | Démarre l'enregistrement, ou l'arrête et lance la transcription. |
| `ping` | `{"cmd": "ping"}` | Répond `{"type": "pong"}`. |
| `shutdown` | `{"cmd": "shutdown"}` | Libère PyAudio et termine le processus (code 0). La fermeture de stdin (EOF) termine aussi le worker. |

Toute autre valeur de `cmd` : `{"type": "error", "message": "Commande inconnue : <cmd>"}`.
Ligne non JSON : `{"type": "error", "message": "JSON invalide : …"}`. Dans les deux cas le worker continue.

### Configuration (`config`)

Clés inconnues ignorées ; valeur invalide → valeur par défaut.

| Clé | Valeurs | Défaut |
|---|---|---|
| `language` | `auto`, `en`, `fr`, `de`, `es`, `it`, `ja`, `zh`, `nl`, `uk`, `pt`, `ru` | `fr` |
| `model_size` | `tiny`, `base`, `small`, `medium`, `large-v3` | `base` |
| `device` | `auto`, `cpu`, `cuda` (CUDA seulement si `nvidia-smi -L` voit un GPU, repli CPU) | `auto` |
| `compute_type` | `int8`, `int8_float16`, `float16`, `float32` | `int8` |
| `transcription_profile` | `fast`, `balanced`, `accurate` | `fast` |
| `max_record_seconds` | entier, borné à [0, 600] ; 0 = pas d'arrêt automatique | `90` |

Les modèles sont téléchargés (Hugging Face) dans `~/Documents/CyberScribeNote/models`.

## Événements (stdout)

| Type | Champs | Quand |
|---|---|---|
| `deps` | `ok` (bool), `error` (str, si `ok` = false) | Démarrage. |
| `ready` | — | Démarrage, après `deps`. |
| `status` | `recording` (false), `depsOk` (true) | Fin de `init` / `preload` réussi. |
| `model` | `loading` (bool), `loaded` (bool) | Début (`loading: true, loaded: false`) et fin de chargement ; `preload` en émet un de plus. Un échec peut émettre plusieurs fois `loaded: false`. |
| `recording` | `active` (bool) | `true` ~0,22 s après `toggle` (après le bip), `false` à l'arrêt. |
| `transcribing` | `active` (bool) | `true` puis `false` autour de la transcription. |
| `transcript` | `text` (str, éventuellement vide) | Toujours après `transcribing: false` ; `""` si audio vide, trop court/silencieux ou erreur. |
| `error` | `message` (str, en français) | Erreur micro, modèle, transcription, commande… |
| `pong` | — | Réponse à `ping`. |

Messages d'erreur courants : `Worker non initialisé` (toggle avant init),
`Transcription encore en cours — patientez.`, `Microphone : …`, `Micro indisponible : …`,
`Chargement modèle : …`, `Timeout chargement modèle Whisper`, `Transcription : …`.

## Séquence type d'une dictée

```
→ {"cmd":"init","config":{"language":"fr","model_size":"base"}}
← {"type":"model","loading":true,"loaded":false}
← {"type":"status","recording":false,"depsOk":true}
← {"type":"model","loading":false,"loaded":true}
→ {"cmd":"toggle"}
← {"type":"recording","active":true}
→ {"cmd":"toggle"}
← {"type":"recording","active":false}
← {"type":"transcribing","active":true}
← {"type":"transcribing","active":false}
← {"type":"transcript","text":"Scribe, corrige le texte."}
```

## Commandes vocales courtes « Scribe, … »

Pour que les ordres brefs adressés à l'assistant ne soient pas perdus :

- chaque passe Whisper reçoit `initial_prompt="Scribe."` et `hotwords="Scribe"` ;
- audio < 0,35 s ou RMS < 60 → `transcript` vide, sans appel au modèle ;
- le **VAD** (Silero) n'est activé que si l'audio dure **≥ 3,5 s**
  (`condition_on_previous_text` suit la même règle) ;
- si le résultat est vide et que l'audio dure **< 8 s**, nouvelle passe **sans VAD**,
  `condition_on_previous_text=false`, `no_speech_threshold=0.35` ;
- si la version de faster-whisper refuse `hotwords` / `without_timestamps`
  (`TypeError`), la passe est relancée sans ces deux paramètres.

Ce comportement est couvert par `tests/test_transcriber.py` et `tests/test_protocol.py`.
