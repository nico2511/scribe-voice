"""Faux module ``pyaudio`` pour les tests : aucun micro requis.

Pilotage par variables d'environnement :
  FAKE_PYAUDIO_IMPORT_ERROR=1  -> l'import échoue (simule dépendance absente)
  FAKE_PYAUDIO_FAIL_OPEN=1     -> PyAudio.open() lève OSError (micro absent)
  FAKE_PYAUDIO_AMPLITUDE=n     -> amplitude du signal int16 (défaut 3000)
"""
import math
import os
import struct
import time

if os.environ.get("FAKE_PYAUDIO_IMPORT_ERROR") == "1":
    raise ImportError("No module named 'pyaudio' (simulé)")

paInt16 = 8


class _Stream:
    def __init__(self, rate, amplitude):
        self._rate = rate
        self._amp = amplitude
        self._t = 0

    def read(self, n, exception_on_overflow=True):
        # Rythme temps réel pour que la durée du WAV suive la durée d'enregistrement.
        time.sleep(n / float(self._rate))
        out = []
        for _ in range(n):
            out.append(int(self._amp * math.sin(2 * math.pi * 440 * self._t / self._rate)))
            self._t += 1
        return struct.pack("<%dh" % n, *out)

    def stop_stream(self):
        pass

    def close(self):
        pass


class PyAudio:
    def open(self, format=None, channels=1, rate=16000, input=True, frames_per_buffer=1024):
        if os.environ.get("FAKE_PYAUDIO_FAIL_OPEN") == "1":
            raise OSError("[Errno -9996] Invalid input device (simulé)")
        return _Stream(rate, int(os.environ.get("FAKE_PYAUDIO_AMPLITUDE", "3000")))

    def get_sample_size(self, fmt):
        return 2

    def terminate(self):
        pass
