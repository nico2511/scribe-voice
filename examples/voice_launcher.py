#!/usr/bin/env python3
"""Lanceur vocal de demonstration : pilote le worker et execute des actions sur commande.

Reutilise le client de demo pour la session worker. Les actions sont definies dans un
fichier JSON (--actions).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable

_EXAMPLES = Path(__file__).resolve().parent
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

from demo_client import (  # noqa: E402
    ROOT,
    WorkerSession,
    _configure_stdio,
    build_config,
    worker_command,
)

DEFAULT_ACTIONS = _EXAMPLES / "launcher_actions.example.json"


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_command_text(text: str) -> str:
    """Casse et accents ignores, ponctuation de fin supprimee, espaces compactes."""
    t = strip_accents(text).casefold().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[\s.,;:!?…\-—]+$", "", t)
    return t.strip()


def phrase_matches(command_text: str, phrase: str) -> bool:
    norm_cmd = normalize_command_text(command_text)
    norm_phrase = normalize_command_text(phrase)
    if not norm_phrase:
        return False
    if norm_cmd == norm_phrase:
        return True
    return norm_cmd.startswith(norm_phrase + " ")


def load_actions(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Impossible de lire le fichier d'actions : {path} ({exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Fichier d'actions JSON invalide : {path} ({exc})") from exc
    if not isinstance(data, list):
        raise ValueError(
            f"Fichier d'actions invalide : {path} (un tableau JSON est attendu)"
        )
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(
                f"Fichier d'actions invalide : entree {i} n'est pas un objet"
            )
        if "phrases" not in entry or "action" not in entry:
            raise ValueError(
                f"Fichier d'actions invalide : entree {i} sans 'phrases' ou 'action'"
            )
        if not isinstance(entry["phrases"], list) or not entry["phrases"]:
            raise ValueError(
                f"Fichier d'actions invalide : entree {i}, 'phrases' doit etre un tableau non vide"
            )
        if not isinstance(entry["action"], dict) or "type" not in entry["action"]:
            raise ValueError(
                f"Fichier d'actions invalide : entree {i}, 'action' doit contenir 'type'"
            )
    return data


def find_action(
    command_text: str, entries: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for entry in entries:
        for phrase in entry["phrases"]:
            if phrase_matches(command_text, str(phrase)):
                return entry
    return None


def _expand_env(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value))


def open_target(target: str) -> None:
    path = _expand_env(target)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path], shell=False)
    else:
        subprocess.Popen(["xdg-open", path], shell=False)


def execute_action(action: dict[str, Any], *, dry_run: bool) -> None:
    typ = action.get("type")
    if typ == "run":
        args = action.get("args")
        if not isinstance(args, list) or not args:
            print("[launcher] action run invalide : args manquants", flush=True)
            return
        str_args = [str(a) for a in args]
        if dry_run:
            print(f"[launcher] dry-run run : {str_args!r}", flush=True)
            return
        subprocess.Popen(str_args, shell=False)
        print(f"[launcher] execute run : {str_args!r}", flush=True)
    elif typ == "open":
        target = action.get("target")
        if not isinstance(target, str) or not target.strip():
            print("[launcher] action open invalide : target manquant", flush=True)
            return
        resolved = _expand_env(target)
        if dry_run:
            print(f"[launcher] dry-run open : {resolved!r}", flush=True)
            return
        open_target(target)
        print(f"[launcher] execute open : {resolved!r}", flush=True)
    elif typ == "say":
        message = action.get("message", "")
        print(f"[launcher] {message}", flush=True)
    else:
        print(f"[launcher] type d'action inconnu : {typ!r}", flush=True)


def handle_command(
    session: WorkerSession,
    command_text: str,
    entries: list[dict[str, Any]],
    *,
    dry_run: bool,
    confirm_timeout: float = 4.0,
    send_confirm: Callable[[WorkerSession, float], str] | None = None,
    execute: Callable[[dict[str, Any], bool], None] | None = None,
) -> None:
    entry = find_action(command_text, entries)
    if entry is None:
        print(f"[launcher] commande inconnue : {command_text!r}", flush=True)
        return
    action = entry["action"]
    needs_confirm = bool(entry.get("confirm"))
    if needs_confirm:
        _send = send_confirm or _default_send_confirm
        answer = _send(session, confirm_timeout)
        if answer != "yes":
            print(f"[launcher] annule (reponse={answer})", flush=True)
            return
    runner = execute or (lambda a, dr: execute_action(a, dry_run=dr))
    runner(action, dry_run)


def _default_send_confirm(session: WorkerSession, timeout: float) -> str:
    session.send({"cmd": "confirm", "timeout": timeout})
    evt = session.wait_for(
        lambda e: e.get("type") == "confirmation",
        timeout=max(30.0, timeout + 10.0),
    )
    answer = evt.get("answer", "unknown")
    return str(answer) if answer is not None else "unknown"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Lanceur vocal de demonstration pour voice_worker."
    )
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
    p.add_argument(
        "--actions",
        type=Path,
        default=DEFAULT_ACTIONS,
        help="fichier JSON des actions (defaut : launcher_actions.example.json)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="affiche l'action sans l'executer",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = parse_args(argv)
    try:
        entries = load_actions(args.actions)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

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
                evt = session.wait_for(
                    lambda e: e.get("type") == "transcript",
                    timeout=120.0,
                )
                cmd_obj = evt.get("command")
                if isinstance(cmd_obj, dict):
                    text = str(cmd_obj.get("text", ""))
                    if text.strip():
                        handle_command(
                            session,
                            text,
                            entries,
                            dry_run=args.dry_run,
                        )
    finally:
        return session.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())