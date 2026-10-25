#!/usr/bin/env python3
"""
CyberScribeNote — Voice worker (sidecar)

Flux audio / Whisper aligné sur CyberScribe
(https://github.com/nico2511/CyberScribe) :
  - un seul process Python permanent
  - PyAudio + WhisperModel gardés en mémoire entre les dictées
  - mêmes presets VAD / transcription que CyberScribe

Communication JSON stdin/stdout pour le parent Tauri.
"""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import traceback
import unicodedata
import wave
from typing import Any

WORKER_VERSION = "1.1.0-dev"
PROTOCOL_VERSION = 2

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DOWNLOAD_ROOT = os.path.join(
    os.path.expanduser("~"), "Documents", "CyberScribeNote", "models"
)
DEFAULT_LOG_ROOT = os.path.join(
    os.path.expanduser("~"), "Documents", "CyberScribeNote"
)

_logging_ready = False
_fault_fp: Any = None


def _default_log_dir(app_id: str | None = None) -> str:
    if app_id:
        return os.path.join(DEFAULT_LOG_ROOT, app_id)
    return DEFAULT_LOG_ROOT


def _ensure_logging(app_id: str | None = None) -> None:
    """Configure le journal fichier (lazy — aucun dossier créé à l'import du module)."""
    global _logging_ready, _fault_fp
    log_dir = _default_log_dir(app_id)
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "voice_worker.log")
    if not _logging_ready:
        logging.basicConfig(
            filename=log_file,
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(message)s",
            encoding="utf-8",
            force=True,
        )
        _fault_fp = open(log_file, "a", encoding="utf-8")
        faulthandler.enable(file=_fault_fp, all_threads=True)
        _logging_ready = True
    else:
        for handler in logging.root.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.baseFilename = os.path.abspath(log_file)
                handler.stream.close()
                handler.stream = open(log_file, "a", encoding="utf-8")

VALID_LANGUAGES = {
    "auto", "en", "fr", "de", "es", "it", "ja", "zh", "nl", "uk", "pt", "ru",
}
VALID_MODELS = {"tiny", "base", "small", "medium", "large-v3"}
VALID_DEVICES = {"auto", "cpu", "cuda"}
VALID_COMPUTE = {"int8", "int8_float16", "float16", "float32"}
VALID_PROFILES = {"fast", "balanced", "accurate"}

DEFAULT_CONFIG = {
    "language": "fr",
    "model_size": "small",
    "device": "auto",
    "compute_type": "int8",
    "transcription_profile": "fast",
    "max_record_seconds": 90,
    "models_dir": None,
    "offline": False,
    "app_id": None,
}

_HF_REPO_PREFIX = "models--Systran--faster-whisper-"

PROFILE_PRESETS = {
    # Dictée : VAD souple — les pauses naturelles ne doivent pas tronquer la phrase.
    "fast": {
        "beam_size": 1,
        "best_of": 1,
        "vad_filter": True,
        "vad_parameters": {
            "min_silence_duration_ms": 1200,
            "min_speech_duration_ms": 120,
            "speech_pad_ms": 400,
        },
        "condition_on_previous_text": True,
        "no_speech_threshold": 0.6,
        "log_prob_threshold": -1.0,
    },
    "balanced": {
        "beam_size": 3,
        "best_of": 2,
        "vad_filter": True,
        "vad_parameters": {
            "min_silence_duration_ms": 900,
            "min_speech_duration_ms": 100,
            "speech_pad_ms": 350,
        },
        "condition_on_previous_text": True,
        "no_speech_threshold": 0.65,
        "log_prob_threshold": -1.2,
    },
    "accurate": {
        "beam_size": 5,
        "best_of": 3,
        "vad_filter": True,
        "vad_parameters": {
            "min_silence_duration_ms": 700,
            "min_speech_duration_ms": 80,
            "speech_pad_ms": 300,
        },
        "condition_on_previous_text": True,
        "no_speech_threshold": 0.7,
        "log_prob_threshold": -1.0,
    },
}

