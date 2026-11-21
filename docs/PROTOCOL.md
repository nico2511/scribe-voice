# Protocole JSON Lines de scribe-voice (protocole 4)

Le worker est un processus permanent. L'application cliente (le « parent ») lui écrit des
**commandes** sur **stdin** et lit des **événements** sur **stdout**.

- Chaque ligne contient un objet JSON et se termine par `\n`. Les lignes vides sont ignorées.
- stdout est écrit en **UTF-8** brut sur le descripteur 1 (`ensure_ascii=False`), y compris
  sous Windows, où stdout passe en mode binaire. Il faut lire stdout en octets, puis le décoder en UTF-8.
- stdin est lu en mode texte Python, avec l'encodage par défaut de la plateforme. Il vaut mieux
  envoyer du JSON ASCII, avec `\uXXXX` pour les caractères non ASCII.
- stdout ne contient **que** des événements. Les journaux vont dans le fichier `voice_worker.log`
  (voir plus bas). L'import du module ne crée aucun dossier.
- Des événements peuvent être émis depuis plusieurs threads. Leur ordre relatif n'est garanti
  que là où ce document l'indique.

## Démarrage

Dès le lancement, avant toute commande :

```json
{"type": "deps", "ok": true}
{"type": "ready", "version": "1.1.1", "protocol": 4}
```

- `version` : version sémantique du worker (chaîne).
- `protocol` : version entière du contrat JSON. Les clients plus anciens peuvent ignorer les
  champs et commandes qu'ils ne gèrent pas. L'historique des numéros est le suivant :
  - pas de champ `protocol` : v1.0 ;
  - `2` : résolution des modèles et mode hors ligne ;
  - `3` : mot-clé, champ `command` et commande `confirm` ;
  - `4` : commandes `start` et `stop`, et `preload` traité en arrière-plan.

Si `pyaudio`, `numpy` ou `faster_whisper` ne peut pas être importé, le worker émet
`{"type": "deps", "ok": false, "error": "<message ImportError>"}`, puis `ready`. Il reste à
l'écoute, mais `init` échouera.

## Commandes (stdin)

| Commande | Forme | Effet |
|---|---|---|
| `init` | `{"cmd": "init", "config": {…}}` | Applique la configuration, ouvre PyAudio (une seule fois), puis crée le modèle Whisper ou le recharge si `model_size`, `device`, `compute_type`, `models_dir` ou `offline` ont changé. Le chargement se fait dans un thread : la commande rend la main tout de suite et émet `status`. |
| `preload` | `{"cmd": "preload", "config": {…}}` | Fait comme `init`, puis attend la fin du chargement en arrière-plan, au plus 300 s, et émet un événement `model` final avec `loaded` à true ou false. Pendant ce temps, les autres commandes, par exemple `ping`, sont traitées. |
| `start` | `{"cmd": "start"}` | Démarre l'enregistrement. Commande **idempotente** : si un enregistrement est déjà actif ou en train de démarrer, le worker renvoie `recording` `active:true` sans en lancer un second. |
| `stop` | `{"cmd": "stop"}` | Arrête l'enregistrement et lance la transcription. Commande **idempotente** : si rien n'enregistre, le worker renvoie `recording` `active:false` sans `transcript`. Pendant le délai de démarrage (~220 ms), elle annule le démarrage : `recording` `active:false`, sans `transcript`. |
| `toggle` | `{"cmd": "toggle"}` | Démarre l'enregistrement, ou l'arrête et lance la transcription. Pendant le délai de démarrage, elle annule : `recording` `active:false`, puis `transcript` vide. |
| `confirm` | `{"cmd": "confirm", "timeout": 4}` | Écoute le micro pendant `timeout` secondes (4 par défaut, valeur bornée à [0,5 ; 30]), transcrit, puis émet `confirmation`. Le traitement se fait en arrière-plan. |
| `ping` | `{"cmd": "ping"}` | Répond `{"type": "pong"}`. |
| `shutdown` | `{"cmd": "shutdown"}` | Libère PyAudio et termine le processus. La fermeture de stdin (EOF) termine aussi le worker. |

Une valeur de `cmd` inconnue produit `{"type": "error", "message": "Commande inconnue : <cmd>"}`.
Une ligne qui n'est pas du JSON valide produit `{"type": "error", "message": "JSON invalide : …"}`.
Une ligne JSON valide dont la racine n'est pas un objet (tableau, nombre, chaîne, `null`…) produit
`{"type": "error", "message": "JSON invalide : un objet JSON est attendu"}`. Dans tous ces cas, le
worker continue.

Une exception dans le traitement d'une commande produit `{"type": "error", "message": "Worker : …"}`.

### Configuration (`config`)

