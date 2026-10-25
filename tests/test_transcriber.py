"""Tests unitaires du traitement des commandes courtes « Scribe, … ».

Contrat v1.1 :
  - initial_prompt « Scribe. » sur chaque passe (sans hotwords) ;
  - porte VAD (Silero) avant Whisper si durée < 8 s ;
  - texte mot-clé seul -> "" ;
  - VAD Whisper seulement si durée >= 3,5 s (et si le profil l'active) ;
  - segments courts : no_speech_prob > 0,6 ignorés ;
  - transcription vide et durée < 8 s -> nouvelle passe sans VAD, no_speech 0,35 ;
  - audio < 0,35 s ou RMS < 60 -> "" sans appel au modèle.
"""
from __future__ import annotations

import math
import struct
import threading
import wave

import numpy as np
import pytest

import voice_worker as vw

_ORIGINAL_HAS_SPEECH = vw.Transcriber._has_speech


@pytest.fixture(autouse=True)
def synthetic_wav_counts_as_speech(monkeypatch):
    """Les WAV sinusoïdaux des tests ne sont pas de la parole pour Silero réel."""
    monkeypatch.setattr(
        vw.Transcriber,
        "_has_speech",
        lambda self, _path: True,
    )


class FakeModel:
    def __init__(
        self,
        texts=("Scribe, corrige.",),
        raise_type_error_once=False,
        no_speech_probs=None,
    ):
        self.texts = list(texts)
        self.calls: list[dict] = []
        self.audios: list = []
        self.raise_type_error_once = raise_type_error_once
        self.no_speech_probs = list(no_speech_probs or [])

    def transcribe(self, audio, **kwargs):
        self.calls.append(dict(kwargs))
        self.audios.append(audio)
        if self.raise_type_error_once:
            self.raise_type_error_once = False
            raise TypeError("unexpected keyword argument 'without_timestamps'")
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        prob = self.no_speech_probs.pop(0) if self.no_speech_probs else 0.0

        class Seg:
            def __init__(self, t, p):
                self.text = t
                self.no_speech_prob = p

        return iter([Seg(" " + text, prob)] if text else []), None


def make_transcriber(model, **config):
    t = vw.Transcriber.__new__(vw.Transcriber)  # pas de thread de chargement
    t.config = vw.sanitize_config(config)
    t.model = model
    t.loading = False
    t.loaded_event = threading.Event()
    t.loaded_event.set()
    t._transcribe_lock = threading.Lock()
    t._load_gen = 1
    return t


def make_wav(tmp_path, seconds, amplitude=3000, rate=16000):
    path = tmp_path / f"a_{seconds}_{amplitude}.wav"
    n = int(round(seconds * rate))
    frames = struct.pack(
        "<%dh" % n,
        *(int(amplitude * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)),
    )
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return str(path)


def test_command_constants():
    assert vw.COMMAND_PROMPT == "Scribe."


def test_transcribe_passes_float32_ndarray_to_model(tmp_path):
    m = FakeModel(["Scribe, bonjour."])
    t = make_transcriber(m)
    path = make_wav(tmp_path, 1.5)
    t.transcribe(path)
    assert len(m.audios) == 1
    audio = m.audios[0]
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert len(audio) == int(1.5 * 16000)


@pytest.mark.parametrize("raw", ["Scribe Scribe.", "scribe", "SCRIBE !"])
def test_keyword_only_filtered(tmp_path, raw):
    m = FakeModel([raw])
    t = make_transcriber(m)
    assert t.transcribe(make_wav(tmp_path, 1.5)) == ""


def test_real_scribe_command_preserved(tmp_path):
    m = FakeModel(["Scribe, corrige le texte."])
    t = make_transcriber(m)
    assert t.transcribe(make_wav(tmp_path, 1.5)) == "Scribe, corrige le texte."


def test_is_keyword_only_helper():
    assert vw._is_keyword_only("Scribe Scribe.")
    assert vw._is_keyword_only("SCRIBE !")
    assert not vw._is_keyword_only("Scribe, corrige le texte.")


def test_has_speech_false_skips_model(tmp_path, monkeypatch):
    m = FakeModel(["Scribe, traduis."])
    t = make_transcriber(m)
    monkeypatch.setattr(t, "_has_speech", lambda _path: False)
    assert t.transcribe(make_wav(tmp_path, 1.5)) == ""
    assert m.calls == []


def test_has_speech_failure_allows_transcription(tmp_path, monkeypatch):
    m = FakeModel(["Scribe, corrige."])
    t = make_transcriber(m)
    monkeypatch.setattr(vw.Transcriber, "_has_speech", _ORIGINAL_HAS_SPEECH)

    def _boom(*_a, **_k):
        raise RuntimeError("vad indisponible")

    monkeypatch.setattr("faster_whisper.vad.get_speech_timestamps", _boom)
    assert t.transcribe(make_wav(tmp_path, 1.5)) == "Scribe, corrige."
    assert len(m.calls) >= 1


def test_short_clip_drops_high_no_speech_segment(tmp_path):
    m = FakeModel(["Scribe Scribe."], no_speech_probs=[0.9])
    t = make_transcriber(m)
    preset = vw.PROFILE_PRESETS["fast"]
    audio = vw._load_wav_mono_float32(make_wav(tmp_path, 2.0))
    out = t._transcribe_once(
        audio,
        "fr",
        preset,
        duration=2.0,
        vad=False,
        condition=False,
    )
    assert out == ""


