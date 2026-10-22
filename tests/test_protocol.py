"""Tests de contrat du protocole JSON Lines (stdin -> commandes, stdout -> événements).

Le worker réel (voice_worker.py, non modifié) tourne en sous-processus ;
pyaudio / faster_whisper / winsound sont remplacés par tests/fakes via PYTHONPATH.
Aucun micro, aucun modèle, aucun réseau.
"""
from __future__ import annotations

import json
import time

INIT = {"cmd": "init", "config": {"language": "fr", "model_size": "base", "device": "cpu"}}


def _fake_whisper(tmp_path, **cfg):
    calls = tmp_path / "calls.jsonl"
    cfg.setdefault("calls_file", str(calls))
    return json.dumps(cfg), calls


def _read_calls(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- Démarrage ----------------------------------------------------------------

def test_startup_emits_deps_then_ready(worker_factory):
    w = worker_factory()
    first = w.wait_for(lambda e: True)
    second = w.wait_for(lambda e: True)
    assert first == {"type": "deps", "ok": True}
    assert second == {"type": "ready"}
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_deps_missing_reports_error_and_still_ready(worker_factory):
    w = worker_factory(FAKE_PYAUDIO_IMPORT_ERROR="1")
    deps = w.wait_type("deps")
    assert deps["ok"] is False
    assert isinstance(deps.get("error"), str) and deps["error"]
    w.wait_type("ready")
    w.send({"cmd": "ping"})
    w.wait_type("pong")
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


# --- ping / erreurs de protocole ---------------------------------------------

def test_ping_pong(worker_factory):
    w = worker_factory()
    w.wait_type("ready")
    w.send({"cmd": "ping"})
    assert w.wait_type("pong") == {"type": "pong"}
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_invalid_json_and_unknown_command_are_errors_not_fatal(worker_factory):
    w = worker_factory()
    w.wait_type("ready")
    w.send("{pas du json")
    err = w.wait_type("error")
    assert err["message"].startswith("JSON invalide")
    w.send({"cmd": "danse"})
    err = w.wait_type("error")
    assert err["message"] == "Commande inconnue : danse"
    w.send("")  # ligne vide ignorée
    w.send({"cmd": "ping"})
    w.wait_type("pong")
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_toggle_before_init_is_error(worker_factory):
    w = worker_factory()
    w.wait_type("ready")
    w.send({"cmd": "toggle"})
    err = w.wait_type("error")
    assert err["message"] == "Worker non initialisé"
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


# --- init / preload / model ---------------------------------------------------

def test_init_emits_model_and_status(worker_factory, tmp_path):
    fw, _ = _fake_whisper(tmp_path)
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send(INIT)
    status = w.wait_type("status")
    assert status == {"type": "status", "recording": False, "depsOk": True}
    w.wait_type("model", loaded=True, loading=False)
    loading = [e for e in w.events if e["type"] == "model" and e.get("loading") is True]
    assert loading and loading[0] == {"type": "model", "loading": True, "loaded": False}
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_preload_waits_and_reports_loaded(worker_factory, tmp_path):
    fw, _ = _fake_whisper(tmp_path)
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send({"cmd": "preload", "config": {"model_size": "small"}})
    w.wait_type("status", recording=False, depsOk=True)
    w.wait_type("model", loaded=True)
    # preload est bloquant : le ping n'est traité qu'après le chargement.
    w.send({"cmd": "ping"})
    w.wait_type("pong")
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_model_load_failure(worker_factory, tmp_path):
    fw, _ = _fake_whisper(tmp_path, fail_load=True)
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send({"cmd": "preload", "config": {}})
    err = w.wait_type("error")
    assert err["message"].startswith("Chargement modèle")
    w.wait_type("model", loaded=False, loading=False)
    w.send({"cmd": "ping"})
    w.wait_type("pong")
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


# --- toggle : cycle de dictée complet -------------------------------------------

def _dictate(w, seconds):
    w.send({"cmd": "toggle"})
    w.wait_type("recording", active=True)
    time.sleep(seconds)
    w.send({"cmd": "toggle"})
    w.wait_type("recording", active=False)
    w.wait_type("transcribing", active=True, timeout=30)
    w.wait_type("transcribing", active=False, timeout=30)
    return w.wait_type("transcript", timeout=30)


def test_full_dictation_cycle_short_scribe_command(worker_factory, tmp_path):
    fw, calls = _fake_whisper(tmp_path, texts=["Scribe, corrige le texte."])
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send(INIT)
    w.wait_type("model", loaded=True)
    tr = _dictate(w, 1.2)
    assert tr == {"type": "transcript", "text": "Scribe, corrige le texte."}
    c = _read_calls(calls)
    assert len(c) == 1
    # Commande courte « Scribe, … » (< 3,5 s) : pas de VAD, prompt/hotword Scribe.
    assert c[0]["vad_filter"] is False
    assert "vad_parameters" not in c[0]
    assert c[0]["initial_prompt"] == "Scribe."
    assert c[0]["hotwords"] == "Scribe"
    assert c[0]["condition_on_previous_text"] is False
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_short_command_empty_then_retry_without_vad(worker_factory, tmp_path):
    fw, calls = _fake_whisper(tmp_path, texts=["", "Scribe, traduis en anglais."])
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send(INIT)
    w.wait_type("model", loaded=True)
    tr = _dictate(w, 1.0)
    assert tr["text"] == "Scribe, traduis en anglais."
    c = _read_calls(calls)
    assert len(c) == 2
    assert c[1]["vad_filter"] is False
    assert c[1]["no_speech_threshold"] == 0.35
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_silent_recording_gives_empty_transcript_without_model_call(worker_factory, tmp_path):
    fw, calls = _fake_whisper(tmp_path)
    w = worker_factory(FAKE_WHISPER=fw, FAKE_PYAUDIO_AMPLITUDE="0")
    w.wait_type("ready")
    w.send(INIT)
    w.wait_type("model", loaded=True)
    tr = _dictate(w, 0.8)
    assert tr == {"type": "transcript", "text": ""}
    assert _read_calls(calls) == []
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_microphone_open_failure_is_error(worker_factory, tmp_path):
    fw, _ = _fake_whisper(tmp_path)
    w = worker_factory(FAKE_WHISPER=fw, FAKE_PYAUDIO_FAIL_OPEN="1")
    w.wait_type("ready")
    w.send(INIT)
    w.wait_type("model", loaded=True)
    w.send({"cmd": "toggle"})
    err = w.wait_type("error")
    assert err["message"].startswith("Microphone : ")
    w.drain(0.5)
    assert not any(e["type"] == "recording" for e in w.events)
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


# --- shutdown / EOF -----------------------------------------------------------

def test_shutdown_exits_cleanly(worker_factory):
    w = worker_factory()
    w.wait_type("ready")
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_stdin_eof_exits_cleanly(worker_factory):
    w = worker_factory()
    w.wait_type("ready")
    assert w.close() == 0


def test_stdout_is_utf8_json_lines(worker_factory):
    w = worker_factory()
    w.wait_type("ready")
    w.send({"cmd": "toggle"})  # message accentué : « Worker non initialisé »
    w.wait_type("error")
    w.send({"cmd": "shutdown"})
    assert w.close() == 0
    for raw in w.raw_lines:
        assert raw.endswith(b"\n")
        obj = json.loads(raw.decode("utf-8"))
        assert isinstance(obj, dict) and "type" in obj
    assert "initialisé".encode("utf-8") in b"".join(w.raw_lines)
