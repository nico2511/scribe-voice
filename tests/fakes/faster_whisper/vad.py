"""Faux VAD Silero pour les tests (variable d'environnement FAKE_VAD, JSON).

Exemples :
  FAKE_VAD='{"has_speech": false}'  -> aucune parole
  FAKE_VAD='{"raise": true}'        -> échec simulé (le worker assume la parole)
"""
import json
import os


def _cfg():
    try:
        return json.loads(os.environ.get("FAKE_VAD") or "{}")
    except ValueError:
        return {}


def get_speech_timestamps(audio, *args, **kwargs):
    cfg = _cfg()
    if cfg.get("raise"):
        raise RuntimeError(cfg.get("message") or "VAD simulé en échec")
    if "has_speech" in cfg:
        return [{"start": 0, "end": 100}] if cfg["has_speech"] else []
    # Par défaut : parole détectée (rétrocompatible avec les tests existants).
    return [{"start": 0, "end": max(1, len(audio) - 1)}]