@pytest.mark.parametrize("seconds", [1.0, 2.0, 3.49])
def test_short_scribe_command_no_vad(tmp_path, seconds):
    m = FakeModel(["Scribe, résume."])
    t = make_transcriber(m)
    assert t.transcribe(make_wav(tmp_path, seconds)) == "Scribe, résume."
    assert len(m.calls) == 1
    c = m.calls[0]
    assert c["vad_filter"] is False
    assert "vad_parameters" not in c
    assert c["condition_on_previous_text"] is False
    assert c["initial_prompt"] == "Scribe."
    assert "hotwords" not in c
    assert c["without_timestamps"] is True
    assert c["language"] == "fr"
    assert c["beam_size"] == 1 and c["best_of"] == 1


@pytest.mark.parametrize("seconds", [3.5, 6.0])
def test_long_dictation_uses_vad(tmp_path, seconds):
    m = FakeModel(["Une longue dictée."])
    t = make_transcriber(m)
    assert t.transcribe(make_wav(tmp_path, seconds)) == "Une longue dictée."
    c = m.calls[0]
    assert c["vad_filter"] is True
    assert c["vad_parameters"] == vw.PROFILE_PRESETS["fast"]["vad_parameters"]
    assert c["condition_on_previous_text"] is True
    assert c["no_speech_threshold"] == 0.6
    assert c["initial_prompt"] == "Scribe."
    assert "hotwords" not in c


@pytest.mark.parametrize("seconds", [1.5, 5.0, 7.9])
def test_empty_result_retries_without_vad(tmp_path, seconds):
    m = FakeModel(["", "Scribe, traduis."])
    t = make_transcriber(m)
    assert t.transcribe(make_wav(tmp_path, seconds)) == "Scribe, traduis."
    assert len(m.calls) == 2
    retry = m.calls[1]
    assert retry["vad_filter"] is False
    assert "vad_parameters" not in retry
    assert retry["condition_on_previous_text"] is False
    assert retry["no_speech_threshold"] == 0.35
    assert retry["initial_prompt"] == "Scribe."
    assert "hotwords" not in retry


def test_no_retry_when_8_seconds_or_more(tmp_path):
    m = FakeModel([""])
    t = make_transcriber(m)
    assert t.transcribe(make_wav(tmp_path, 8.0)) == ""
    assert len(m.calls) == 1


def test_too_short_audio_skipped(tmp_path):
    m = FakeModel()
    t = make_transcriber(m)
    assert t.transcribe(make_wav(tmp_path, 0.3)) == ""
    assert m.calls == []


def test_too_quiet_audio_skipped(tmp_path):
    m = FakeModel()
    t = make_transcriber(m)
    assert t.transcribe(make_wav(tmp_path, 2.0, amplitude=40)) == ""
    assert m.calls == []


def test_type_error_fallback_drops_without_timestamps(tmp_path):
    m = FakeModel(["Scribe, corrige."], raise_type_error_once=True)
    t = make_transcriber(m)
    assert t.transcribe(make_wav(tmp_path, 1.5)) == "Scribe, corrige."
    assert len(m.calls) == 2
    assert "hotwords" not in m.calls[0]
    assert "without_timestamps" not in m.calls[1]
    assert m.calls[1]["initial_prompt"] == "Scribe."


def test_language_auto_maps_to_none(tmp_path):
    m = FakeModel()
    t = make_transcriber(m, language="auto")
    t.transcribe(make_wav(tmp_path, 1.0))
    assert m.calls[0]["language"] is None


@pytest.mark.parametrize("profile", ["fast", "balanced", "accurate"])
def test_profile_presets_applied(tmp_path, profile):
    m = FakeModel()
    t = make_transcriber(m, transcription_profile=profile)
    t.transcribe(make_wav(tmp_path, 4.0))
    p = vw.PROFILE_PRESETS[profile]
    assert m.calls[0]["beam_size"] == p["beam_size"]
    assert m.calls[0]["best_of"] == p["best_of"]
    assert m.calls[0]["vad_parameters"] == p["vad_parameters"]


def test_transcribe_busy_set_before_audio_thread(tmp_path, monkeypatch):
    worker = vw.VoiceWorker()
    worker.recording = True
    worker.config = vw.sanitize_config({})
    worker.transcriber = make_transcriber(FakeModel(["ok"]))

    class Rec:
        def stop(self):
            return make_wav(tmp_path, 1.0)

    worker.recorder = Rec()
    busy_at_thread_start: list[bool] = []
    real_thread = threading.Thread

    def capture_thread(*args, **kwargs):
        busy_at_thread_start.append(worker._transcribe_busy)
        return real_thread(*args, **kwargs)

    monkeypatch.setattr(worker, "_beep", lambda *_a, **_k: None)
    monkeypatch.setattr(threading, "Thread", capture_thread)
    monkeypatch.setattr(vw, "emit", lambda _payload: None)
    worker._stop()
    assert busy_at_thread_start == [True]


def test_transcribe_exception_emits_error(tmp_path, capfd):
    class Boom:
        def transcribe(self, *a, **k):
            raise RuntimeError("ctranslate2 a planté")

    t = make_transcriber(Boom())
    assert t.transcribe(make_wav(tmp_path, 1.0)) is None
    out = capfd.readouterr().out.strip().splitlines()
    assert out and __import__("json").loads(out[-1]) == {
        "type": "error", "message": "Transcription : ctranslate2 a planté"
    }
