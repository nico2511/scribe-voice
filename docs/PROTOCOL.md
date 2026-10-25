# Protocole JSON Lines — scribe-voice v1.1

Le worker est un processus permanent. Le parent (CyberScribeNote, Fresh Windows…)
lui écrit des **commandes** sur **stdin** et lit des **événements** sur **stdout**.

- Une ligne = un objet JSON, terminé par `\n`. Les lignes vides sont ignorées.
- stdout est écrit en **UTF-8** brut sur le descripteur 1 (`ensure_ascii=False`),
  y compris sous Windows (mode binaire). Lire stdout en octets puis décoder en UTF-8.
- stdin est lu en mode texte Python (encodage par défaut de la plateforme) :
  envoyer de préférence du JSON ASCII (`\uXXXX` pour les caractères non ASCII).
- stdout ne contient **que** des événements ; les journaux vont dans un fichier
  `voice_worker.log` (voir ci-dessous). Aucun dossier n'est créé à l'import du module.
- Les événements peuvent être émis depuis des threads : leur ordre relatif
  n'est garanti que là où c'est indiqué ci-dessous.

## Démarrage

Dès le lancement, avant toute commande :

```json
{"type": "deps", "ok": true}
{"type": "ready", "version": "1.1.0-dev", "protocol": 3}
```

- `version` : version sémantique du worker (chaîne).
- `protocol` : entier de version du contrat JSON (v1.0 implicite = pas de champs ;
  v1.1 modèles / hors ligne = `2` ; v1.1 mot-clé / commandes / confirmation = `3`).
  Les clients v1.0 peuvent ignorer les champs supplémentaires (`command` sur `transcript`,
  événement `confirmation`, etc.).

**Pourquoi `protocol` 3 ?** Les clients qui ne comprennent pas `confirm` ni `command`
peuvent continuer à lire uniquement `transcript.text` ; le bump signale toutefois
des capacités nouvelles (commande stdin `confirm`, champ optionnel `command`).

Si `pyaudio` ou `faster_whisper` est introuvable :
`{"type": "deps", "ok": false, "error": "<message ImportError>"}` puis `ready`
(le worker reste à l'écoute, mais `init` échouera).

## Commandes (stdin)

| Commande | Forme | Effet |
|---|---|---|
| `init` | `{"cmd": "init", "config": {…}}` | Ouvre PyAudio (une fois), crée ou recharge le modèle Whisper en arrière-plan. Non bloquant. |
| `preload` | `{"cmd": "preload", "config": {…}}` | Comme `init`, puis **bloque** (≤ 300 s) jusqu'à la fin du chargement et émet `model`. |
| `toggle` | `{"cmd": "toggle"}` | Démarre l'enregistrement, ou l'arrête et lance la transcription. |
| `confirm` | `{"cmd": "confirm", "timeout": 4}` | Écoute micro pendant `timeout` secondes (défaut **4**, borné à [0,5 ; 30]), transcrit, émet `confirmation`. Non bloquant sur stdin (traitement en arrière-plan). |
| `ping` | `{"cmd": "ping"}` | Répond `{"type": "pong"}`. |
| `shutdown` | `{"cmd": "shutdown"}` | Libère PyAudio et termine le processus (code 0). La fermeture de stdin (EOF) termine aussi le worker. |

Toute autre valeur de `cmd` : `{"type": "error", "message": "Commande inconnue : <cmd>"}`.
Ligne non JSON : `{"type": "error", "message": "JSON invalide : …"}`. Dans les deux cas le worker continue.

### Configuration (`config`)

Clés inconnues ignorées ; valeur invalide → valeur par défaut.

| Clé | Valeurs | Défaut |
|---|---|---|
| `language` | `auto`, `en`, `fr`, `de`, `es`, `it`, `ja`, `zh`, `nl`, `uk`, `pt`, `ru` | `fr` |
| `model_size` | `tiny`, `base`, `small`, `medium`, `large-v3` | `small` |
| `device` | `auto`, `cpu`, `cuda` (CUDA seulement si `nvidia-smi -L` voit un GPU, repli CPU) | `auto` |
| `compute_type` | `int8`, `int8_float16`, `float16`, `float32` | `int8` |
| `transcription_profile` | `fast`, `balanced`, `accurate` | `fast` |
| `max_record_seconds` | entier, borné à [0, 600] ; 0 = pas d'arrêt automatique | `90` |
| `models_dir` | chemin absolu ou relatif (voir résolution ci-dessous) | `null` (voir env.) |
| `offline` | booléen : `true` → `local_files_only` (aucun téléchargement HF) | `false` |
| `app_id` | identifiant court (journal séparé par application) | `null` |
| `keyword` | mot-clé de commande vocale (début de phrase) | `Scribe` |
| `keyword_aliases` | liste de variantes ASR (ex. fautes de transcription) | `[]` |

Le `initial_prompt` Whisper et le filtre « mot-clé seul » (anti-hallucination) sont
dérivés de `keyword` (prompt = `« {keyword}. »`). Les alias servent au **parsing**
de `transcript.command`, pas au prompt.

**Dossier des modèles**

- Variable d'environnement : `SCRIBE_VOICE_MODELS_DIR` (chemin du dossier racine ou d'un modèle CT2).
- Priorité : `config.models_dir` **>** `SCRIBE_VOICE_MODELS_DIR` **>** défaut
  `~/Documents/CyberScribeNote/models` (téléchargements Hugging Face si `offline` = false).

