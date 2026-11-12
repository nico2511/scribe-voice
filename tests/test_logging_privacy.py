"""Journal : pas de texte transcrit par défaut (vie privée)."""
from __future__ import annotations

import wave
from pathlib import Path

import pytest

import voice_worker as vw


@pytest.fixture
def log_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("SCRIBE_VOICE_LOG_TRANSCRIPTS", raising=False)
    monkeypatch.setattr(
        vw,
        "DEFAULT_LOG_ROOT",
        str(home / "Documents" / "CyberScribeNote"),
    )
    vw._logging_ready = False
    vw._fault_fp = None
    return home


def _log_file(home: Path) -> Path:
    return home / "Documents" / "CyberScribeNote" / "voice_worker.log"


def _loud_wav(path: Path, seconds: float = 1.0) -> None:
    n = int(16000 * seconds)
    samples = b"".join((int(5000).to_bytes(2, "little", signed=True) for _ in range(n)))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(samples)


def test_transcript_text_not_in_log_by_default(monkeypatch, log_home, tmp_path):
    """Le fichier journal ne contient pas le texte reconnu sans opt-in explicite."""
    monkeypatch.setenv(
        "FAKE_WHISPER",
        '{"texts": ["texte secret invisible dans le log."]}',
    )
    monkeypatch.setenv("FAKE_VAD", '{"has_speech": true}')
    vw._ensure_logging(None)
    cfg = vw.sanitize_config({"model_size": "small", "device": "cpu"})
    t = vw.Transcriber(cfg)
    assert t.loaded_event.wait(timeout=15)
    wav = tmp_path / "t.wav"
    _loud_wav(wav)
    result = t.transcribe(str(wav))
    assert result == "texte secret invisible dans le log."
    log_file = _log_file(log_home)
    assert log_file.is_file()
    content = log_file.read_text(encoding="utf-8")
    assert "texte secret invisible" not in content
    assert "Transcription done (" in content


def test_transcript_text_in_log_when_enabled(monkeypatch, log_home, tmp_path):
    monkeypatch.setenv("SCRIBE_VOICE_LOG_TRANSCRIPTS", "1")
    monkeypatch.setenv(
        "FAKE_WHISPER",
        '{"texts": ["visible quand opt-in."]}',
    )
    monkeypatch.setenv("FAKE_VAD", '{"has_speech": true}')
    vw._ensure_logging(None)
    cfg = vw.sanitize_config(
        {"model_size": "small", "device": "cpu", "log_transcripts": True}
    )
    t = vw.Transcriber(cfg)
    assert t.loaded_event.wait(timeout=15)
    wav = tmp_path / "t.wav"
    _loud_wav(wav)
    result = t.transcribe(str(wav))
    assert result == "visible quand opt-in."
    content = _log_file(log_home).read_text(encoding="utf-8")
    assert "visible quand opt-in" in content
