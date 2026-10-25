#!/usr/bin/env python3
"""Banc manuel : bruit synthétique -> Transcriber (modèle base réel).

Usage : python tools/bench_hallucination.py [--trials 60]
Non exécuté par pytest.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import struct
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import voice_worker as vw  # noqa: E402


def _noise_wav(seconds: float, amplitude: float) -> str:
    rate = 16000
    n = max(1, int(round(seconds * rate)))
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="bench_noise_")
    os.close(fd)
    frames = struct.pack(
        "<%dh" % n,
        *(
            int(amplitude * 32767 * (random.random() * 2 - 1))
            for _ in range(n)
        ),
    )
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=60)
    args = parser.parse_args()

    t = vw.Transcriber(vw.sanitize_config({"model_size": "base", "device": "cpu"}))
    if not t.loaded_event.wait(timeout=300):
        print("timeout chargement modèle")
        return 1
    if not t.model:
        print("modèle non chargé")
        return 1

    nonempty = 0
    for i in range(args.trials):
        seconds = random.uniform(0.4, 3.0)
        amplitude = random.uniform(0.005, 0.04)
        path = _noise_wav(seconds, amplitude)
        try:
            text = t.transcribe(path) or ""
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if text.strip():
            nonempty += 1
            print(f"#{i + 1}: dur={seconds:.2f}s amp={amplitude:.4f} -> {text!r}")

    print(f"Résultat : {nonempty}/{args.trials} transcriptions non vides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
