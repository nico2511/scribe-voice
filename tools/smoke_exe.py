"""Smoke test de l'exe construit : deps -> ready, ping -> pong, shutdown.

Usage : python tools/smoke_exe.py dist/voice_worker.exe

Test optionnel (hors réseau, modèle local) si les variables sont définies :
  SCRIBE_SMOKE_MODELS_DIR — dossier contenant un modèle faster-whisper (CTranslate2)
  SCRIBE_SMOKE_WAV — chemin d'un petit WAV mono 16 kHz (sinon un sinus 1 s est généré)

Ce test charge ``voice_worker.py`` via l'interpréteur courant (pas l'exe) : l'exe
ne propose pas de commande « transcrire un fichier » sans micro.
"""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _make_sine_wav(path: str, seconds: float = 1.0, rate: int = 16000) -> None:
    n = int(round(seconds * rate))
    frames = struct.pack(
        "<%dh" % n,
        *(int(3000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)),
    )
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)


def _optional_offline_transcribe() -> bool:
    models_dir = os.environ.get("SCRIBE_SMOKE_MODELS_DIR", "").strip()
    if not models_dir:
        print("Transcription smoke : ignorée (SCRIBE_SMOKE_MODELS_DIR non défini)")
        return True
    if not os.path.isdir(models_dir):
        print(f"Transcription smoke : ignorée (dossier introuvable : {models_dir})")
        return True

    wav_path = os.environ.get("SCRIBE_SMOKE_WAV", "").strip()
    if not wav_path:
        fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="scribe_smoke_")
        os.close(fd)
        _make_sine_wav(wav_path)
        cleanup_wav = True
    else:
        cleanup_wav = False
        if not os.path.isfile(wav_path):
            print(f"Transcription smoke : ignorée (WAV introuvable : {wav_path})")
            return True

    sys.path.insert(0, str(ROOT))
    import voice_worker as vw

    cfg = vw.sanitize_config(
        {
            "model_size": "tiny",
            "device": "cpu",
            "compute_type": "int8",
            "offline": True,
            "models_dir": models_dir,
            "language": "fr",
        }
    )
    t = vw.Transcriber.__new__(vw.Transcriber)
    t.config = cfg
    t.model = None
    t.loading = True
    t.loaded_event = __import__("threading").Event()
    t._transcribe_lock = __import__("threading").Lock()
    t._load_gen = 0
    t._load_model()
    if not t.loaded_event.wait(timeout=300):
        print("Transcription smoke : échec (timeout chargement modèle)", file=sys.stderr)
        return False
    if t.model is None:
        print("Transcription smoke : échec (modèle non chargé)", file=sys.stderr)
        return False
    result = t.transcribe(wav_path)
    if result is None:
        print("Transcription smoke : échec (transcribe a renvoyé None)", file=sys.stderr)
        return False
    print(f"Transcription smoke OK (texte {len(result)} caractères)")
    if cleanup_wav:
        try:
            os.remove(wav_path)
        except OSError:
            pass
    return True


def main() -> int:
    exe = sys.argv[1]
    proc = subprocess.run(
        [exe],
        input=b'{"cmd": "ping"}\n{"cmd": "shutdown"}\n',
        capture_output=True,
        timeout=180,
    )
    events = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
    print("exit:", proc.returncode)
    for e in events:
        print(e)
    ok = (
        proc.returncode == 0
        and len(events) >= 2
        and events[0] == {"type": "deps", "ok": True}
        and events[1].get("type") == "ready"
        and {"type": "pong"} in events
    )
    if not ok:
        print("SMOKE TEST ÉCHOUÉ", file=sys.stderr)
        print(proc.stderr.decode("utf-8", "replace"), file=sys.stderr)
        return 1
    print("SMOKE TEST OK")
    if not _optional_offline_transcribe():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
