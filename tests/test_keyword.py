"""Mot-clé configurable, champ ``command`` et confirmation (T4 v1.1)."""
from __future__ import annotations

import json
import time

import pytest

import voice_keyword as vk
import voice_worker as vw

INIT = {"cmd": "init", "config": {"language": "fr", "model_size": "base", "device": "cpu"}}


def test_parse_command_scribe_prefix():
    cfg = vk.KeywordConfig.from_config({"keyword": "Scribe"})
    cmd = cfg.parse_command("Scribe, corrige le texte.")
    assert cmd == {"keyword": "Scribe", "text": "corrige le texte."}


def test_parse_command_not_at_start():
    cfg = vk.KeywordConfig.from_config({"keyword": "Scribe"})
    assert cfg.parse_command("le scribe corrige") is None


def test_parse_command_custom_keyword_and_alias():
    cfg = vk.KeywordConfig.from_config({
        "keyword": "Fresh",
        "keyword_aliases": ["frèche", "freche"],
    })
    assert cfg.parse_command("Frèche, ouvre le menu.") == {
        "keyword": "Fresh",
        "text": "ouvre le menu.",
    }
    assert cfg.parse_command("FRECHE: stop.") == {
        "keyword": "Fresh",
        "text": "stop.",
    }


def test_parse_command_case_and_accents():
    cfg = vk.KeywordConfig.from_config({"keyword": "Scribe"})
    assert cfg.parse_command("  … SCRIBE — résume.") == {
        "keyword": "Scribe",
        "text": "résume.",
    }


def test_initial_prompt_from_keyword():
    cfg = vk.KeywordConfig.from_config({"keyword": "Dictée"})
    assert cfg.initial_prompt() == "Dictée."


def test_keyword_only_custom():
    cfg = vk.KeywordConfig.from_config({"keyword": "Fresh", "keyword_aliases": ["frèche"]})
    assert cfg.is_keyword_only("Fresh !")
    assert cfg.is_keyword_only("frèche, frèche.")
    assert not cfg.is_keyword_only("Fresh, vas-y.")


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("Oui.", "yes"),
        ("ouais", "yes"),
        ("D'accord", "yes"),
        ("vas-y", "yes"),
        ("Non merci", "no"),
        ("annule tout", "no"),
        ("peut-être", "unknown"),
        ("", "unknown"),
    ],
)
def test_classify_confirmation(text, answer):
    assert vk.classify_confirmation(text) == answer


def test_transcript_command_payload_helper():
    payload = vk.transcript_command_payload("Scribe, test.", {"keyword": "Scribe"})
    assert payload == {"keyword": "Scribe", "text": "test."}


def test_dictation_emits_command_field(worker_factory, tmp_path):
    fw = json.dumps({"texts": ["Scribe, corrige le texte."]})
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send(INIT)
    w.wait_type("model", loaded=True)
    w.send({"cmd": "toggle"})
    w.wait_type("recording", active=True)
    time.sleep(1.0)
    w.send({"cmd": "toggle"})
    w.wait_type("transcript", timeout=30)
    tr = w.events[-1]
    assert tr["text"] == "Scribe, corrige le texte."
    assert tr["command"] == {"keyword": "Scribe", "text": "corrige le texte."}
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_v10_client_no_command_without_keyword(worker_factory, tmp_path):
    fw = json.dumps({"texts": ["Bonjour tout le monde."]})
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send(INIT)
    w.wait_type("model", loaded=True)
    w.send({"cmd": "toggle"})
    w.wait_type("recording", active=True)
    time.sleep(1.0)
    w.send({"cmd": "toggle"})
    tr = w.wait_type("transcript", timeout=30)
    assert tr["text"] == "Bonjour tout le monde."
    assert "command" not in tr
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_confirm_yes_no_unknown(worker_factory, tmp_path):
    fw = json.dumps({"texts": ["oui", "non", "peut-être demain"]})
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send(INIT)
    w.wait_type("model", loaded=True)
    for expected in ("yes", "no", "unknown"):
        w.send({"cmd": "confirm", "timeout": 0.6})
        conf = w.wait_type("confirmation", timeout=30)
        assert conf["answer"] == expected
        assert isinstance(conf["text"], str)
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_confirm_during_recording_errors(worker_factory, tmp_path):
    fw = json.dumps({"texts": ["oui"]})
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send(INIT)
    w.wait_type("model", loaded=True)
    w.send({"cmd": "toggle"})
    w.wait_type("recording", active=True)
    w.send({"cmd": "confirm", "timeout": 1})
    err = w.wait_type("error")
    assert "Confirmation impossible" in err["message"]
    w.send({"cmd": "toggle"})
    w.wait_type("transcript", timeout=30)
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_custom_keyword_prompt_in_whisper_call(worker_factory, tmp_path):
    calls = tmp_path / "calls.jsonl"
    fw = json.dumps({
        "texts": ["Dictée, lance la capture."],
        "calls_file": str(calls),
    })
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send({
        "cmd": "init",
        "config": {
            "language": "fr",
            "model_size": "base",
            "device": "cpu",
            "keyword": "Dictée",
        },
    })
    w.wait_type("model", loaded=True)
    w.send({"cmd": "toggle"})
    w.wait_type("recording", active=True)
    time.sleep(1.0)
    w.send({"cmd": "toggle"})
    tr = w.wait_type("transcript", timeout=30)
    assert tr.get("command", {}).get("text") == "lance la capture."
    lines = [json.loads(l) for l in calls.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["initial_prompt"] == "Dictée."
    w.send({"cmd": "shutdown"})
    assert w.close() == 0


def test_keyword_only_filtered_custom(worker_factory, tmp_path):
    fw = json.dumps({"texts": ["Fresh Fresh."]})
    w = worker_factory(FAKE_WHISPER=fw)
    w.wait_type("ready")
    w.send({
        "cmd": "init",
        "config": {
            "language": "fr",
            "model_size": "base",
            "device": "cpu",
            "keyword": "Fresh",
        },
    })
    w.wait_type("model", loaded=True)
    w.send({"cmd": "toggle"})
    w.wait_type("recording", active=True)
    time.sleep(1.0)
    w.send({"cmd": "toggle"})
    tr = w.wait_type("transcript", timeout=30)
    assert tr == {"type": "transcript", "text": ""}
    w.send({"cmd": "shutdown"})
    assert w.close() == 0