**Résolution** (ordre, pour un `model_size` donné) :

1. Si `models_dir` pointe déjà sur un dossier CTranslate2 (`model.bin` ou `model.bin.index`),
   ce chemin est chargé tel quel (indépendamment de `model_size`).
2. Sinon, sous la racine `models_dir` :
   - dossiers plats : `{model_size}/`, `faster-whisper-{model_size}/`, `whisper-{model_size}/` ;
   - cache Hugging Face : `models--Systran--faster-whisper-{model_size}/snapshots/<hash>/`
     (également sous `hub/` si présent).
3. Si `offline` = true et aucun chemin local valide : événement `error` explicite, pas de téléchargement.
4. Si `offline` = false et racine configurée sans correspondance locale : `model_size` est passé à
   faster-whisper avec `download_root` = cette racine (comportement HF habituel).

**Journal**

- Par défaut : `~/Documents/CyberScribeNote/voice_worker.log`.
- Avec `app_id` : `~/Documents/CyberScribeNote/<app_id>/voice_worker.log`.
- Le fichier est créé au démarrage du worker (`main`), pas à l'import du module.

## Événements (stdout)

| Type | Champs | Quand |
|---|---|---|
| `deps` | `ok` (bool), `error` (str, si `ok` = false) | Démarrage. |
| `ready` | `version` (str), `protocol` (int) | Démarrage, après `deps`. |
| `status` | `recording` (false), `depsOk` (true) | Fin de `init` / `preload` réussi. |
| `model` | `loading` (bool), `loaded` (bool) | Début (`loading: true, loaded: false`) et fin de chargement ; `preload` en émet un de plus. Un échec peut émettre plusieurs fois `loaded: false`. |
| `recording` | `active` (bool) | `true` ~0,22 s après `toggle` (après le bip), `false` à l'arrêt. |
| `transcribing` | `active` (bool) | `true` puis `false` autour de la transcription. |
| `transcript` | `text` (str), `command` (objet, **optionnel**) | Toujours après `transcribing: false` ; `""` si audio vide, trop court/silencieux ou erreur. `command` présent **seulement** si la phrase commence par `keyword` ou un alias (position 0, casse / accents / ponctuation de tête ignorés) : `{"keyword":"<mot-clé canonique>","text":"<consigne sans le mot-clé>"}`. Le champ `text` du transcript reste la transcription brute (rétrocompat v1.0). |
| `confirmation` | `answer` (`yes` \| `no` \| `unknown`), `text` (str) | Après `confirm` : transcription de la fenêtre micro, puis classification oui/non (français). Le worker **n'exécute aucune action** ; l'application décide. |
| `error` | `message` (str, en français) | Erreur micro, modèle, transcription, commande… |
| `pong` | — | Réponse à `ping`. |

