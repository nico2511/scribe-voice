"""Tests de sanitize_config, emit et du choix device/compute (sans GPU)."""
from __future__ import annotations

import json

import pytest

import voice_worker as vw


def test_defaults():
    assert vw.sanitize_config(None) == vw.DEFAULT_CONFIG
    assert vw.sanitize_config("pas un dict") == vw.DEFAULT_CONFIG


def test_valid_values_kept_and_normalized():
    cfg = vw.sanitize_config({
        "language": "EN", "model_size": "Large-V3", "device": "CPU",
        "compute_type": "FLOAT32", "transcription_profile": "Accurate",
        "max_record_seconds": "30", "inconnu": 1,
    })
    assert cfg == {
        "language": "en",
        "model_size": "large-v3",
        "device": "cpu",
        "compute_type": "float32",
        "transcription_profile": "accurate",
        "max_record_seconds": 30,
        "models_dir": None,
        "offline": False,
        "app_id": None,
        "keyword": "Scribe",
        "keyword_aliases": [],
    }


def test_invalid_values_fall_back():
    cfg = vw.sanitize_config({
        "language": "klingon", "model_size": "huge", "device": "tpu",
        "compute_type": "int4", "transcription_profile": "turbo",
        "max_record_seconds": "abc",
    })
    assert cfg == vw.DEFAULT_CONFIG


@pytest.mark.parametrize("raw,expected", [(-5, 0), (0, 0), (600, 600), (10_000, 600)])
def test_max_record_seconds_clamped(raw, expected):
    assert vw.sanitize_config({"max_record_seconds": raw})["max_record_seconds"] == expected


def test_emit_writes_one_utf8_json_line(capfd):
    vw.emit({"type": "transcript", "text": "Scribe, résume « ça »."})
    out = capfd.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1
    assert json.loads(out) == {"type": "transcript", "text": "Scribe, résume « ça »."}
    assert "résume" in out  # ensure_ascii=False


@pytest.mark.parametrize("device,compute,gpu,expected", [
    ("auto", "int8", False, [("cpu", "int8")]),
    ("auto", "int8", True, [("cuda", "int8_float16"), ("cpu", "int8")]),
    ("cuda", "float16", False, [("cpu", "int8")]),
    ("cuda", "float16", True, [("cuda", "float16"), ("cpu", "int8")]),
    ("cpu", "float32", True, [("cpu", "float32")]),
])
def test_resolve_device(monkeypatch, device, compute, gpu, expected):
    monkeypatch.setattr(vw, "detect_nvidia_gpu", lambda: gpu)
    t = vw.Transcriber.__new__(vw.Transcriber)
    t.config = {"device": device, "compute_type": compute}
    assert t._resolve_device() == expected
