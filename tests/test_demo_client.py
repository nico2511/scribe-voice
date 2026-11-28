"""Client de démo : pilotage stdin et détection de commande avec faux Whisper."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo_client.py"
FAKES = Path(__file__).resolve().parent / "fakes"


def _run_demo_cycle(tmp_path: Path, transcript: str) -> str:
    home = tmp_path / "home"
    home.mkdir()
    fw = json.dumps({"texts": [transcript]})
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PYTHONPATH": os.pathsep.join([str(FAKES), str(ROOT)]),
        "PYTHONUNBUFFERED": "1",
        "FAKE_WHISPER": fw,
        "FAKE_VAD": '{"has_speech": true}',
    }
    proc = subprocess.Popen(
        [sys.executable, str(DEMO), "--model", "base"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(ROOT),
        text=True,
        bufsize=1,
    )
    collected: list[str] = []

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            collected.append(line)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    assert proc.stdin is not None

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        blob = "".join(collected)
        if "[model] chargé" in blob:
            break
        time.sleep(0.05)
    else:
        proc.kill()
        pytest.fail(f"timeout init ; sortie : {collected!r}")

    proc.stdin.write("\n")
    proc.stdin.flush()
    time.sleep(0.8)
    proc.stdin.write("\n")
    proc.stdin.flush()
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        blob = "".join(collected)
        if "→ commande" in blob:
            break
        time.sleep(0.05)
    else:
        proc.kill()
        pytest.fail(f"timeout transcript ; sortie : {collected!r}")

    proc.stdin.write("q\n")
    proc.stdin.flush()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    thread.join(timeout=2)
    return "".join(collected)


def test_demo_client_majordome_command(tmp_path):
    out = _run_demo_cycle(tmp_path, "Majordome ouvre la note.")
    assert "Majordome ouvre la note." in out
    assert "→ commande (Majordome)" in out
    assert "ouvre la note." in out