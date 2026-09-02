#!/usr/bin/env python3
"""
CyberScribeNote — Voice worker (sidecar)
Basé sur la logique CyberScribe : PyAudio + faster-whisper.
Communication JSON ligne par ligne via stdin/stdout.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import wave
from typing import Any

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "CyberScribeNote", "models"
)
os.makedirs(MODELS_DIR, exist_ok=True)

VALID_LANGUAGES = {
    "auto", "en", "fr", "de", "es", "it", "ja", "zh", "nl", "uk", "pt", "ru",
}
VALID_MODELS = {"tiny", "base", "small", "medium", "large-v3"}
VALID_DEVICES = {"auto", "cpu", "cuda"}
VALID_COMPUTE = {"int8", "int8_float16", "float16", "float32"}
VALID_PROFILES = {"fast", "balanced", "accurate"}
MIN_RECORD_CHUNKS = 4

DEFAULT_CONFIG = {
    "language": "fr",
    "model_size": "base",
    "device": "auto",
    "compute_type": "int8",
    "transcription_profile": "fast",
    "max_record_seconds": 25,
}

PROFILE_PRESETS = {
    "fast": {
        "beam_size": 1,
        "best_of": 1,
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": 250},
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.7,
        "log_prob_threshold": -2.0,
    },
    "balanced": {
        "beam_size": 3,
        "best_of": 2,
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": 400},
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.75,
        "log_prob_threshold": -1.5,
    },
    "accurate": {
        "beam_size": 5,
        "best_of": 3,
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": 500},
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.8,
        "log_prob_threshold": -1.0,
    },
}


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def sanitize_config(data: dict[str, Any] | None) -> dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    if not isinstance(data, dict):
        return cfg
    for key in DEFAULT_CONFIG:
        if key in data:
            cfg[key] = data[key]
    language = str(cfg.get("language") or "fr").lower()
    cfg["language"] = language if language in VALID_LANGUAGES else "fr"
    model_size = str(cfg.get("model_size") or "base").lower()
    cfg["model_size"] = model_size if model_size in VALID_MODELS else "base"
    device = str(cfg.get("device") or "auto").lower()
    cfg["device"] = device if device in VALID_DEVICES else "auto"
    compute_type = str(cfg.get("compute_type") or "int8").lower()
    cfg["compute_type"] = compute_type if compute_type in VALID_COMPUTE else "int8"
    profile = str(cfg.get("transcription_profile") or "fast").lower()
    cfg["transcription_profile"] = profile if profile in VALID_PROFILES else "fast"
    try:
        max_seconds = int(cfg.get("max_record_seconds"))
    except (TypeError, ValueError):
        max_seconds = DEFAULT_CONFIG["max_record_seconds"]
    cfg["max_record_seconds"] = max(0, min(max_seconds, 600))
    return cfg


def detect_nvidia_gpu() -> bool:
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.returncode == 0 and "GPU" in result.stdout
    except Exception:
        return False


def check_deps() -> tuple[bool, str | None]:
    try:
        import pyaudio  # noqa: F401
        from faster_whisper import WhisperModel  # noqa: F401
        return True, None
    except ImportError as exc:
        return False, str(exc)


class AudioRecorder:
    def __init__(self) -> None:
        import pyaudio

        self.pyaudio = pyaudio
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.frames: list[bytes] = []
        self.is_recording = False
        self.rate = 16000
        self.chunk = 1024
        self._lock = threading.Lock()

    def start(self) -> bool:
        if self.is_recording:
            return True
        with self._lock:
            self.frames = []
        self.is_recording = True
        try:
            self.stream = self.audio.open(
                format=self.pyaudio.paInt16,
                channels=1,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk,
            )
            threading.Thread(target=self._record_loop, daemon=True).start()
            return True
        except Exception as exc:
            self.is_recording = False
            self.stream = None
            emit({"type": "error", "message": f"Microphone : {exc}"})
            return False

    def _record_loop(self) -> None:
        while self.is_recording and self.stream:
            try:
                data = self.stream.read(self.chunk, exception_on_overflow=False)
                with self._lock:
                    self.frames.append(data)
            except Exception:
                break

    def stop(self) -> str | None:
        if not self.is_recording:
            return None
        self.is_recording = False
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
        except Exception:
            pass
        with self._lock:
            frames = list(self.frames)
            self.frames = []
        if not frames or len(frames) < MIN_RECORD_CHUNKS:
            emit(
                {
                    "type": "error",
                    "message": "Enregistrement trop court — maintenez la touche dictée un peu plus longtemps.",
                }
            )
            return None
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="csnote_")
        os.close(fd)
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(self.audio.get_sample_size(self.pyaudio.paInt16))
                wf.setframerate(self.rate)
                wf.writeframes(b"".join(frames))
            return path
        except Exception as exc:
            emit({"type": "error", "message": f"Enregistrement WAV : {exc}"})
            try:
                os.remove(path)
            except Exception:
                pass
            return None

    def close(self) -> None:
        self.is_recording = False
        try:
            self.audio.terminate()
        except Exception:
            pass


class Transcriber:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.model = None
        self.loading = False
        self.loaded_event = threading.Event()
        self._lock = threading.Lock()
        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self) -> None:
        from faster_whisper import WhisperModel

        self.loading = True
        emit({"type": "model", "loading": True, "loaded": False})
        try:
            model_size = self.config.get("model_size")
            device_pref = (self.config.get("device") or "auto").lower()
            compute_pref = (self.config.get("compute_type") or "int8").lower()
            has_nvidia = detect_nvidia_gpu()

            if device_pref == "auto":
                device = "cuda" if has_nvidia else "cpu"
            else:
                device = device_pref

            if device == "cuda" and not has_nvidia:
                device = "cpu"

            if device == "cuda":
                compute_type = "int8_float16" if compute_pref == "int8" else compute_pref
            else:
                compute_type = "int8" if compute_pref in ("int8_float16", "float16") else compute_pref

            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                download_root=MODELS_DIR,
            )
            emit({"type": "model", "loading": False, "loaded": True})
        except Exception as exc:
            self.model = None
            emit({"type": "error", "message": f"Chargement modèle : {exc}"})
            emit({"type": "model", "loading": False, "loaded": False})
        finally:
            self.loaded_event.set()
            self.loading = False

    def reload(self, config: dict[str, Any]) -> None:
        def _reload() -> None:
            with self._lock:
                self.config = config
                self.model = None
                self.loaded_event.clear()
                self._load_model()

        threading.Thread(target=_reload, daemon=True).start()

    def transcribe(self, audio_path: str) -> str | None:
        if not self.model:
            if not self.loaded_event.wait(timeout=120):
                emit({"type": "error", "message": "Timeout chargement modèle Whisper"})
                return None
        if not self.model:
            return None

        with self._lock:
            try:
                lang = self.config.get("language")
                if lang == "auto":
                    lang = None
                profile = self.config.get("transcription_profile") or "fast"
                preset = PROFILE_PRESETS.get(profile, PROFILE_PRESETS["fast"])
                segments, _info = self.model.transcribe(
                    audio_path,
                    beam_size=preset["beam_size"],
                    best_of=preset["best_of"],
                    language=lang,
                    condition_on_previous_text=preset["condition_on_previous_text"],
                    vad_filter=preset["vad_filter"],
                    vad_parameters=preset["vad_parameters"],
                    no_speech_threshold=preset["no_speech_threshold"],
                    log_prob_threshold=preset["log_prob_threshold"],
                )
                return "".join(segment.text for segment in segments).strip()
            except Exception as exc:
                emit({"type": "error", "message": f"Transcription : {exc}"})
                return None


class VoiceWorker:
    def __init__(self) -> None:
        self.config = sanitize_config(None)
        self.recorder: AudioRecorder | None = None
        self.transcriber: Transcriber | None = None
        self.recording = False
        self.auto_stop_timer: threading.Timer | None = None
        self._audio_queue: queue.Queue[str | None] = queue.Queue()
        self._transcribe_busy = False
        threading.Thread(target=self._transcribe_loop, daemon=True).start()

    def init(self, config: dict[str, Any] | None) -> None:
        self.config = sanitize_config(config)
        if self.recorder is None:
            self.recorder = AudioRecorder()
        if self.transcriber is None:
            self.transcriber = Transcriber(self.config)
        else:
            self.transcriber.reload(self.config)
        emit({"type": "status", "recording": False, "depsOk": True})

    def toggle(self) -> None:
        if self.recording:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        if not self.recorder:
            emit({"type": "error", "message": "Worker non initialisé"})
            return
        if not self.recorder.start():
            return
        self.recording = True
        emit({"type": "recording", "active": True})
        try:
            import winsound

            winsound.Beep(600, 150)
        except Exception:
            pass

        max_seconds = int(self.config.get("max_record_seconds") or 0)
        if max_seconds > 0:
            if self.auto_stop_timer:
                self.auto_stop_timer.cancel()
            self.auto_stop_timer = threading.Timer(max_seconds, self._auto_stop)
            self.auto_stop_timer.daemon = True
            self.auto_stop_timer.start()

    def _auto_stop(self) -> None:
        if self.recording:
            self._stop()

    def _stop(self) -> None:
        if not self.recording or not self.recorder:
            return
        self.recording = False
        if self.auto_stop_timer:
            self.auto_stop_timer.cancel()
            self.auto_stop_timer = None
        emit({"type": "recording", "active": False})
        try:
            import winsound

            winsound.Beep(400, 150)
        except Exception:
            pass

        audio_path = self.recorder.stop()
        if not audio_path:
            emit({"type": "transcript", "text": ""})
            return

        self._audio_queue.put(audio_path)

    def _transcribe_loop(self) -> None:
        while True:
            audio_path = self._audio_queue.get()
            if audio_path is None:
                break
            self._transcribe_busy = True
            emit({"type": "transcribing", "active": True})
            text = self.transcriber.transcribe(audio_path) if self.transcriber else None
            try:
                os.remove(audio_path)
            except Exception:
                pass
            emit({"type": "transcribing", "active": False})
            emit({"type": "transcript", "text": text or ""})
            self._transcribe_busy = False
            self._audio_queue.task_done()

    def shutdown(self) -> None:
        if self.recorder:
            self.recorder.close()


def main() -> None:
    deps_ok, err = check_deps()
    if not deps_ok:
        emit({"type": "deps", "ok": False, "error": err})
    else:
        emit({"type": "deps", "ok": True})

    worker = VoiceWorker()
    emit({"type": "ready"})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            emit({"type": "error", "message": f"JSON invalide : {exc}"})
            continue

        cmd = req.get("cmd")
        if cmd == "init":
            worker.init(req.get("config"))
        elif cmd == "toggle":
            worker.toggle()
        elif cmd == "preload":
            cfg = sanitize_config(req.get("config"))
            worker.init(cfg)
            if worker.transcriber:
                worker.transcriber.loaded_event.wait(timeout=300)
                loaded = worker.transcriber.model is not None
                emit({"type": "model", "loading": False, "loaded": loaded})
        elif cmd == "shutdown":
            worker.shutdown()
            break
        elif cmd == "ping":
            emit({"type": "pong"})
        else:
            emit({"type": "error", "message": f"Commande inconnue : {cmd}"})


if __name__ == "__main__":
    main()
