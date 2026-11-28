"""Lanceur vocal : normalisation, correspondance, actions et confirmation."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
sys.path.insert(0, str(EXAMPLES))

import voice_launcher as vl  # noqa: E402


@pytest.mark.parametrize(
    "command, phrase, expected",
    [
        ("Ouvre le bloc-notes.", "ouvre le bloc-notes", True),
        ("ouvre le bloc note", "ouvre le bloc note", True),
        ("OUVRE LE BLOC-NOTES", "ouvre le bloc-notes", True),
        ("ouvre le bloc note s il te plait", "ouvre le bloc note", True),
        ("verrouille ma session. Oui.", "verrouille ma session", True),
        ("verrouille ma session. non.", "verrouille ma session", True),
        ("ferme tout", "ouvre le bloc-notes", False),
        ("ouvre le bloc", "ouvre le bloc-notes", False),
    ],
)
def test_phrase_matches(command: str, phrase: str, expected: bool) -> None:
    assert vl.phrase_matches(command, phrase) is expected


@pytest.mark.parametrize(
    "text, first, rest",
    [
        ("verrouille ma session. Oui.", "verrouille ma session", "Oui."),
        ("alpha", "alpha", ""),
        ("un deux! trois", "un deux", "trois"),
    ],
)
def test_split_command_text(text: str, first: str, rest: str) -> None:
    assert vl.split_command_text(text) == (first, rest)


def test_command_had_premature_answer() -> None:
    assert vl.command_had_premature_answer("verrouille ma session. Oui.")
    assert vl.command_had_premature_answer("verrouille ma session. non merci")
    assert not vl.command_had_premature_answer("verrouille ma session")


def test_example_actions_match_verrouille_ma_session() -> None:
    entries = vl.load_actions(EXAMPLES / "launcher_actions.example.json")
    hit = vl.find_action_with_phrase("verrouille ma session. Oui.", entries)
    assert hit is not None
    assert hit[1] == "verrouille ma session"
    assert hit[0].get("confirm") is True


@pytest.mark.parametrize(
    "text, expected",
    [
        ("  Ouvre   le   bloc  ", "ouvre le bloc"),
        ("Écran verrouillé.", "ecran verrouille"),
        ("test…", "test"),
    ],
)
def test_normalize_command_text(text: str, expected: str) -> None:
    assert vl.normalize_command_text(text) == expected


def test_confirmation_prompt() -> None:
    assert vl.confirmation_prompt("verrouille la session") == (
        "Verrouille la session ? Dites oui ou non."
    )


def test_find_action_first_match() -> None:
    entries = [
        {"phrases": ["alpha"], "action": {"type": "say", "message": "a"}},
        {"phrases": ["beta"], "action": {"type": "say", "message": "b"}},
    ]
    hit = vl.find_action("beta", entries)
    assert hit is not None
    assert hit["action"]["message"] == "b"


def test_load_actions_ok(tmp_path: Path) -> None:
    p = tmp_path / "actions.json"
    p.write_text(
        json.dumps(
            [{"phrases": ["x"], "action": {"type": "say", "message": "m"}}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    data = vl.load_actions(p)
    assert len(data) == 1


@pytest.mark.parametrize(
    "content, msg",
    [
        ("not json", "JSON invalide"),
        ('{"x": 1}', "tableau JSON"),
        ("[]", None),
        ('[{"phrases": [], "action": {"type": "say"}}]', "phrases"),
    ],
)
def test_load_actions_errors(tmp_path: Path, content: str, msg: str | None) -> None:
    p = tmp_path / "bad.json"
    p.write_text(content, encoding="utf-8")
    if msg is None:
        assert vl.load_actions(p) == []
        return
    with pytest.raises(ValueError) as exc:
        vl.load_actions(p)
    assert msg in str(exc.value)


def test_load_actions_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as exc:
        vl.load_actions(tmp_path / "absent.json")
    assert "Impossible de lire" in str(exc.value)


def test_handle_command_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    session = MagicMock()
    vl.handle_command(session, "inconnu", [], dry_run=False)
    out = capsys.readouterr().out
    assert "[launcher] commande inconnue" in out


def test_dry_run_run(capsys: pytest.CaptureFixture[str]) -> None:
    entries = [
        {"phrases": ["go"], "action": {"type": "run", "args": ["echo", "hi"]}, "confirm": False}
    ]
    with patch.object(subprocess, "Popen") as popen:
        vl.handle_command(MagicMock(), "go", entries, dry_run=True)
        popen.assert_not_called()
    assert "dry-run run" in capsys.readouterr().out


def test_dry_run_open(capsys: pytest.CaptureFixture[str]) -> None:
    entries = [
        {"phrases": ["site"], "action": {"type": "open", "target": "https://example.com"}, "confirm": False}
    ]
    with patch.object(vl, "open_target") as ot:
        vl.handle_command(MagicMock(), "site", entries, dry_run=True)
        ot.assert_not_called()
    assert "dry-run open" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["yes", "no", "unknown"])
def test_confirm_path(answer: str, capsys: pytest.CaptureFixture[str]) -> None:
    entries = [
        {
            "phrases": ["lock"],
            "action": {"type": "run", "args": ["x"]},
            "confirm": True,
        }
    ]
    executed: list[bool] = []

    def fake_confirm(session: Any, timeout: float) -> str:
        assert timeout == vl.DEFAULT_CONFIRM_TIMEOUT
        return answer

    def fake_exec(action: dict[str, Any], dry_run: bool) -> None:
        executed.append(True)

    spk = vl.Speaker(mode="none")
    vl.handle_command(
        MagicMock(),
        "lock",
        entries,
        dry_run=False,
        speaker=spk,
        send_confirm=fake_confirm,
        execute=fake_exec,
    )
    out = capsys.readouterr().out
    assert "Dites oui ou non." in out
    if answer == "yes":
        assert executed == [True]
        assert "C'est fait." in out
    else:
        assert executed == []
        assert "Annule." in out


def test_run_never_uses_shell() -> None:
    entries = [
        {"phrases": ["x"], "action": {"type": "run", "args": ["cmd", "a"]}, "confirm": False}
    ]
    with patch.object(subprocess, "Popen") as popen:
        vl.handle_command(MagicMock(), "x", entries, dry_run=False, speaker=vl.Speaker(mode="none"))
        popen.assert_called_once_with(["cmd", "a"], shell=False)


class MockWorkerSession:
    def __init__(self, answer: str) -> None:
        self.sent: list[dict[str, Any]] = []
        self.answer = answer

    def send(self, obj: dict[str, Any]) -> None:
        self.sent.append(obj)

    def wait_for(self, pred, timeout: float = 60.0) -> dict[str, Any]:
        evt: dict[str, Any] = {
            "type": "confirmation",
            "answer": self.answer,
            "text": "reponse",
        }
        assert pred(evt)
        return evt


@pytest.mark.parametrize("answer", ["yes", "no", "unknown"])
def test_default_send_confirm_timeout(answer: str) -> None:
    s = MockWorkerSession(answer)
    got = vl._default_send_confirm(s, vl.DEFAULT_CONFIRM_TIMEOUT)
    assert got == answer
    assert s.sent == [{"cmd": "confirm", "timeout": vl.DEFAULT_CONFIRM_TIMEOUT}]


def test_premature_oui_reposes_question_not_auto_confirm(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entries = [
        {
            "phrases": ["verrouille ma session"],
            "action": {"type": "run", "args": ["x"]},
            "confirm": True,
        }
    ]
    confirm_calls: list[float] = []

    def fake_confirm(_session: Any, timeout: float) -> str:
        confirm_calls.append(timeout)
        return "no"

    with patch.object(subprocess, "Popen"):
        vl.handle_command(
            MagicMock(),
            "verrouille ma session. Oui.",
            entries,
            dry_run=False,
            speaker=vl.Speaker(mode="none"),
            send_confirm=fake_confirm,
        )
    out = capsys.readouterr().out
    assert confirm_calls == [vl.DEFAULT_CONFIRM_TIMEOUT]
    assert vl.REPOSE_QUESTION in out
    assert "Dites oui ou non." in out
    assert "Annule." in out


def test_prompt_then_confirm_order() -> None:
    timeline: list[str] = []
    entries = [
        {
            "phrases": ["lock"],
            "action": {"type": "run", "args": ["x"]},
            "confirm": True,
        }
    ]

    class TrackSpeaker:
        def announce_and_wait(self, text: str) -> None:
            timeline.append(f"prompt:{text}")
            print(text, flush=True)

        def announce(self, text: str) -> None:
            timeline.append(f"announce:{text}")
            print(text, flush=True)

    def fake_confirm(session: Any, timeout: float) -> str:
        timeline.append(f"confirm:{timeout}")
        return "yes"

    with patch.object(subprocess, "Popen"):
        vl.handle_command(
            MagicMock(),
            "lock",
            entries,
            dry_run=False,
            speaker=TrackSpeaker(),
            send_confirm=fake_confirm,
            confirm_timeout=6.0,
        )
    assert timeline[0].startswith("prompt:")
    assert timeline[1] == "confirm:6.0"
    assert timeline[-1] == "announce:C'est fait."


def test_handle_command_with_default_send_confirm(capsys: pytest.CaptureFixture[str]) -> None:
    s = MockWorkerSession("no")
    entries = [
        {"phrases": ["y"], "action": {"type": "say", "message": "ok"}, "confirm": True}
    ]
    with patch.object(vl, "execute_action") as ea:
        vl.handle_command(s, "y", entries, dry_run=False, speaker=vl.Speaker(mode="none"))
        ea.assert_not_called()
    out = capsys.readouterr().out
    assert "Annule." in out
    assert "Dites oui ou non." in out


def test_speaker_kokoro_missing_fallback(capsys: pytest.CaptureFixture[str]) -> None:
    sp = vl.Speaker(mode="auto")
    with patch.object(sp, "_kokoro_available", return_value=False):
        with patch.object(sp, "_synthesize") as syn:
            sp.announce("Bonjour")
            syn.assert_not_called()
    assert "Bonjour" in capsys.readouterr().out


def test_tts_none_skips_synthesis() -> None:
    sp = vl.Speaker(mode="none")
    with patch.object(sp, "_synthesize") as syn:
        sp.announce("test")
        syn.assert_not_called()
    assert sp._should_speak() is False


def test_say_action_announces_message(capsys: pytest.CaptureFixture[str]) -> None:
    entries = [
        {"phrases": ["hi"], "action": {"type": "say", "message": "Salut"}, "confirm": False}
    ]
    vl.handle_command(MagicMock(), "hi", entries, dry_run=False, speaker=vl.Speaker(mode="none"))
    assert "Salut" in capsys.readouterr().out


def test_parse_args_tts_and_confirm_timeout() -> None:
    args = vl.parse_args(["--tts", "none", "--confirm-timeout", "8"])
    assert args.tts == "none"
    assert args.confirm_timeout == 8.0
    assert args.tts_voice == "ff_siwis"


def test_parse_args_default_confirm_timeout() -> None:
    args = vl.parse_args([])
    assert args.confirm_timeout == 3.5


def test_hf_hub_offline_when_cache_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = (
        tmp_path
        / "hub"
        / "models--hexgrad--Kokoro-82M"
        / "snapshots"
        / "rev1"
    )
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"1")
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    assert vl.kokoro_model_cached()
    assert vl.apply_kokoro_hf_offline_if_cached(tts_online=False) is True
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    assert vl.apply_kokoro_hf_offline_if_cached(tts_online=True) is False
    assert os.environ.get("HF_HUB_OFFLINE") is None


def test_apply_tts_warning_filters() -> None:
    vl.apply_tts_warning_filters()


def test_resolve_worker_exe_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = tmp_path / "voice_worker.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(exe=Path("voice_worker.exe"))
    assert vl.launcher_worker_command(args) == [str(exe.resolve())]


def test_preload_runs_in_background_thread() -> None:
    ran = threading.Event()

    class PreloadSpeaker(vl.Speaker):
        def wants_preload(self) -> bool:
            return True

        def _preload_worker(self) -> None:
            ran.set()

    sp = PreloadSpeaker(mode="auto")
    sp.start_preload_background()
    assert sp._preload_thread is not None
    assert sp._preload_thread.is_alive() or ran.wait(2.0)
    sp.wait_preload(timeout=2.0)
    assert ran.is_set()


def test_verbose_confirm_delay(capsys: pytest.CaptureFixture[str]) -> None:
    s = MockWorkerSession("no")

    class WaitSpeaker(vl.Speaker):
        def announce_and_wait(self, text: str) -> None:
            print(text, flush=True)

    entries = [
        {"phrases": ["x"], "action": {"type": "say", "message": "m"}, "confirm": True}
    ]
    vl.handle_command(
        s,
        "x",
        entries,
        dry_run=False,
        speaker=WaitSpeaker(mode="none"),
        verbose=True,
    )
    out = capsys.readouterr().out
    assert "delai question -> confirmation" in out