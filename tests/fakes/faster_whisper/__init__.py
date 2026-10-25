"""Faux ``faster_whisper`` pour les tests : aucun modèle téléchargé.

FAKE_WHISPER (JSON) :
  {"texts": ["", "Scribe, corrige."],   # textes renvoyés appel après appel (le dernier se répète)
   "fail_load": false,                   # WhisperModel() lève une exception
   "calls_file": "/chemin/calls.jsonl"}  # chaque appel transcribe() y est journalisé (kwargs)
"""
import json
import os


def _cfg():
    try:
        return json.loads(os.environ.get("FAKE_WHISPER") or "{}")
    except ValueError:
        return {}


class _Segment:
    def __init__(self, text):
        self.text = text


class WhisperModel:
    def __init__(
        self,
        model_size,
        device="cpu",
        compute_type="int8",
        download_root=None,
        local_files_only=False,
        **kwargs,
    ):
        cfg = _cfg()
        if cfg.get("fail_load"):
            raise RuntimeError("modèle introuvable (simulé)")
        loads_file = cfg.get("loads_file")
        if loads_file:
            with open(loads_file, "a", encoding="utf-8") as fp:
                fp.write(
                    json.dumps(
                        {
                            "model": model_size,
                            "device": device,
                            "compute_type": compute_type,
                            "download_root": download_root,
                            "local_files_only": local_files_only,
                        }
                    )
                    + "\n"
                )
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.local_files_only = local_files_only
        self._texts = list(cfg.get("texts") or ["Scribe, corrige le texte."])
        self._calls_file = cfg.get("calls_file")

    def transcribe(self, audio, **kwargs):
        if self._calls_file:
            with open(self._calls_file, "a", encoding="utf-8") as fp:
                fp.write(json.dumps(kwargs) + "\n")
        text = self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        segments = [_Segment(" " + text)] if text else []
        return iter(segments), {"language": kwargs.get("language")}
