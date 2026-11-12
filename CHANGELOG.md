# Changelog

## v1.1.0

Référence : [docs/PROTOCOL.md](docs/PROTOCOL.md) (protocole **4**). Les applications clientes
(CyberScribeNote, Fresh Windows, etc.) s'adaptent à ce contrat ; scribe-voice en est la source de vérité.

### T1 — Anti-hallucination « Scribe Scribe » et push-to-talk

Filtrage mot-clé seul, prompt Whisper, VAD adaptatif, fenêtre de démarrage toggle (~220 ms).
Commandes dédiées **start** / **stop** (idempotentes) en complément de **toggle**.

### T2 — Modèle français et hors ligne

`model_size` par défaut **small**, langue **fr**, résolution `models_dir` / `SCRIBE_VOICE_MODELS_DIR`,
mode `offline` sans téléchargement Hugging Face implicite.

### T3 — Exe sans PyAV ni codecs x264/x265

Import factice de `av` ; lecture WAV PCM directe. Tests `tests/test_pyav_free.py`.

### T4 — Mot-clé configurable, commande et confirmation

`keyword`, `keyword_aliases`, champ `command` sur `transcript`, commande **confirm**
(classification oui/non). Protocole passé à **3** sur la branche mot-clé.

### T5 — Finition v1.1 (cette release)

- **start** / **stop** idempotents pour le push-to-talk.
- **preload** n'empêche plus le traitement des autres commandes (ex. **ping** pendant le chargement).
- Journaux sans texte transcrit par défaut (`SCRIBE_VOICE_LOG_TRANSCRIPTS` ou `log_transcripts` dans `init`).
- Smoke test : `SCRIBE_SMOKE_MODEL` (défaut `small`).
- Version **1.1.0**, protocole **4** (nouvelles commandes PTT + sémantique `preload` assouplie).
