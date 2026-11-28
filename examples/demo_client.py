#!/usr/bin/env python3
"""Client de démonstration du worker scribe-voice (stdlib uniquement).

Lance le worker, envoie ``init``, affiche les événements JSON Lines, puis en boucle :
Entrée démarre l'enregistrement, une seconde Entrée l'arrête ; ``q`` + Entrée quitte.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKER = ROOT / "voice_worker.py"


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass


def _format_event(evt: dict[str, Any]) -> str:
    typ = evt.get("type", "?")
    if typ == "deps":
        if evt.get("ok"):
            return "[deps] dependances OK"
        return f"[deps] erreur : {evt.get('error', '')}"
    if typ == "ready":
        return f"[ready] version {evt.get('version')} - protocole {evt.get('protocol')}"
    if typ == "status":
        return f"[status] enregistrement={evt.get('recording')} - depsOk={evt.get('depsOk')}"
    if typ == "model":
        if evt.get("loading"):
            return "[model] chargement..."
        if evt.get("loaded"):
            return "[model] charge"
        return "[model] non charge"
    if typ == "recording":
        return f"[recording] {'actif' if evt.get('active') else 'arrete'}"
    if typ == "transcribing":
        return f"[transcribing] {'en cours' if evt.get('active') else 'termine'}"
    if typ == "transcript":
        parts = [f"[transcript] {evt.get('text', '')!r}"]
        cmd = evt.get("command")
        if isinstance(cmd, dict):
            parts.append(
                f"  -> commande ({cmd.get('keyword', '')}) : {cmd.get('text', '')!r}"
            )
        return "\n".join(parts)
    if typ == "confirmation":
        return (
            f"[confirmation] reponse={evt.get('answer')} - texte={evt.get('text', '')!r}"
        )
    if typ == "error":
        return f"[error] {evt.get('message', '')}"
    if typ == "pong":
        return "[pong]"
    return json.dumps(evt, ensure_ascii=False)


class WorkerSession:
    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        self.proc = proc
        self._q: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._thread.start()
        self.recording = False
        self._last_transcript: dict[str, Any] | None = None

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for raw in iter(self.proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                evt = {"type": "__parse_error__", "raw": line}
            if isinstance(evt, dict) and evt.get("type") == "transcript":
                self._last_transcript = evt
            print(_format_event(evt), flush=True)
            self._q.put(evt)
        self._q.put(None)

    def send(self, obj: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        payload = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        self.proc.stdin.write(payload)
        self.proc.stdin.flush()

    def wait_for(self, pred, timeout: float = 60.0) -> dict[str, Any]:
        import time

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("delai depasse en attente d'un evenement worker")
            try:
                evt = self._q.get(timeout=remaining)
            except queue.Empty:
                continue
            if evt is None:
                raise RuntimeError("stdout worker ferme")
            if pred(evt):
                return evt

    def wait_ready_and_model(self) -> None:
        self.wait_for(lambda e: e.get("type") == "deps")
        self.wait_for(lambda e: e.get("type") == "ready")
        self.wait_for(
            lambda e: e.get("type") == "model" and e.get("loaded") is True,
            timeout=120.0,
        )

    def shutdown(self) -> int:
        try:
            self.send({"cmd": "shutdown"})
        except (BrokenPipeError, OSError):
            pass
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        return self.proc.wait(timeout=30)


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "language": "fr",
        "model_size": args.model,
        "device": "cpu",
    }
    if args.models_dir:
        cfg["models_dir"] = args.models_dir
    if args.offline:
        cfg["offline"] = True
    if args.keyword:
        cfg["keyword"] = args.keyword
    return cfg


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Client de demo pour voice_worker.")
    p.add_argument(
        "--exe",
        type=Path,
        help="chemin vers voice_worker.exe (sinon python voice_worker.py a cote du depot)",
    )
    p.add_argument("--model", default="small", help="model_size pour init (defaut : small)")
    p.add_argument("--models-dir", default=None, help="dossier des modeles Whisper")
    p.add_argument(
        "--offline",
        action="store_true",
        help="mode hors ligne (modeles deja sur le disque)",
    )
    p.add_argument("--keyword", default=None, help="mot-cle vocal (defaut worker)")
    return p.parse_args(argv)


def worker_command(args: argparse.Namespace) -> list[str]:
    if args.exe:
        return [str(args.exe)]
    if not DEFAULT_WORKER.is_file():
        print(f"Worker introuvable : {DEFAULT_WORKER}", file=sys.stderr)
        sys.exit(2)
    return [sys.executable, str(DEFAULT_WORKER)]


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = parse_args(argv)
    cmd = worker_command(args)
    env = os.environ.copy()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(ROOT),
        env=env,
    )
    session = WorkerSession(proc)
    session.send({"cmd": "init", "config": build_config(args)})
    try:
        session.wait_ready_and_model()
    except (TimeoutError, RuntimeError) as exc:
        print(f"Echec a l'initialisation : {exc}", file=sys.stderr)
        session.shutdown()
        return 1

    print(
        "\nEntree : demarrer / arreter l'enregistrement - q + Entree : quitter\n",
        flush=True,
    )
    try:
        while True:
            try:
                line = sys.stdin.readline()
            except KeyboardInterrupt:
                print("\nInterruption.", flush=True)
                break
            if not line:
                break
            if line.strip().lower() == "q":
                break
            if not session.recording:
                session.send({"cmd": "start"})
                session.recording = True
            else:
                session.send({"cmd": "stop"})
                session.recording = False
                session.wait_for(
                    lambda e: e.get("type") == "transcript",
                    timeout=120.0,
                )
    finally:
        return session.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())