Les clés inconnues sont ignorées et une valeur invalide est remplacée par la valeur par défaut.
La configuration complète est appliquée à chaque `init` ou `preload` : une clé absente reprend sa
valeur par défaut, et non la valeur précédente.

| Clé | Valeurs | Défaut |
|---|---|---|
| `language` | `auto` (détection), `en`, `fr`, `de`, `es`, `it`, `ja`, `zh`, `nl`, `uk`, `pt`, `ru` | `fr` |
| `model_size` | `tiny`, `base`, `small`, `medium`, `large-v3` | `small` |
| `device` | `auto`, `cpu`, `cuda` | `auto` |
| `compute_type` | `int8`, `int8_float16`, `float16`, `float32` | `int8` |
| `transcription_profile` | `fast`, `balanced`, `accurate` | `fast` |
| `max_record_seconds` | entier borné à [0, 600] ; 0 désactive l'arrêt automatique | `90` |
| `models_dir` | chemin (`~` développé, converti en chemin absolu) | `null` (voir plus bas) |
| `offline` | booléen ; `true` interdit tout téléchargement (`local_files_only`) | `false` |
| `app_id` | identifiant court ; les caractères hors `[\w.-]` sont remplacés par `_` (120 caractères au plus) | `null` |
| `keyword` | mot-clé attendu en début de phrase (120 caractères au plus) | `Scribe` |
| `keyword_aliases` | liste de variantes du mot-clé (32 au plus, 120 caractères chacune) | `[]` |
| `log_transcripts` | booléen : journalise les 180 premiers caractères de chaque transcription de dictée | `false` |

Les booléens acceptent aussi les chaînes `1`, `true`, `yes` et `on` (casse indifférente).

**Choix du matériel** : `cuda` n'est utilisé que si `nvidia-smi -L` détecte un GPU. Sinon, le
worker passe sur le CPU. Sur CUDA, `int8` devient `int8_float16`, et si le chargement CUDA échoue,
le worker réessaie sur CPU en `int8`. Sur CPU, `int8_float16` et `float16` deviennent `int8`.

**Profils** (`transcription_profile`) :

| Profil | `beam_size` | `best_of` | `no_speech_threshold` | `log_prob_threshold` |
|---|---|---|---|---|
| `fast` | 1 | 1 | 0,6 | -1,0 |
| `balanced` | 3 | 2 | 0,65 | -1,2 |
| `accurate` | 5 | 3 | 0,7 | -1,0 |

**Dossier des modèles**

- Variable d'environnement : `SCRIBE_VOICE_MODELS_DIR`, qui désigne le dossier racine ou
  directement un modèle CTranslate2.
- Ordre de priorité : `config.models_dir`, puis `SCRIBE_VOICE_MODELS_DIR`, puis le dossier par
  défaut `~/Documents/CyberScribeNote/models`. Le dossier par défaut sert de destination aux
  téléchargements Hugging Face ; il n'est pas utilisé en mode hors ligne.

**Résolution** (dans cet ordre, pour un `model_size` donné) :

1. Si aucun dossier n'est configuré : avec `offline` à true, le worker émet l'erreur
   `Mode hors ligne : indiquez models_dir ou SCRIBE_VOICE_MODELS_DIR.`. Sinon, faster-whisper
   charge `model_size` avec le dossier par défaut comme `download_root`.
2. Si le dossier configuré n'existe pas, le worker émet l'erreur `Dossier modèles introuvable : …`,
   quelle que soit la valeur d'`offline`.
3. Si le dossier est lui-même un modèle CTranslate2 (`model.bin` ou `model.bin.index`), il est
   chargé tel quel, sans tenir compte de `model_size`.
4. Sinon, le worker cherche sous ce dossier :
   - les dossiers plats `{model_size}/`, `faster-whisper-{model_size}/` et `whisper-{model_size}/` ;
   - le cache Hugging Face `models--Systran--faster-whisper-{model_size}/snapshots/<hash>/`,
     aussi sous `hub/` s'il existe.
5. Si rien ne correspond : avec `offline` à true, le worker émet l'erreur
   `Modèle « … » introuvable dans …` sans rien télécharger. Avec `offline` à false,
   faster-whisper charge `model_size` avec ce dossier comme `download_root`.

Les erreurs de résolution sont émises sous la forme `Chargement modèle : <message>`, suivies de
`model` avec `loaded:false`.

**Journal**

- Le fichier `~/Documents/CyberScribeNote/voice_worker.log` est créé au démarrage du worker,
  pas à l'import du module.
- Après un `init` qui contient `app_id`, le journal est écrit dans
  `~/Documents/CyberScribeNote/<app_id>/voice_worker.log`.
