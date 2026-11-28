#!/usr/bin/env python3
"""Lanceur vocal graphique de demonstration (Tkinter, un seul fichier)."""
from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal

_EXAMPLES = Path(__file__).resolve().parent
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

from demo_client import ROOT, WorkerSession, _configure_stdio, build_config  # noqa: E402

import voice_launcher as vl  # noqa: E402

GUI_MODULE = Path(__file__).resolve()
MIN_PROTOCOL_END_ON_SILENCE = 5

HotkeyKind = Literal["f8"]


class LauncherState(str, Enum):
    DEMARRAGE = "demarrage"
    PRET = "pret"
    ECOUTE = "ecoute"
    TRANSCRIPTION = "transcription"
    CONFIRMATION = "confirmation"
    ERREUR = "erreur"


STATE_LABELS: dict[LauncherState, str] = {
    LauncherState.DEMARRAGE: "Démarrage",
    LauncherState.PRET: "Prêt",
    LauncherState.ECOUTE: "Écoute",
    LauncherState.TRANSCRIPTION: "Transcription",
    LauncherState.CONFIRMATION: "Confirmation",
    LauncherState.ERREUR: "Erreur",
}

STATE_COLORS: dict[LauncherState, str] = {
    LauncherState.DEMARRAGE: "#f0ad4e",
    LauncherState.PRET: "#5cb85c",
    LauncherState.ECOUTE: "#5bc0de",
    LauncherState.TRANSCRIPTION: "#f0ad4e",
    LauncherState.CONFIRMATION: "#d9534f",
    LauncherState.ERREUR: "#d9534f",
}


@dataclass(frozen=True)
class AppEvent:
    kind: str
    payload: Any = None


@dataclass
class LauncherContext:
    state: LauncherState = LauncherState.DEMARRAGE
    last_phrase: str = ""
    last_action: str = ""
    last_result: str = ""
    worker_version: str = ""
    worker_protocol: int | None = None
    recording: bool = False
    end_on_silence_supported: bool = False


def gui_anchor_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return GUI_MODULE


def resolve_gui_worker_exe_path(anchor: Path | None = None) -> Path | None:
    """SCRIBE_VOICE_WORKER puis voice_worker.exe a cote de l'exe ou du script graphique."""
    if env := os.environ.get("SCRIBE_VOICE_WORKER"):
        p = Path(os.path.expandvars(os.path.expanduser(env)))
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        else:
            p = p.resolve()
        if p.is_file():
            return p
    base = (anchor or gui_anchor_path()).resolve().parent
    candidate = base / "voice_worker.exe"
    if candidate.is_file():
        return candidate
    return None


def worker_command_for_gui(
    args: argparse.Namespace, *, anchor: Path | None = None
) -> list[str]:
    """--exe, SCRIBE_VOICE_WORKER, voice_worker.exe a cote du lanceur graphique."""
    if args.exe:
        resolved = vl.resolve_worker_exe_path(Path(args.exe))
        if not resolved.is_file():
            raise FileNotFoundError(f"Worker introuvable : {resolved}")
        return [str(resolved)]
    default = resolve_gui_worker_exe_path(anchor)
    if default is not None:
        return [str(default)]
    base = (anchor or gui_anchor_path()).resolve().parent
    raise FileNotFoundError(
        f"Worker introuvable : indiquez --exe, SCRIBE_VOICE_WORKER "
        f"ou placez voice_worker.exe dans {base}"
    )


def protocol_supports_end_on_silence(protocol: int | None) -> bool:
    if protocol is None:
        return False
    return protocol >= MIN_PROTOCOL_END_ON_SILENCE