_emit_lock = threading.Lock()

# Biais ASR : le mot-clé seul (pas une commande complète, pour limiter
# les hallucinations du type « Scribe, corrige » sur un silence).
COMMAND_PROMPT = "Scribe."

_KEYWORD_ONLY_RE = re.compile(r"^(scribe[\s.,;:!?…]*)+$", re.IGNORECASE)


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _is_keyword_only(text: str) -> bool:
    """Vrai si le texte ne contient que le mot-clé « Scribe » (casse / accents ignorés)."""
    normalized = _strip_accents(text.strip())
    if not normalized:
        return False
    return bool(_KEYWORD_ONLY_RE.match(normalized))


def log(msg: str) -> None:
    logging.info(msg)


def log_error(msg: str) -> None:
    logging.error(msg)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        if n <= 0:
            raise OSError("stdout write returned 0")
        view = view[n:]


def _force_utf8_stdio() -> None:
    """Passe stdout en binaire (Windows) pour que os.write(1, json) ne soit pas manglé.

    On ne réouvre pas sys.stdin/sys.stdout : un second wrapper sur le même fd
    peut fermer le pipe au GC. emit() écrit directement sur fd 1.
    """
    if sys.platform != "win32":
        return
    try:
        import msvcrt

        msvcrt.setmode(1, os.O_BINARY)
    except Exception as exc:
        log_error(f"stdio setmode stdout: {exc}")


def emit(payload: dict[str, Any]) -> None:
    """JSON UTF-8 sur fd 1 — ignore le wrapper texte / NullWriter PyInstaller."""
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    with _emit_lock:
        try:
            _write_all(1, data)
            return
        except (BrokenPipeError, OSError) as exc:
            log_error(f"emit fd1: {exc}")
        try:
            buf = getattr(sys.stdout, "buffer", None)
            if buf is not None:
                buf.write(data)
                buf.flush()
                return
            sys.stdout.write(data.decode("utf-8"))
            sys.stdout.flush()
        except (BrokenPipeError, OSError, AttributeError) as exc:
            log_error(f"emit stdout: {exc}")


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def _sanitize_app_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    safe = re.sub(r"[^\w.\-]+", "_", text, flags=re.UNICODE)
    return safe[:120] or None


def _resolve_models_dir_from_env() -> str | None:
    raw = os.environ.get("SCRIBE_VOICE_MODELS_DIR")
    if not raw or not str(raw).strip():
        return None
    return os.path.abspath(os.path.expanduser(str(raw).strip()))


