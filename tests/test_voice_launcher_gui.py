"""Lanceur graphique : machine d'etats, file d'evenements, resolution du worker (sans fenetre)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
sys.path.insert(0, str(EXAMPLES))

import voice_launcher_gui as vlg  # noqa: E402


def test_protocol_supports_end_on_silence() -> None:
    assert vlg.protocol_supports_end_on_silence(5) is True
    assert vlg.protocol_supports_end_on_silence(6) is True
    assert vlg.protocol_supports_end_on_silence(4) is False
    assert vlg.protocol_supports_end_on_silence(None) is False


@pytest.mark.parametrize(
    "raw, expected",
    [
        (5, 5),
        (5.0, 5),
        ("5", None),
        (True, None),
        (None, None),
    ],
)
def test_coerce_protocol(raw, expected) -> None:
    assert vlg.coerce_protocol(raw) == expected


def test_state_machine_transitions() -> None:
    sm = vlg.LauncherStateMachine(vlg.LauncherState.DEMARRAGE)
    sm.transition(vlg.LauncherState.PRET)
    assert sm.state == vlg.LauncherState.PRET
    sm.transition(vlg.LauncherState.ECOUTE)
    sm.transition(vlg.LauncherState.TRANSCRIPTION)
    sm.transition(vlg.LauncherState.PRET)


def test_thread_safe_bridge_hotkey_schedules() -> None:
    scheduled: list[str] = []

    def schedule(fn) -> None:
        fn()
        scheduled.append("ok")

    bridge = vlg.ThreadSafeBridge(schedule)
    app = MagicMock()
    bridge.attach(app)
    bridge.emit_hotkey("f8")
    bridge.pump()
    app.on_hotkey_f8.assert_called_once()
    assert scheduled == ["ok"]


def test_thread_safe_bridge_event_queue() -> None:
    bridge = vlg.ThreadSafeBridge(lambda fn: fn())
    received: list[vlg.AppEvent] = []

    class App:
        def on_bridge_event(self, evt: vlg.AppEvent) -> None:
            received.append(evt)

    app = App()
    bridge.attach(app)
    bridge.post("worker", {"type": "pong"})
    bridge.pump()
    assert len(received) == 1
    assert received[0].kind == "worker"


def test_resolve_gui_worker_exe_beside_anchor(tmp_path: Path) -> None:
    anchor = tmp_path / "voice_launcher_gui.py"
    anchor.write_text("#", encoding="utf-8")
    exe = tmp_path / "voice_worker.exe"
    exe.write_bytes(b"MZ")
    found = vlg.resolve_gui_worker_exe_path(anchor)
    assert found == exe.resolve()


def test_resolve_gui_worker_exe_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchor = tmp_path / "sub" / "gui.py"
    anchor.parent.mkdir(parents=True)
    anchor.write_text("#", encoding="utf-8")
    env_exe = tmp_path / "other" / "voice_worker.exe"
    env_exe.parent.mkdir(parents=True)
    env_exe.write_bytes(b"MZ")
    monkeypatch.setenv("SCRIBE_VOICE_WORKER", str(env_exe))
    assert vlg.resolve_gui_worker_exe_path(anchor) == env_exe.resolve()


def test_worker_command_for_gui_prefers_cli_exe(tmp_path: Path) -> None:
    cli = tmp_path / "w.exe"
    cli.write_bytes(b"MZ")
    args = MagicMock()
    args.exe = cli
    assert vlg.worker_command_for_gui(args, anchor=tmp_path / "gui.py") == [str(cli.resolve())]


def test_worker_command_for_gui_missing_raises(tmp_path: Path) -> None:
    args = MagicMock()
    args.exe = None
    anchor = tmp_path / "voice_launcher_gui.py"
    anchor.write_text("#", encoding="utf-8")
    with pytest.raises(FileNotFoundError) as exc:
        vlg.worker_command_for_gui(args, anchor=anchor)
    assert "SCRIBE_VOICE_WORKER" in str(exc.value)


@pytest.fixture
def tk_headless_available() -> bool:
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@pytest.mark.skipif(
    not bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    and sys.platform != "win32",
    reason="Pas d'affichage pour Tkinter",
)
def test_launcher_context_defaults() -> None:
    ctx = vlg.LauncherContext()
    assert ctx.state == vlg.LauncherState.DEMARRAGE
    assert ctx.end_on_silence_supported is False