def coerce_protocol(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


class LauncherStateMachine:
    """Transitions simples pour tests et interface."""

    def __init__(self, initial: LauncherState = LauncherState.DEMARRAGE) -> None:
        self.state = initial

    def transition(self, new: LauncherState) -> LauncherState:
        allowed: dict[LauncherState, set[LauncherState]] = {
            LauncherState.DEMARRAGE: {
                LauncherState.PRET,
                LauncherState.ERREUR,
            },
            LauncherState.PRET: {
                LauncherState.ECOUTE,
                LauncherState.ERREUR,
            },
            LauncherState.ECOUTE: {
                LauncherState.TRANSCRIPTION,
                LauncherState.PRET,
                LauncherState.ERREUR,
            },
            LauncherState.TRANSCRIPTION: {
                LauncherState.CONFIRMATION,
                LauncherState.PRET,
                LauncherState.ERREUR,
            },
            LauncherState.CONFIRMATION: {
                LauncherState.PRET,
                LauncherState.ERREUR,
            },
            LauncherState.ERREUR: {LauncherState.DEMARRAGE, LauncherState.PRET},
        }
        if new == self.state:
            return self.state
        if new in allowed.get(self.state, set()) or new == LauncherState.ERREUR:
            self.state = new
            return self.state
        self.state = new
        return self.state


class ThreadSafeBridge:
    """File thread-safe + publication vers le thread Tk."""

    def __init__(self, tk_schedule: Callable[[Callable[[], None]], None]) -> None:
        self._q: queue.Queue[AppEvent] = queue.Queue()
        self._tk_schedule = tk_schedule

    def post(self, kind: str, payload: Any = None) -> None:
        self._q.put(AppEvent(kind=kind, payload=payload))

    def emit_hotkey(self, key: HotkeyKind) -> None:
        self.post("hotkey", key)

    def pump(self) -> None:
        while True:
            try:
                evt = self._q.get_nowait()
            except queue.Empty:
                break
            self._dispatch(evt)

    def _dispatch(self, evt: AppEvent) -> None:
        if evt.kind == "hotkey":
            self._tk_schedule(lambda e=evt: self._on_hotkey(e))
        else:
            self._tk_schedule(lambda e=evt: self._on_generic(e))

    def _on_hotkey(self, evt: AppEvent) -> None:
        if hasattr(self, "_app") and self._app is not None:
            self._app.on_hotkey_f8()

    def _on_generic(self, evt: AppEvent) -> None:
        if hasattr(self, "_app") and self._app is not None:
            self._app.on_bridge_event(evt)

    def attach(self, app: Any) -> None:
        self._app = app


class QuietWorkerSession(WorkerSession):
    """Session worker sans affichage console ; journal via rappel optionnel."""

    def __init__(
        self,
        proc: subprocess.Popen[bytes],
        *,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._on_event = on_event
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
                evt = __import__("json").loads(line)
            except __import__("json").JSONDecodeError:
                evt = {"type": "__parse_error__", "raw": line}
            if isinstance(evt, dict):
                if evt.get("type") == "transcript":
                    self._last_transcript = evt
                if self._on_event is not None:
                    self._on_event(evt)
            self._q.put(evt if isinstance(evt, dict) else {"type": "__bad__"})
        self._q.put(None)


class JournalSpeaker(vl.Speaker):
    """TTS Kokoro heritee du lanceur console ; messages aussi dans le journal."""

    def __init__(
        self,
        log: Callable[[str], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._log = log

    def announce(self, text: str) -> None:
        self._log(text)
        if not self._should_speak():
            return
        audio = self._synthesize(text)
        if audio is not None:
            self._play_blocking(audio)

    def announce_and_wait(self, text: str) -> None:
        self.announce(text)


class GlobalHotkeyListener:
    """F8 global sous Windows (RegisterHotKey) ; sinon raccourci fenetre uniquement."""

    def __init__(self, bridge: ThreadSafeBridge) -> None:
        self._bridge = bridge
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._registered = False

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        self._thread = threading.Thread(target=self._run_win, name="f8-hotkey", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if sys.platform == "win32" and self._registered:
            try:
                import ctypes

                ctypes.windll.user32.UnregisterHotKey(None, 1)
            except Exception:
                pass
            self._registered = False

    def _run_win(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        MOD_NONE = 0
        VK_F8 = 0x77
        WM_HOTKEY = 0x0312
        HOTKEY_ID = 1
        if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_NONE, VK_F8):
            return
        self._registered = True
        msg = wintypes.MSG()
        while not self._stop.is_set():
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self._bridge.emit_hotkey("f8")
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._registered:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False


def parse_gui_args(argv: list[str] | None = None) -> argparse.Namespace:
    return vl.parse_args(argv)


class VoiceLauncherGuiApp:
    def __init__(self, args: argparse.Namespace) -> None:
        import tkinter as tk
        from tkinter import scrolledtext, ttk

        self.args = args
        self.ctx = LauncherContext()
        self.fsm = LauncherStateMachine()
        self._entries: list[dict[str, Any]] = []
        self._session: QuietWorkerSession | None = None
        self._speaker: JournalSpeaker | None = None
        self._init_error: str | None = None
        self._shutdown_done = False
        self._command_lock = threading.Lock()
        self._worker_proc: subprocess.Popen[bytes] | None = None

        self.root = tk.Tk()
        self.root.title("Scribe Voice — lanceur démo")
        self.root.minsize(360, 420)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.bridge = ThreadSafeBridge(self._schedule_ui)
        self.bridge.attach(self)
        self._hotkey = GlobalHotkeyListener(self.bridge)

        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)

        self._status_canvas = tk.Canvas(top, width=18, height=18, highlightthickness=0)
        self._status_canvas.pack(side="left")
        self._status_oval = self._status_canvas.create_oval(2, 2, 16, 16, fill=STATE_COLORS[self.ctx.state])
        self._status_label = ttk.Label(top, text=STATE_LABELS[self.ctx.state])
        self._status_label.pack(side="left", padx=6)
        self._worker_info = ttk.Label(top, text="")
        self._worker_info.pack(side="right")

        ttk.Label(self.root, text="Dernière phrase").pack(anchor="w", padx=8)
        self._phrase_var = tk.StringVar(value="—")
        ttk.Label(self.root, textvariable=self._phrase_var, wraplength=340).pack(
            anchor="w", padx=8
        )

        ttk.Label(self.root, text="Dernière action").pack(anchor="w", padx=8, pady=(8, 0))
        self._action_var = tk.StringVar(value="—")
        ttk.Label(self.root, textvariable=self._action_var, wraplength=340).pack(
            anchor="w", padx=8
        )
        self._result_var = tk.StringVar(value="")
        ttk.Label(self.root, textvariable=self._result_var, wraplength=340).pack(
            anchor="w", padx=8
        )

        ttk.Label(self.root, text="Journal").pack(anchor="w", padx=8, pady=(8, 0))
        self._log = scrolledtext.ScrolledText(self.root, height=12, state="disabled", wrap="word")
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

        btn_row = ttk.Frame(self.root)
        btn_row.pack(fill="x", padx=8, pady=8)
        ttk.Button(btn_row, text="Quitter", command=self.quit).pack(side="right")
        self.root.bind("<F8>", lambda _e: self.on_hotkey_f8())

        self._log_line("Lanceur graphique — F8 démarre ou arrête l'enregistrement.")
        if sys.platform != "win32":
            self._log_line("Raccourci F8 global : Windows uniquement ; ici F8 avec la fenêtre active.")

        self._set_state(LauncherState.DEMARRAGE)
        threading.Thread(target=self._bootstrap, name="gui-bootstrap", daemon=True).start()
        self._hotkey.start()
        self._schedule_pump()

    def _schedule_ui(self, fn: Callable[[], None]) -> None:
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def _schedule_pump(self) -> None:
        self.bridge.pump()
        try:
            self.root.after(50, self._schedule_pump)
        except Exception:
            pass

    def _log_line(self, msg: str) -> None:
        def write() -> None:
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n")
            self._log.see("end")
            self._log.configure(state="disabled")

        self._schedule_ui(write)

    def _set_state(self, state: LauncherState) -> None:
        self.fsm.transition(state)
        self.ctx.state = self.fsm.state
        color = STATE_COLORS.get(self.ctx.state, "#999")
        label = STATE_LABELS.get(self.ctx.state, self.ctx.state.value)

        def refresh() -> None:
            self._status_canvas.itemconfig(self._status_oval, fill=color)
            self._status_label.configure(text=label)

        self._schedule_ui(refresh)

    def _update_worker_banner(self) -> None:
        if self.ctx.worker_version or self.ctx.worker_protocol is not None:
            proto = (
                str(self.ctx.worker_protocol)
                if self.ctx.worker_protocol is not None
                else "?"
            )
            txt = f"Worker {self.ctx.worker_version or '?'} — protocole {proto}"
            self._schedule_ui(lambda: self._worker_info.configure(text=txt))

    def _bootstrap(self) -> None:
        try:
            self._entries = vl.load_actions(self.args.actions)
        except ValueError as exc:
            self._fail_init(str(exc))
            return

        self._speaker = JournalSpeaker(
            self._log_line,
            mode=self.args.tts,
            voice=self.args.tts_voice,
            dry_run=self.args.dry_run,
            tts_online=self.args.tts_online,
        )
        if not self.args.dry_run:
            self._speaker.start_preload_background()

        try:
            cmd = worker_command_for_gui(self.args)
        except FileNotFoundError as exc:
            self._fail_init(str(exc))
            return

        self._log_line(f"Worker : {cmd[0]}")
        env = os.environ.copy()
        try:
            self._worker_proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(ROOT),
                env=env,
            )
        except OSError as exc:
            self._fail_init(f"Impossible de lancer le worker : {exc}")
            return

        def on_evt(evt: dict[str, Any]) -> None:
            self.bridge.post("worker", evt)

        self._session = QuietWorkerSession(self._worker_proc, on_event=on_evt)
        self._session.send({"cmd": "init", "config": build_config(self.args)})

        worker_ok = True
        try:
            self._wait_worker_ready_blocking()
        except (TimeoutError, RuntimeError) as exc:
            worker_ok = False
            self._fail_init(f"Échec à l'initialisation : {exc}")

        if not worker_ok:
            return

        tts_ok = self._speaker.wait_preload() if not self.args.dry_run else True
        if not tts_ok and self._speaker.wants_preload():
            self._log_line("[avertissement] synthèse vocale non préchargée")

        if self.ctx.end_on_silence_supported:
            self._log_line(
                f"Arrêt sur silence activé ({self.args.end_on_silence_ms} ms)."
            )
        else:
            self._log_line(
                "Worker sans protocole 5 : arrêt sur silence indisponible ; "
                "appuyez sur F8 pour arrêter l'enregistrement."
            )

        self._speaker.announce(vl.LAUNCHER_READY)
        self._set_state(LauncherState.PRET)
        self._update_worker_banner()

    def _wait_worker_ready_blocking(self) -> None:
        assert self._session is not None
        self._session.wait_for(lambda e: e.get("type") == "deps")
        ready = self._session.wait_for(lambda e: e.get("type") == "ready")
        version = str(ready.get("version", ""))
        protocol = coerce_protocol(ready.get("protocol"))
        self.ctx.worker_version = version
        self.ctx.worker_protocol = protocol
        self.ctx.end_on_silence_supported = protocol_supports_end_on_silence(protocol)
        self._log_line(f"[ready] version {version} — protocole {protocol}")
        self._session.wait_for(
            lambda e: e.get("type") == "model" and e.get("loaded") is True,
            timeout=120.0,
        )

    def _fail_init(self, message: str) -> None:
        self._init_error = message
        self._log_line(message)
        self._set_state(LauncherState.ERREUR)
        if self._session is not None:
            try:
                self._session.shutdown()
            except Exception:
                pass
        elif self._worker_proc is not None:
            try:
                self._worker_proc.terminate()
            except Exception:
                pass

    def on_bridge_event(self, evt: AppEvent) -> None:
        if evt.kind != "worker" or not isinstance(evt.payload, dict):
            return
        self._handle_worker_event(evt.payload)

    def _handle_worker_event(self, evt: dict[str, Any]) -> None:
        typ = evt.get("type")
        if typ == "recording":
            active = bool(evt.get("active"))
            if not active and self.ctx.recording:
                self.ctx.recording = False
                self._set_state(LauncherState.TRANSCRIPTION)
        elif typ == "transcribing":
            if evt.get("active"):
                self._set_state(LauncherState.TRANSCRIPTION)
        elif typ == "transcript":
            self._on_transcript(evt)
        elif typ == "confirmation":
            self._set_state(LauncherState.CONFIRMATION)
        elif typ == "error":
            self._log_line(f"[erreur worker] {evt.get('message', '')}")

    def _on_transcript(self, evt: dict[str, Any]) -> None:
        cmd_obj = evt.get("command")
        if not isinstance(cmd_obj, dict):
            self._set_state(LauncherState.PRET)
            return
        text = str(cmd_obj.get("text", "")).strip()
        if not text:
            self._set_state(LauncherState.PRET)
            return
        self.ctx.last_phrase = text
        self._phrase_var.set(text)
        threading.Thread(
            target=self._run_command_pipeline,
            args=(text,),
            name="command-pipeline",
            daemon=True,
        ).start()

    def _effective_end_on_silence_ms(self) -> int | None:
        if not self.ctx.end_on_silence_supported:
            return None
        ms = int(self.args.end_on_silence_ms)
        if ms <= 0:
            return None
        return ms

    def on_hotkey_f8(self) -> None:
        if self._init_error or self._session is None:
            return
        if self.ctx.state == LauncherState.ERREUR:
            return
        if self.ctx.state not in (
            LauncherState.PRET,
            LauncherState.ECOUTE,
        ):
            return
        if not self.ctx.recording:
            payload: dict[str, Any] = {"cmd": "start"}
            end_ms = self._effective_end_on_silence_ms()
            if end_ms is not None:
                payload["end_on_silence_ms"] = end_ms
            try:
                self._session.send(payload)
            except OSError as exc:
                self._log_line(f"Envoi start impossible : {exc}")
                self._set_state(LauncherState.ERREUR)
                return
            self._session.recording = True
            self.ctx.recording = True
            self._set_state(LauncherState.ECOUTE)
            self._log_line("Enregistrement démarré.")
        else:
            try:
                self._session.send({"cmd": "stop"})
            except OSError as exc:
                self._log_line(f"Envoi stop impossible : {exc}")
                self._set_state(LauncherState.ERREUR)
                return
            self._session.recording = False
            self._log_line("Arrêt manuel de l'enregistrement.")

    def _run_command_pipeline(self, text: str) -> None:
        if not text.strip():
            self._set_state(LauncherState.PRET)
            return
        if self._session is None or self._speaker is None:
            return
        with self._command_lock:
            self._set_state(LauncherState.TRANSCRIPTION)

            def send_confirm(
                session: Any, timeout: float, end_ms: int | None
            ) -> str:
                self._set_state(LauncherState.CONFIRMATION)
                effective = end_ms
                if not self.ctx.end_on_silence_supported:
                    effective = None
                return vl._default_send_confirm(
                    session,
                    timeout,
                    end_on_silence_ms=effective,
                )

            def execute(action: dict[str, Any], dry_run: bool) -> None:
                summary = str(action.get("type", "?"))
                self.ctx.last_action = summary
                self._schedule_ui(
                    lambda: self._action_var.set(summary or "—")
                )
                lines: list[str] = []

                def capture_exec(a: dict[str, Any], dr: bool) -> None:
                    import io
                    from contextlib import redirect_stdout

                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        vl.execute_action(a, dry_run=dr)
                    lines.append(buf.getvalue().strip())

                capture_exec(action, dry_run)
                result = lines[-1] if lines else ""
                self.ctx.last_result = result
                self._schedule_ui(lambda: self._result_var.set(result))

            try:
                import io
                from contextlib import redirect_stdout

                buf = io.StringIO()
                with redirect_stdout(buf):
                    vl.handle_command(
                        self._session,
                        text,
                        self._entries,
                        dry_run=self.args.dry_run,
                        confirm_timeout=self.args.confirm_timeout,
                        end_on_silence_ms=self._effective_end_on_silence_ms(),
                        speaker=self._speaker,
                        send_confirm=send_confirm,
                        execute=execute,
                        verbose=self.args.verbose,
                    )
                extra = buf.getvalue().strip()
                if extra:
                    for line in extra.splitlines():
                        self._log_line(line)
            except Exception as exc:
                self._log_line(f"Erreur commande : {exc}")
                self._set_state(LauncherState.ERREUR)
                return
            self._set_state(LauncherState.PRET)

    def quit(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._hotkey.stop()
        if self._session is not None:
            try:
                self._session.shutdown()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> int:
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.quit()
        return 0


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = parse_gui_args(argv)
    app = VoiceLauncherGuiApp(args)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())