- **Vie privée** : par défaut, le journal ne contient pas le texte transcrit, seulement des
  métadonnées comme la durée, le RMS ou le nombre de caractères. Pour le débogage, activer
  `log_transcripts` à `true` dans `config`, ou la variable d'environnement
  `SCRIBE_VOICE_LOG_TRANSCRIPTS=1` (ou `true`, `yes`, `on`), qui ajoute les 180 premiers
  caractères de chaque transcription de dictée. Priorité : la variable d'environnement force
  l'activation si elle vaut vrai ; sinon `log_transcripts` dans la config ; défaut désactivé.

**Fichiers temporaires** : chaque enregistrement est écrit dans un WAV temporaire (16 kHz, mono,
int16) dans le dossier temporaire du système. Ce fichier est supprimé après la transcription.

## Événements (stdout)

| Type | Champs | Quand |
|---|---|---|
| `deps` | `ok` (bool), `error` (str, si `ok` vaut false) | Au démarrage. |
| `ready` | `version` (str), `protocol` (int) | Au démarrage, après `deps`. |
| `status` | `recording` (false), `depsOk` (true) | Quand `init` ou `preload` est accepté, sans attendre la fin du chargement. Il n'est pas émis si le micro ne peut pas être ouvert. |
| `model` | `loading` (bool), `loaded` (bool) | Au début du chargement (`loading:true, loaded:false`), puis à la fin. Si la configuration du modèle n'a pas changé et que le modèle est déjà chargé, `init` émet directement `loading:false, loaded:true`. `preload` en émet un de plus à la fin de son attente. En cas d'échec, `loaded:false` peut être émis plusieurs fois. |
| `recording` | `active` (bool) | `true` environ 0,22 s après `start` ou `toggle`. `false` à l'arrêt : `stop`, `toggle` ou arrêt automatique après `max_record_seconds`. |
| `transcribing` | `active` (bool) | `true`, puis `false`, autour de la transcription. |
| `transcript` | `text` (str), `command` (objet, optionnel) | Après `transcribing:false`, ou directement si aucun audio n'a été capté. `text` est vide si l'audio est vide, trop court ou silencieux, si la transcription ne contient que le mot-clé, ou en cas d'erreur. Voir [Mot-clé](#mot-clé-et-champ-command) pour `command`. |
| `confirmation` | `answer` (`yes`, `no` ou `unknown`), `text` (str) | Après `confirm`. |
| `error` | `message` (str, en français) | En cas d'erreur de micro, de modèle, de transcription ou de commande. |
| `pong` | — | En réponse à `ping`. |

Un son est joué au début (600 Hz) et à la fin (400 Hz) de l'enregistrement, avec `winsound` et
donc seulement sous Windows. Il n'est pas joué pendant `confirm`.

Messages d'erreur émis par le worker :

