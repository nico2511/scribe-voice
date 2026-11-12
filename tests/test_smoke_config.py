"""Configuration du smoke test (SCRIBE_SMOKE_MODEL)."""
from __future__ import annotations

import os

from tools import smoke_exe


def test_smoke_model_default_small(monkeypatch):
    monkeypatch.delenv("SCRIBE_SMOKE_MODEL", raising=False)
    assert smoke_exe.smoke_model_size() == "small"


def test_smoke_model_from_env(monkeypatch):
    monkeypatch.setenv("SCRIBE_SMOKE_MODEL", "base")
    assert smoke_exe.smoke_model_size() == "base"
