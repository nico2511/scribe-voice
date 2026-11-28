"""Lanceur vocal : normalisation, correspondance, actions et confirmation."""
from __future__ import annotations

import json
import subprocess
import sys
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
        ("ferme tout", "ouvre le bloc-notes", False),
        ("ouvre le bloc", "ouvre le bloc-notes", False),
    ],
)
def test_phrase_matches(command: str, phrase: str, expected: bool) -> None:
    assert vl.phrase_matches(command, phrase) is expected


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
            "action": {"type": "say", "message": "locked"},
            "confirm": True,
        }
    ]
    executed: list[bool] = []

    def fake_confirm(session: Any, timeout: float) -> str:
        assert timeout == 4.0
        return answer

    def fake_exec(action: dict[str, Any], dry_run: bool) -> None:
        executed.append(True)

    vl.handle_command(
        MagicMock(),
        "lock",
        entries,
        dry_run=False,
        send_confirm=fake_confirm,
        execute=fake_exec,
    )
    out = capsys.readouterr().out
    if answer == "yes":
        assert executed == [True]
        assert "annule" not in out
    else:
        assert executed == []
        assert f"annule (reponse={answer})" in out


def test_run_never_uses_shell() -> None:
    entries = [
        {"phrases": ["x"], "action": {"type": "run", "args": ["cmd", "a"]}, "confirm": False}
    ]
    with patch.object(subprocess, "Popen") as popen:
        vl.handle_command(MagicMock(), "x", entries, dry_run=False)
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
def test_default_send_confirm(answer: str) -> None:
    s = MockWorkerSession(answer)
    got = vl._default_send_confirm(s, 4.0)
    assert got == answer
    assert s.sent == [{"cmd": "confirm", "timeout": 4.0}]


def test_handle_command_with_default_send_confirm(capsys: pytest.CaptureFixture[str]) -> None:
    s = MockWorkerSession("no")
    entries = [
        {"phrases": ["y"], "action": {"type": "say", "message": "ok"}, "confirm": True}
    ]
    with patch.object(vl, "execute_action") as ea:
        vl.handle_command(s, "y", entries, dry_run=False)
        ea.assert_not_called()
    assert "annule (reponse=no)" in capsys.readouterr().out