| Message | Cause |
|---|---|
| `Worker non initialisé` | `start`, `stop`, `toggle` ou `confirm` avant un `init` réussi |
| `Transcription encore en cours — patientez.` | `start` ou `toggle` pendant une transcription |
| `Confirmation en cours — patientez.` | `start` ou `toggle` pendant un `confirm` |
| `Confirmation déjà en cours — patientez.` | `confirm` pendant un `confirm` |
| `Confirmation impossible : enregistrement dictée en cours.` | `confirm` pendant un enregistrement ou son démarrage |
| `Confirmation impossible : transcription dictée en cours.` | `confirm` pendant une transcription |
| `Micro indisponible : …` | échec de l'ouverture de PyAudio à l'`init` |
| `Microphone : …` | échec de l'ouverture du flux micro |
| `Enregistrement WAV : …` / `Lecture WAV : …` | échec d'écriture ou de lecture du WAV temporaire |
| `Chargement modèle : …` | erreur de résolution ou de chargement du modèle |
| `Timeout chargement modèle Whisper` | modèle toujours pas chargé 120 s après la demande de transcription |
| `Transcription : …` / `Confirmation : …` | exception pendant la transcription |
| `Commande inconnue : …` / `JSON invalide : …` / `Worker : …` / `Worker fatal : …` | voir [Commandes](#commandes-stdin) |

## Séquences types

Avec `start` / `stop` :

```
→ {"cmd":"init","config":{"language":"fr","model_size":"small"}}
← {"type":"model","loading":true,"loaded":false}
← {"type":"status","recording":false,"depsOk":true}
← {"type":"model","loading":false,"loaded":true}
→ {"cmd":"start"}
← {"type":"recording","active":true}
→ {"cmd":"start"}
← {"type":"recording","active":true}
→ {"cmd":"stop"}
← {"type":"recording","active":false}
← {"type":"transcribing","active":true}
← {"type":"transcribing","active":false}
← {"type":"transcript","text":"Scribe, corrige le texte.","command":{"keyword":"Scribe","text":"corrige le texte."}}
→ {"cmd":"stop"}
← {"type":"recording","active":false}
```

Les deux premiers événements `model` et `status` sont émis par des threads différents, donc leur
ordre relatif peut varier. Un second `stop` sans enregistrement en cours ne produit pas de `transcript`.

Avec `toggle` :

```
→ {"cmd":"toggle"}
← {"type":"recording","active":true}
→ {"cmd":"toggle"}
← {"type":"recording","active":false}
← {"type":"transcribing","active":true}
← {"type":"transcribing","active":false}
← {"type":"transcript","text":"…"}
```

### Confirmation (`confirm`)

```
→ {"cmd":"confirm","timeout":3}
← {"type":"confirmation","answer":"yes","text":"oui"}
```

Le texte est d'abord normalisé : minuscules, accents supprimés, ponctuation remplacée par des
espaces. Il est ensuite classé `no` s'il est égal à une expression « non » ou commence par
l'une d'elles suivie d'un espace. Sinon, il est classé `yes` selon la même règle avec les
expressions « oui ». Tout le reste, y compris un texte vide, donne `unknown`. Les expressions
« non » sont testées en premier. Les listes, en français, sont dans `voice_keyword.py` :

- **yes** : `oui`, `ouais`, `oué`, `oué oué`, `d accord`, `daccord`, `ok`, `okay`, `confirme`,
  `confirmé`, `confirmer`, `vas y`, `vas-y`, `allez y`, `allez-y`, `c est bon`, `c est ça`,
  `affirmatif`, `exact`, `exactement` ;
- **no** : `non`, `nan`, `nop`, `annule`, `annulé`, `annuler`, `stop`, `arrête`, `arrete`,
  `arrêter`, `arreter`, `negatif`, `négatif`, `pas ça`, `pas ca`.

La transcription d'une confirmation utilise le profil `fast`, sans VAD, avec
`no_speech_threshold=0.35`. Un audio de moins de 0,25 s, ou dont le RMS est inférieur à 60,
donne un texte vide. Aucun filtre de mot-clé n'est appliqué. Si aucun audio n'a été capté, le
worker émet `confirmation` avec `answer:"unknown"` et `text:""`.

## Mot-clé et champ `command`

- Le champ `command` est ajouté à `transcript` **seulement** si la transcription commence par
  `keyword` ou par un alias, suivi d'autre chose qu'une lettre ou un chiffre et d'un texte non vide.
  La casse, les accents, ainsi que les espaces et la ponctuation en tête, sont ignorés.
  Exemples : « Scribe, corrige » donne `command.text` = `corrige` ; « le scribe corrige » ne
  donne pas de `command`.
- `command.keyword` vaut toujours la forme canonique de `keyword`, même quand c'est un alias qui
  a été reconnu. `command.text` contient la suite de la phrase, sans la ponctuation qui suit le mot-clé.
- Le champ `text` de `transcript` reste la transcription brute.
- Si la transcription ne contient que le mot-clé ou des alias, éventuellement répétés et séparés
  par de la ponctuation, `transcript.text` est vide.
- Chaque passe Whisper reçoit `initial_prompt="{keyword}."` (par exemple `Scribe.`). Les alias ne
  servent qu'à la détection de `command` et au filtre « mot-clé seul », pas au prompt.

## Traitement de l'audio d'une dictée

- Si l'audio dure moins de 0,35 s ou si son RMS est inférieur à 60, `transcript` est vide et le
  modèle n'est pas appelé.
- Si l'audio dure moins de 8 s, une porte VAD (Silero via `faster_whisper.vad`) doit détecter de
  la parole. Sinon, `transcript` est vide et aucune passe Whisper n'a lieu. Si cette détection
  échoue, l'audio est traité comme de la parole.
- Le VAD de Whisper (`vad_filter`, avec les paramètres du profil) et `condition_on_previous_text`
  ne sont activés que si l'audio dure au moins 3,5 s.
- Sur les clips de moins de 3,5 s, les segments dont `no_speech_prob` dépasse 0,6 sont ignorés.
- Si le résultat est vide et que l'audio dure moins de 8 s, une seconde passe a lieu sans VAD,
  avec `condition_on_previous_text=false` et `no_speech_threshold=0.35`.
- Si la version de faster-whisper refuse `without_timestamps` (`TypeError`), la passe est relancée
  sans ce paramètre.
- L'audio est passé à faster-whisper sous forme de tableau NumPy float32. PyAV et `decode_audio`
  ne sont pas utilisés.

Tests associés : `tests/test_transcriber.py`, `tests/test_protocol.py`, `tests/test_keyword.py`,
`tests/test_models.py`, `tests/test_config.py` et `tests/test_logging_privacy.py`.
