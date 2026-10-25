"""Smoke test de l'exe construit : deps -> ready, ping -> pong, shutdown.

Usage : python tools/smoke_exe.py dist/voice_worker.exe
Ne touche ni au micro ni au modèle (aucune commande init/toggle/preload).
"""
import json
import subprocess
import sys


def main() -> int:
    exe = sys.argv[1]
    proc = subprocess.run(
        [exe],
        input=b'{"cmd": "ping"}\n{"cmd": "shutdown"}\n',
        capture_output=True,
        timeout=180,
    )
    events = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
    print("exit:", proc.returncode)
    for e in events:
        print(e)
    ok = (
        proc.returncode == 0
        and events[:2] == [{"type": "deps", "ok": True}, {"type": "ready"}]
        and {"type": "pong"} in events
    )
    if not ok:
        print("SMOKE TEST ÉCHOUÉ", file=sys.stderr)
        print(proc.stderr.decode("utf-8", "replace"), file=sys.stderr)
        return 1
    print("SMOKE TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
