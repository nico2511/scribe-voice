"""Fixtures communes.

On redirige HOME / USERPROFILE vers un dossier temporaire avant l'import de
``voice_worker`` pour ne rien écrire dans le profil réel.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKES = Path(__file__).resolve().parent / "fakes"
WORKER = ROOT / "voice_worker.py"

_HOME = tempfile.mkdtemp(prefix="scribe-voice-home-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME
if str(FAKES) not in sys.path:
    sys.path.insert(0, str(FAKES))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Événements autorisés sur stdout (contrat v1.0).
EVENT_TYPES = {
    "deps", "ready", "status", "model", "recording",
    "transcribing", "transcript", "confirmation", "error", "pong",
}


class WorkerProcess:
    """Lance ``voice_worker.py`` en sous-processus et parle JSON Lines."""

    def __init__(self, tmp_path: Path, env_extra: dict[str, str] | None = None):
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        env = dict(os.environ)
        env.update({
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONPATH": os.pathsep.join([str(FAKES), env.get("PYTHONPATH", "")]).rstrip(os.pathsep),
            "PYTHONUNBUFFERED": "1",
            # PATH sans nvidia-smi garanti n'est pas nécessaire : absence de GPU -> CPU.
        })
        for key in (
            "FAKE_PYAUDIO_IMPORT_ERROR",
            "FAKE_PYAUDIO_FAIL_OPEN",
            "FAKE_WHISPER",
            "FAKE_VAD",
            "SCRIBE_VOICE_MODELS_DIR",
        ):
            env.pop(key, None)
        env.update(env_extra or {})
        self.home = home
        self.proc = subprocess.Popen(
            [sys.executable, str(WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(tmp_path),
        )
        self.events: list[dict] = []
        self.raw_lines: list[bytes] = []
        self._q: queue.Queue = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for raw in iter(self.proc.stdout.readline, b""):
            self.raw_lines.append(raw)
            try:
                evt = json.loads(raw.decode("utf-8"))
            except ValueError:
                evt = {"type": "__invalid__", "raw": raw}
            self._q.put(evt)
        self._q.put(None)

    def send(self, obj: dict | str) -> None:
        assert self.proc.stdin is not None
        line = obj if isinstance(obj, str) else json.dumps(obj)  # ASCII (ensure_ascii)
        self.proc.stdin.write((line + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def wait_for(self, pred, timeout: float = 15.0) -> dict:
        """Attend le prochain événement satisfaisant ``pred`` (les autres sont conservés)."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"timeout ; événements reçus : {self.events}")
            try:
                evt = self._q.get(timeout=remaining)
            except queue.Empty:
                continue
            if evt is None:
                raise AssertionError(f"stdout fermé ; événements reçus : {self.events}")
            self.events.append(evt)
            if pred(evt):
                return evt

    def wait_type(self, typ: str, timeout: float = 15.0, **fields) -> dict:
        return self.wait_for(
            lambda e: e.get("type") == typ and all(e.get(k) == v for k, v in fields.items()),
            timeout,
        )

    def drain(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                evt = self._q.get(timeout=max(0.01, end - time.monotonic()))
            except queue.Empty:
                break
            if evt is None:
                break
            self.events.append(evt)

    def close(self, timeout: float = 10.0) -> int:
        try:
            if self.proc.poll() is None and self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            raise


@pytest.fixture
def worker_factory(tmp_path):
    procs: list[WorkerProcess] = []

    def _make(**env_extra: str) -> WorkerProcess:
        w = WorkerProcess(tmp_path, env_extra)
        procs.append(w)
        return w

    yield _make
    for w in procs:
        if w.proc.poll() is None:
            w.proc.kill()
            w.proc.wait()
        # Contrat : stdout ne contient QUE des objets JSON typés, une ligne chacun.
        w.drain(0.2)
        for evt in w.events:
            assert evt.get("type") in EVENT_TYPES, f"événement hors contrat : {evt!r}"