def _normalize_models_dir(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return os.path.abspath(os.path.expanduser(text))


def is_ct2_model_dir(path: str) -> bool:
    """Vrai si ``path`` ressemble à un dossier modèle CTranslate2 (faster-whisper)."""
    if not path or not os.path.isdir(path):
        return False
    for name in ("model.bin", "model.bin.index"):
        if os.path.isfile(os.path.join(path, name)):
            return True
    return False


def _hf_repo_dir_name(model_size: str) -> str:
    return f"{_HF_REPO_PREFIX}{model_size}"


def _find_hf_snapshot(models_root: str, model_size: str) -> str | None:
    """Cherche un snapshot Hugging Face sous ``models_root`` (cache plat ou hub/)."""
    repo = _hf_repo_dir_name(model_size)
    bases: list[str] = [models_root]
    hub = os.path.join(models_root, "hub")
    if os.path.isdir(hub):
        bases.append(hub)
    seen: set[str] = set()
    for base in bases:
        repo_path = os.path.join(base, repo)
        if repo_path in seen or not os.path.isdir(repo_path):
            continue
        seen.add(repo_path)
        snapshots = os.path.join(repo_path, "snapshots")
        if os.path.isdir(snapshots):
            for name in sorted(os.listdir(snapshots)):
                candidate = os.path.join(snapshots, name)
                if is_ct2_model_dir(candidate):
                    return candidate
        if is_ct2_model_dir(repo_path):
            return repo_path
    try:
        for entry in os.scandir(models_root):
            if not entry.is_dir():
                continue
            if entry.name != repo and not entry.name.startswith(repo):
                continue
            snapshots = os.path.join(entry.path, "snapshots")
            if os.path.isdir(snapshots):
                for name in sorted(os.listdir(snapshots)):
                    candidate = os.path.join(snapshots, name)
                    if is_ct2_model_dir(candidate):
                        return candidate
            if is_ct2_model_dir(entry.path):
                return entry.path
    except OSError:
        pass
    return None


def _flat_model_candidates(models_root: str, model_size: str) -> list[str]:
    names = (
        model_size,
        f"faster-whisper-{model_size}",
        f"whisper-{model_size}",
    )
    return [os.path.join(models_root, name) for name in names]


def resolve_whisper_model(
    config: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Résout le chemin ou l'identifiant passé à ``WhisperModel``.

    Retourne ``(model_arg, download_root, error_message)``. Si ``error_message`` est
    renseigné, le chargement doit échouer sans appeler Hugging Face.
    """
    model_size = str(config.get("model_size") or DEFAULT_CONFIG["model_size"])
    offline = _coerce_bool(config.get("offline"))
    models_dir = _normalize_models_dir(config.get("models_dir"))
    if models_dir is None:
        models_dir = _resolve_models_dir_from_env()

    if models_dir is None:
        if offline:
            return (
                None,
                None,
                "Mode hors ligne : indiquez models_dir ou SCRIBE_VOICE_MODELS_DIR.",
            )
        return model_size, DEFAULT_DOWNLOAD_ROOT, None

    if not os.path.isdir(models_dir):
        return (
            None,
            None,
            f"Dossier modèles introuvable : {models_dir}",
        )

    if is_ct2_model_dir(models_dir):
        return models_dir, None, None

    for candidate in _flat_model_candidates(models_dir, model_size):
        if is_ct2_model_dir(candidate):
            return candidate, None, None

    hf_path = _find_hf_snapshot(models_dir, model_size)
    if hf_path:
        return hf_path, None, None

    if offline:
        tried = ", ".join(_flat_model_candidates(models_dir, model_size))
        return (
            None,
            None,
            (
                f"Modèle « {model_size} » introuvable dans {models_dir} "
                f"(dossiers essayés : {tried} ; cache HF {_hf_repo_dir_name(model_size)})."
            ),
        )

    return model_size, models_dir, None


def sanitize_config(data: dict[str, Any] | None) -> dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    if not isinstance(data, dict):
        return cfg
    for key in DEFAULT_CONFIG:
        if key in data:
            cfg[key] = data[key]
    language = str(cfg.get("language") or "fr").lower()
    cfg["language"] = language if language in VALID_LANGUAGES else "fr"
    model_size = str(cfg.get("model_size") or DEFAULT_CONFIG["model_size"]).lower()
    cfg["model_size"] = (
        model_size if model_size in VALID_MODELS else DEFAULT_CONFIG["model_size"]
    )
    device = str(cfg.get("device") or "auto").lower()
    cfg["device"] = device if device in VALID_DEVICES else "auto"
    compute_type = str(cfg.get("compute_type") or "int8").lower()
    cfg["compute_type"] = compute_type if compute_type in VALID_COMPUTE else "int8"
    profile = str(cfg.get("transcription_profile") or "fast").lower()
    cfg["transcription_profile"] = profile if profile in PROFILE_PRESETS else "fast"
    try:
        max_seconds = int(cfg.get("max_record_seconds"))
    except (TypeError, ValueError):
        max_seconds = DEFAULT_CONFIG["max_record_seconds"]
    cfg["max_record_seconds"] = max(0, min(max_seconds, 600))
    cfg["offline"] = _coerce_bool(cfg.get("offline"))
    cfg["app_id"] = _sanitize_app_id(cfg.get("app_id"))
    explicit_dir = data.get("models_dir") if isinstance(data, dict) else None
    if explicit_dir is not None and str(explicit_dir).strip():
        cfg["models_dir"] = _normalize_models_dir(explicit_dir)
    elif cfg.get("models_dir"):
        cfg["models_dir"] = _normalize_models_dir(cfg.get("models_dir"))
    else:
        cfg["models_dir"] = _resolve_models_dir_from_env()
    return cfg


def _wav_stats(path: str) -> tuple[float, float]:
    """Durée (s) et RMS int16 d'un WAV — pour ignorer silences / bips."""
    import array

    with wave.open(path, "rb") as wf:
        nframes = wf.getnframes()
        rate = wf.getframerate() or 16000
        width = wf.getsampwidth()
        frames = wf.readframes(nframes)
    duration = nframes / float(rate)
    if width != 2 or not frames:
        return duration, 0.0
    samples = array.array("h")
    try:
        samples.frombytes(frames)
    except Exception:
        return duration, 0.0
    if not samples:
        return duration, 0.0
    acc = 0.0
    for sample in samples:
        acc += sample * sample
    rms = (acc / len(samples)) ** 0.5
    return duration, rms


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
    """Identique à CyberScribe.AudioRecorder — PyAudio permanent."""

    def __init__(self) -> None:
        import pyaudio

        self.pyaudio = pyaudio
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.frames: list[bytes] = []
        self.is_recording = False
        self.format = pyaudio.paInt16
        self.channels = 1
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
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk,
            )
            threading.Thread(target=self._record_loop, daemon=True).start()
            log("Recording started")
            return True
        except Exception as exc:
            self.is_recording = False
            self.stream = None
            log_error(f"Microphone: {exc}")
            emit({"type": "error", "message": f"Microphone : {exc}"})
            return False

    def _record_loop(self) -> None:
        while self.is_recording and self.stream:
            try:
                data = self.stream.read(self.chunk, exception_on_overflow=False)
                with self._lock:
                    self.frames.append(data)
            except Exception as exc:
                log_error(f"record_loop: {exc}")
                break

    def stop(self) -> str | None:
        if not self.is_recording:
            return None
        self.is_recording = False
        log("Recording stopped")
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
        except Exception as exc:
            log_error(f"close stream: {exc}")

        with self._lock:
            frames = list(self.frames)
            self.frames = []

        if not frames:
            return None

        fd, path = tempfile.mkstemp(suffix=".wav", prefix="csnote_")
        os.close(fd)
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.audio.get_sample_size(self.format))
                wf.setframerate(self.rate)
                wf.writeframes(b"".join(frames))
            return path
        except Exception as exc:
            log_error(f"wav write: {exc}")
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
    """Identique à CyberScribe.Transcriber — modèle chargé une fois, gardé en RAM."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.model = None
        self.loading = False
        self.loaded_event = threading.Event()
        self._transcribe_lock = threading.Lock()
        self._load_gen = 0
        threading.Thread(target=self._load_model, daemon=True).start()

    def _resolve_device(self) -> list[tuple[str, str]]:
        """Retourne des paires (device, compute_type) à essayer, CUDA puis CPU."""
        device_pref = (self.config.get("device") or "auto").lower()
        compute_pref = (self.config.get("compute_type") or "int8").lower()
        has_nvidia = detect_nvidia_gpu()

        if device_pref == "auto":
            device = "cuda" if has_nvidia else "cpu"
        else:
            device = device_pref
        if device == "cuda" and not has_nvidia:
            device = "cpu"

        candidates: list[tuple[str, str]] = []
        if device == "cuda":
            cuda_compute = "int8_float16" if compute_pref == "int8" else compute_pref
            candidates.append(("cuda", cuda_compute))
            candidates.append(("cpu", "int8"))
        else:
            cpu_compute = (
                "int8" if compute_pref in ("int8_float16", "float16") else compute_pref
            )
            candidates.append(("cpu", cpu_compute))
        return candidates

    def _load_model(self) -> None:
        from faster_whisper import WhisperModel

        self._load_gen += 1
        gen = self._load_gen
        self.loading = True
        self.loaded_event.clear()
        emit({"type": "model", "loading": True, "loaded": False})
        model_size = self.config.get("model_size")
        offline = _coerce_bool(self.config.get("offline"))
        model_arg, download_root, resolve_err = resolve_whisper_model(self.config)
        last_err: Exception | None = None
        loaded = False

        if resolve_err:
            log_error(resolve_err)
            emit({"type": "error", "message": f"Chargement modèle : {resolve_err}"})
            emit({"type": "model", "loading": False, "loaded": False})
            self.loaded_event.set()
            self.loading = False
            return

        try:
            for device, compute_type in self._resolve_device():
                if gen != self._load_gen:
                    log(f"Load gen {gen} cancelled")
                    return
                try:
                    log(
                        f"Loading Whisper ({model_arg!r}) on {device}/{compute_type}"
                        f" offline={offline} download_root={download_root!r}"
                    )
                    whisper_kwargs: dict[str, Any] = {
                        "device": device,
                        "compute_type": compute_type,
                    }
                    if download_root:
                        whisper_kwargs["download_root"] = download_root
                    if offline:
                        whisper_kwargs["local_files_only"] = True
                    model = WhisperModel(model_arg, **whisper_kwargs)
                    if gen != self._load_gen:
                        log(f"Load gen {gen} discarded after build")
                        return
                    self.model = model
                    log(f"Model loaded on {device}/{compute_type}")
                    emit({"type": "model", "loading": False, "loaded": True})
                    loaded = True
                    return
                except Exception as exc:
                    last_err = exc
                    log_error(f"model load failed ({device}/{compute_type}): {exc}")
                    continue

            self.model = None
            msg = f"Chargement modèle : {last_err}" if last_err else "Chargement modèle échoué"
            log_error(msg)
            emit({"type": "error", "message": msg})
            emit({"type": "model", "loading": False, "loaded": False})
        except Exception as exc:
            if gen == self._load_gen:
                self.model = None
                log_error(f"model load: {exc}\n{traceback.format_exc()}")
                emit({"type": "error", "message": f"Chargement modèle : {exc}"})
                emit({"type": "model", "loading": False, "loaded": False})
        finally:
            if gen == self._load_gen:
                self.loaded_event.set()
                self.loading = False
                if not loaded and self.model is None:
                    emit({"type": "model", "loading": False, "loaded": False})

    def reload(self, config: dict[str, Any]) -> None:
        prev = self.config
        same = (
            prev.get("model_size") == config.get("model_size")
            and prev.get("device") == config.get("device")
            and prev.get("compute_type") == config.get("compute_type")
            and prev.get("models_dir") == config.get("models_dir")
            and prev.get("offline") == config.get("offline")
        )
        self.config = config

        # Évite le double chargement init + preload (cause fréquente de plantage).
        if same:
            if self.model is not None:
                emit({"type": "model", "loading": False, "loaded": True})
                return
            if self.loading:
                log("reload skipped — chargement déjà en cours")
                return

        def _reload() -> None:
            with self._transcribe_lock:
                self.model = None
                self._load_model()

        threading.Thread(target=_reload, daemon=True).start()

    def transcribe(self, audio_path: str) -> str | None:
        if not self.model:
            if not self.loading and not self.loaded_event.is_set():
                return None
            if not self.loaded_event.wait(timeout=120):
                emit({"type": "error", "message": "Timeout chargement modèle Whisper"})
                return None
        if not self.model:
            return None

        duration, rms = _wav_stats(audio_path)
        log(f"Transcribing {audio_path} duration={duration:.2f}s rms={rms:.1f}")
        if duration < 0.35 or rms < 60:
            log("audio too short or too quiet — skip")
            return ""

        if duration < 8 and not self._has_speech(audio_path):
            log("no speech detected (VAD gate) — skip")
            return ""

        with self._transcribe_lock:
            try:
                lang = self.config.get("language")
                if lang == "auto":
                    lang = None
                profile = self.config.get("transcription_profile") or "fast"
                preset = PROFILE_PRESETS.get(profile, PROFILE_PRESETS["fast"])
                # Les commandes « Scribe, … » durent 1–3 s : le VAD les avale souvent.
                use_vad = bool(preset["vad_filter"]) and duration >= 3.5
                text = self._transcribe_once(
                    audio_path,
                    lang,
                    preset,
                    duration=duration,
                    vad=use_vad,
                    condition=duration >= 3.5,
                )
                if not text and duration < 8:
                    log("empty transcript — retry without VAD")
                    text = self._transcribe_once(
                        audio_path,
                        lang,
                        preset,
                        duration=duration,
                        vad=False,
                        condition=False,
                        no_speech=0.35,
                    )
                if _is_keyword_only(text):
                    log("keyword-only transcript filtered — skip")
                    return ""
                log(f"Transcription done ({len(text)} chars): {text[:180]!r}")
                return text
            except Exception as exc:
                log_error(f"transcribe: {exc}\n{traceback.format_exc()}")
                emit({"type": "error", "message": f"Transcription : {exc}"})
                return None

    def _has_speech(self, audio_path: str) -> bool:
        """Détection Silero (faster-whisper) : parole présente dans le WAV 16 kHz."""
        try:
            import numpy as np
            from faster_whisper.vad import get_speech_timestamps

            with wave.open(audio_path, "rb") as wf:
                rate = wf.getframerate() or 16000
                if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                    log("VAD gate: format WAV inattendu — assume speech")
                    return True
                frames = wf.readframes(wf.getnframes())
            if rate != 16000:
                log(f"VAD gate: sample rate {rate} — assume speech")
                return True
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            timestamps = get_speech_timestamps(audio, sampling_rate=16000)
            return bool(timestamps)
        except Exception as exc:
            log(f"VAD gate failed — assume speech: {exc}")
            return True

    def _transcribe_once(
        self,
        audio_path: str,
        lang: str | None,
        preset: dict[str, Any],
        *,
        duration: float,
        vad: bool,
        condition: bool,
        no_speech: float | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "beam_size": preset["beam_size"],
            "best_of": preset["best_of"],
            "language": lang,
            "condition_on_previous_text": (
                preset["condition_on_previous_text"] if condition else False
            ),
            "vad_filter": vad,
            "no_speech_threshold": (
                no_speech
                if no_speech is not None
                else preset["no_speech_threshold"]
            ),
            "log_prob_threshold": preset["log_prob_threshold"],
            "initial_prompt": COMMAND_PROMPT,
            "without_timestamps": True,
        }
        if vad:
            kwargs["vad_parameters"] = preset["vad_parameters"]
        if not self.model:
            return ""
        try:
            segments, _info = self.model.transcribe(audio_path, **kwargs)
        except TypeError:
            kwargs.pop("without_timestamps", None)
            segments, _info = self.model.transcribe(audio_path, **kwargs)
        segment_list = list(segments)
        if duration < 3.5:
            segment_list = [
                s
                for s in segment_list
                if getattr(s, "no_speech_prob", 0.0) <= 0.6
            ]
        return "".join(segment.text for segment in segment_list).strip()


class VoiceWorker:
    def __init__(self) -> None:
        self.config = sanitize_config(None)
        self.recorder: AudioRecorder | None = None
        self.transcriber: Transcriber | None = None
        self.recording = False
        self.auto_stop_timer: threading.Timer | None = None
        self._start_timer: threading.Timer | None = None
        self._starting = False
        self._transcribe_busy = False

    def init(self, config: dict[str, Any] | None) -> None:
        self.config = sanitize_config(config)
        _ensure_logging(self.config.get("app_id"))
        if self.recorder is None:
            try:
                self.recorder = AudioRecorder()
            except Exception as exc:
                log_error(f"AudioRecorder: {exc}")
                emit({"type": "error", "message": f"Micro indisponible : {exc}"})
                return
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

    def _beep(self, freq: int, ms: int) -> None:
        def _run() -> None:
            try:
                import winsound

                winsound.Beep(freq, ms)
            except Exception as exc:
                log_error(f"beep: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    def _start(self) -> None:
        if not self.recorder:
            emit({"type": "error", "message": "Worker non initialisé"})
            return
        if self._transcribe_busy:
            emit({"type": "error", "message": "Transcription encore en cours — patientez."})
            return
        if self._starting:
            if self._start_timer:
                self._start_timer.cancel()
                self._start_timer = None
            self._starting = False
            emit({"type": "recording", "active": False})
            emit({"type": "transcript", "text": ""})
            return
        # Bip hors micro pour ne pas polluer l'audio / PortAudio
        self._beep(600, 160)
        self._starting = True

        def _begin() -> None:
            if not self._starting:
                return
            self._starting = False
            self._start_timer = None
            if not self.recorder or self.recording:
                return
            if not self.recorder.start():
                return
            self.recording = True
            emit({"type": "recording", "active": True})
            max_seconds = int(self.config.get("max_record_seconds") or 0)
            if max_seconds > 0:
                if self.auto_stop_timer:
                    self.auto_stop_timer.cancel()
                self.auto_stop_timer = threading.Timer(max_seconds, self._auto_stop)
                self.auto_stop_timer.daemon = True
                self.auto_stop_timer.start()

        self._start_timer = threading.Timer(0.22, _begin)
        self._start_timer.daemon = True
        self._start_timer.start()

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
        audio_path = self.recorder.stop()
        self._beep(400, 160)
        if not audio_path:
            emit({"type": "transcript", "text": ""})
            return
        self._transcribe_busy = True
        threading.Thread(
            target=self._process_audio, args=(audio_path,), daemon=True
        ).start()

    def _process_audio(self, audio_path: str) -> None:
        emit({"type": "transcribing", "active": True})
        text = ""
        try:
            if self.transcriber:
                text = self.transcriber.transcribe(audio_path) or ""
        except Exception as exc:
            log_error(f"process_audio: {exc}\n{traceback.format_exc()}")
            emit({"type": "error", "message": f"Transcription : {exc}"})
        finally:
            try:
                os.remove(audio_path)
            except Exception:
                pass
            emit({"type": "transcribing", "active": False})
            emit({"type": "transcript", "text": text})
            self._transcribe_busy = False

    def shutdown(self) -> None:
        log("shutdown")
        if self.recorder:
            self.recorder.close()


def main() -> None:
    _force_utf8_stdio()
    _ensure_logging(None)
    log(f"Worker start pid={os.getpid()} python={sys.executable} frozen={getattr(sys, 'frozen', False)}")
    deps_ok, err = check_deps()
    if not deps_ok:
        emit({"type": "deps", "ok": False, "error": err})
        log_error(f"deps missing: {err}")
    else:
        emit({"type": "deps", "ok": True})

    worker = VoiceWorker()
    emit({
        "type": "ready",
        "version": WORKER_VERSION,
        "protocol": PROTOCOL_VERSION,
    })

    try:
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
            log(f"cmd={cmd}")
            try:
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
            except Exception as exc:
                log_error(f"cmd handler: {exc}\n{traceback.format_exc()}")
                emit({"type": "error", "message": f"Worker : {exc}"})
    except Exception as exc:
        log_error(f"main loop: {exc}\n{traceback.format_exc()}")
        emit({"type": "error", "message": f"Worker fatal : {exc}"})
    finally:
        log("Worker exit")


if __name__ == "__main__":
    main()
