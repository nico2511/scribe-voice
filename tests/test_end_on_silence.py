"""Arrêt automatique après silence (end_on_silence_ms) — logique et protocole."""
from __future__ import annotations

import math
import struct
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import voice_silence as vs
import voice_worker as vw


def _tone_chunk(amplitude: int = 3000, samples: int = 1024) -> bytes:
    vals = [
        int(amplitude * math.sin(2 * math.pi * 440 * i / 16000))
        for i in range(samples)
    ]
    return struct.pack(f"<{samples}h", *vals)


def _silence_chunk(samples: int = 1024) -> bytes:
    return struct.pack(f"<{samples}h", *([0] * samples))


def test_chunk_rms_speech_vs_silence():
    assert vs.chunk_has_speech(_silence_chunk(), use_silero=False) is False
    assert vs.chunk_has_speech(_tone_chunk(), use_silero=False) is True


def test_tracker_requires_speech_before_silence_stop():
    tracker = vs.EndOnSilenceTracker(200, chunk_samples=1024, use_silero=False)
    for _ in range(10):
        assert tracker.feed(_silence_chunk()) is False
    tracker.feed(_tone_chunk())
    silence_ticks = int(math.ceil(200 / tracker._chunk_ms)) + 1
    stopped = False
    for i in range(silence_ticks):
        if tracker.feed(_silence_chunk()):
            stopped = True
            break
    assert stopped


def test_tracker_no_stop_without_prior_speech():
    tracker = vs.EndOnSilenceTracker(100, chunk_samples=1024, use_silero=False)
    for _ in range(50):
        assert tracker.feed(_silence_chunk()) is False


def test_parse_end_on_silence_ms():
    assert vs.parse_end_on_silence_ms(None) is None
    assert vs.parse_end_on_silence_ms("nope") is None
    assert vs.parse_end_on_silence_ms(-1) is None
    assert vs.parse_end_on_silence_ms(700) == 700
    assert vs.parse_end_on_silence_ms(50) == 100
    assert vs.parse_end_on_silence_ms(99_999) == 60_000


def test_protocol_version_announces_five(worker_factory):
    w = worker_factory()
    w.wait_type("deps")
    ready = w.wait_type("ready")
    assert ready.get("protocol") == 5


def test_start_without_end_on_silence_unchanged(worker_factory, tmp_path):
    """Sans le champ, l'enregistrement ne s'arrête pas tant que le micro est silencieux."""
    w = worker_factory(FAKE_PYAUDIO_AMPLITUDE="0", FAKE_PYAUDIO_SPEECH_MS="0")
    w.send({"cmd": "init", "config": {"model_size": "small", "max_record_seconds": 0}})
    w.wait_type("model", loaded=True, timeout=60)
    w.send({"cmd": "start"})
    w.wait_type("recording", active=True)
    w.drain(0.8)
    still_recording = any(
        e.get("type") == "recording" and e.get("active") is False for e in w.events
    )
    assert not still_recording
    w.send({"cmd": "stop"})
    w.wait_type("recording", active=False)


def test_start_end_on_silence_auto_stop(worker_factory, tmp_path):
    fw = '{"texts": ["bonjour"]}'
    w = worker_factory(
        FAKE_WHISPER=fw,
        FAKE_VAD='{"has_speech": true}',
        FAKE_PYAUDIO_SPEECH_MS="350",
    )
    w.send({"cmd": "init", "config": {"model_size": "small", "max_record_seconds": 0}})
    w.wait_type("model", loaded=True, timeout=60)
    w.send({"cmd": "start", "end_on_silence_ms": 250})
    w.wait_type("recording", active=True)
    w.wait_type("recording", active=False, timeout=15)
    w.wait_type("transcript", timeout=30)
    assert not any(e.get("type") == "error" for e in w.events)


def test_confirm_end_on_silence_auto_finish(worker_factory, tmp_path):
    fw = '{"texts": ["oui"]}'
    w = worker_factory(
        FAKE_WHISPER=fw,
        FAKE_PYAUDIO_SPEECH_MS="300",
    )
    w.send({"cmd": "init", "config": {"model_size": "small"}})
    w.wait_type("model", loaded=True, timeout=60)
    t0 = time.monotonic()
    w.send({"cmd": "confirm", "timeout": 8, "end_on_silence_ms": 200})
    conf = w.wait_type("confirmation", timeout=30)
    elapsed = time.monotonic() - t0
    assert conf.get("answer") == "yes"
    assert elapsed < 6.0