Messages d'erreur courants : `Worker non initialisé` (toggle avant init),
`Transcription encore en cours — patientez.`, `Confirmation en cours — patientez.`,
`Confirmation impossible : enregistrement dictée en cours.`,
`Confirmation impossible : transcription dictée en cours.`, `Microphone : …`, `Micro indisponible : …`,
`Chargement modèle : …` (dossier absent, modèle introuvable en hors ligne, etc.),
`Timeout chargement modèle Whisper`, `Transcription : …`.

## Séquence type d'une dictée

```
→ {"cmd":"init","config":{"language":"fr","model_size":"small"}}
← {"type":"model","loading":true,"loaded":false}
← {"type":"status","recording":false,"depsOk":true}
← {"type":"model","loading":false,"loaded":true}
→ {"cmd":"toggle"}
← {"type":"recording","active":true}
→ {"cmd":"toggle"}
← {"type":"recording","active":false}
← {"type":"transcribing","active":true}
← {"type":"transcribing","active":false}
← {"type":"transcript","text":"Scribe, corrige le texte.","command":{"keyword":"Scribe","text":"corrige le texte."}}
```

### Confirmation (`confirm`)

```
→ {"cmd":"confirm","timeout":3}
← {"type":"confirmation","answer":"yes","text":"oui"}
```

Réponses reconnues (liste non exhaustive, normalisation casse / accents) :

- **yes** : `oui`, `ouais`, `d'accord`, `ok`, `confirme`, `vas-y`, `allez-y`, `c'est bon`, …
- **no** : `non`, `annule`, `stop`, `arrête`, `nan`, …
- **unknown** : tout le reste (y compris silence ou phrase hors liste).

Pendant un enregistrement ou une transcription dictée (`toggle`), `confirm` renvoie
`error` et n'ouvre pas le micro. Pendant une confirmation, `toggle` renvoie
`Confirmation en cours — patientez.`

## Commandes vocales courtes « Scribe, … »

Pour que les ordres brefs adressés à l'assistant ne soient pas perdus, sans
halluciner le mot-clé sur le silence :

- chaque passe Whisper reçoit `initial_prompt="« {keyword}. »"` (sans `hotwords`) ;
- audio < 0,35 s ou RMS < 60 → `transcript` vide, sans appel au modèle ;
- si l'audio dure **< 8 s**, une **porte VAD** (Silero via `faster_whisper.vad`,
  détection seulement sur le PCM) doit détecter de la parole ; sinon `transcript`
  vide sans passe Whisper ;
- le **VAD Whisper** n'est activé que si l'audio dure **≥ 3,5 s**
  (`condition_on_previous_text` suit la même règle) ;
- sur les clips **< 3,5 s**, les segments dont `no_speech_prob > 0,6` sont ignorés ;
- si le texte final ne contient que le mot-clé (ou un alias, casse / accents ignorés),
  `transcript` vide ;
- si la phrase **commence** par le mot-clé ou un alias, `transcript.command` est ajouté
  (ex. « Scribe, corrige » → `command.text` = `corrige` ; « le scribe corrige » → pas de `command`) ;
- si le résultat est vide et que l'audio dure **< 8 s**, nouvelle passe **sans VAD**,
  `condition_on_previous_text=false`, `no_speech_threshold=0.35` ;
- si la version de faster-whisper refuse `without_timestamps` (`TypeError`),
  la passe est relancée sans ce paramètre ;
- un second `toggle` reçu pendant le délai de démarrage (~220 ms) **annule**
  l'enregistrement : `recording` `active:false` puis `transcript` vide, sans
  `recording` `active:true` résiduel.

Ce comportement est couvert par `tests/test_transcriber.py` et `tests/test_protocol.py`.
La résolution des modèles et le mode hors ligne sont couverts par `tests/test_models.py`.
