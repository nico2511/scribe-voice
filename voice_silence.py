"""Détection de fin de parole (silence continu après au moins un signal vocal)."""
from __future__ import annotations

import array
from typing import Any

RMS_SPEECH_THRESHOLD = 60.0
DEFAULT_SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2

_silero_cached: bool | None = None


def silero_vad_available() -> bool:
    global _silero_cached
    if _silero_cached is not None:
        return _silero_cached
    try:
        from faster_whisper.vad import get_speech_timestamps  # noqa: F401

        _silero_cached = True
    except Exception:
        _silero_cached = False
    return _silero_cached


def pcm16_rms(pcm: bytes) -> float:
    if len(pcm) < BYTES_PER_SAMPLE:
        return 0.0
    samples = array.array("h")
    try:
        samples.frombytes(pcm)
    except Exception:
        return 0.0
    if not samples:
        return 0.0
    acc = 0.0
    for sample in samples:
        acc += sample * sample
    return (acc / len(samples)) ** 0.5


def chunk_has_speech(
    pcm: bytes,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    use_silero: bool | None = None,
) -> bool:
    rms = pcm16_rms(pcm)
    if rms < RMS_SPEECH_THRESHOLD:
        return False
    if use_silero is None:
        use_silero = silero_vad_available()
    if not use_silero:
        return True
    try:
        import numpy as np
        from faster_whisper.vad import get_speech_timestamps

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        return bool(get_speech_timestamps(audio, sampling_rate=sample_rate))
    except Exception:
        return True


def parse_end_on_silence_ms(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        ms = int(raw)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return max(100, min(ms, 60_000))


class EndOnSilenceTracker:
    """Accumule des trames PCM et signale un arrêt après silence prolongé."""

    def __init__(
        self,
        end_on_silence_ms: int,
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        chunk_samples: int = 1024,
        use_silero: bool | None = None,
    ) -> None:
        self.end_on_silence_ms = end_on_silence_ms
        self.sample_rate = sample_rate
        self._chunk_ms = (chunk_samples / float(sample_rate)) * 1000.0
        self._use_silero = use_silero
        self._speech_seen = False
        self._trailing_silence_ms = 0.0

    def reset(self) -> None:
        self._speech_seen = False
        self._trailing_silence_ms = 0.0

    def feed(self, pcm: bytes) -> bool:
        if chunk_has_speech(pcm, sample_rate=self.sample_rate, use_silero=self._use_silero):
            self._speech_seen = True
            self._trailing_silence_ms = 0.0
            return False
        if not self._speech_seen:
            return False
        self._trailing_silence_ms += self._chunk_ms
        return self._trailing_silence_ms >= float(self.end_on_silence_ms)