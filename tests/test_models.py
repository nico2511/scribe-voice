"""Résolution des modèles locaux, mode hors ligne et défauts v1.1."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import voice_worker as vw

ROOT = Path(__file__).resolve().parent.parent
FAKES = Path(__file__).resolve().parent / "fakes"


def _ct2_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "model.bin").write_bytes(b"ct2")
    return path


def test_defaults_small_and_fr():
    cfg = vw.sanitize_config(None)
    assert cfg["model_size"] == "small"
    assert cfg["language"] == "fr"
    assert cfg["offline"] is False
    assert cfg["models_dir"] is None
    assert cfg["app_id"] is None


def test_config_models_dir_overrides_env(monkeypatch, tmp_path):
    env_dir = tmp_path / "from_env"
    env_dir.mkdir()
    cfg_dir = tmp_path / "from_config"
    cfg_dir.mkdir()
    monkeypatch.setenv("SCRIBE_VOICE_MODELS_DIR", str(env_dir))
    cfg = vw.sanitize_config({"models_dir": str(cfg_dir)})
    assert cfg["models_dir"] == str(cfg_dir.resolve())


def test_env_models_dir_when_config_omitted(monkeypatch, tmp_path):
    env_dir = tmp_path / "env_models"
    env_dir.mkdir()
    monkeypatch.setenv("SCRIBE_VOICE_MODELS_DIR", str(env_dir))
    cfg = vw.sanitize_config({})
    assert cfg["models_dir"] == str(env_dir.resolve())


@pytest.mark.parametrize(
    "layout",
    [
        "flat_size",
        "flat_faster_whisper",
        "hf_cache",
        "direct_ct2",
    ],
)
def test_resolve_whisper_model_layouts(tmp_path, layout):
    root = tmp_path / "models_root"
    model_size = "small"
    if layout == "flat_size":
        root.mkdir()
        _ct2_dir(root / "small")
        cfg = vw.sanitize_config({"models_dir": str(root), "model_size": model_size})
    elif layout == "flat_faster_whisper":
        root.mkdir()
        _ct2_dir(root / "faster-whisper-small")
        cfg = vw.sanitize_config({"models_dir": str(root), "model_size": model_size})
    elif layout == "hf_cache":
        root.mkdir()
        snap = root / "models--Systran--faster-whisper-small" / "snapshots" / "abc123"
        _ct2_dir(snap)
        cfg = vw.sanitize_config({"models_dir": str(root), "model_size": model_size})
    else:
        direct = _ct2_dir(tmp_path / "my_ct2_model")
        cfg = vw.sanitize_config({"models_dir": str(direct), "model_size": model_size})

    model_arg, download_root, err = vw.resolve_whisper_model(cfg)
    assert err is None
    assert download_root is None
    assert model_arg is not None
    assert vw.is_ct2_model_dir(model_arg)


def test_resolve_missing_models_dir_errors(tmp_path):
    missing = tmp_path / "nope"
    cfg = vw.sanitize_config({"models_dir": str(missing), "offline": True})
    model_arg, download_root, err = vw.resolve_whisper_model(cfg)
    assert model_arg is None
    assert download_root is None
    assert err and "introuvable" in err


def test_resolve_offline_without_models_dir():
    cfg = vw.sanitize_config({"offline": True})
    model_arg, download_root, err = vw.resolve_whisper_model(cfg)
    assert model_arg is None
    assert err and "hors ligne" in err.lower()


def test_resolve_offline_model_absent(tmp_path):
    root = tmp_path / "empty_root"
    root.mkdir()
    cfg = vw.sanitize_config({"models_dir": str(root), "offline": True, "model_size": "small"})
    model_arg, _, err = vw.resolve_whisper_model(cfg)
    assert model_arg is None
    assert err and "introuvable" in err


def test_offline_passes_local_files_only(worker_factory, tmp_path):
    models = tmp_path / "models"
    _ct2_dir(models / "small")
    loads = tmp_path / "loads.jsonl"
    whisper_cfg = json.dumps({"loads_file": str(loads)})
    w = worker_factory(
        SCRIBE_VOICE_MODELS_DIR=str(models),
        FAKE_WHISPER=whisper_cfg,
    )
    w.wait_type("ready")
    w.send({
        "cmd": "init",
        "config": {
            "device": "cpu",
            "offline": True,
            "models_dir": str(models),
            "model_size": "small",
        },
    })
    w.wait_type("model", loaded=True, timeout=30)
    w.send({"cmd": "shutdown"})
    w.close()
    lines = loads.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    payload = json.loads(lines[-1])
    assert payload["local_files_only"] is True
    assert Path(payload["model"]).name.endswith("small") or "small" in payload["model"]


def test_offline_missing_model_emits_error(worker_factory, tmp_path):
    root = tmp_path / "vide"
    root.mkdir()
    w = worker_factory(FAKE_WHISPER="{}")
    w.wait_type("ready")
    w.send({
        "cmd": "init",
        "config": {"device": "cpu", "offline": True, "models_dir": str(root)},
    })
    err = w.wait_type("error", timeout=30)
    assert "introuvable" in err["message"].lower() or "Chargement modèle" in err["message"]
    w.wait_type("model", loaded=False, timeout=30)
    w.send({"cmd": "shutdown"})
    w.close()


def test_import_creates_no_directories(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONPATH"] = os.pathsep.join([str(FAKES), str(ROOT)])
    code = (
        "import importlib.util, sys; "
        f"spec = importlib.util.spec_from_file_location('vw', r'{ROOT / 'voice_worker.py'}'); "
        "mod = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(mod)"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        check=True,
        cwd=str(ROOT),
    )
    assert not (home / "Documents" / "CyberScribeNote").exists()


def test_ready_includes_version_and_protocol(worker_factory):
    w = worker_factory()
    w.wait_type("deps")
    ready = w.wait_type("ready")
    assert ready.get("version") == vw.WORKER_VERSION
    assert ready.get("protocol") == vw.PROTOCOL_VERSION
    w.send({"cmd": "shutdown"})
    w.close()
