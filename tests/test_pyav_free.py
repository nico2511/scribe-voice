"""PyAV absent du chemin d'exécution : stub d'import et transcription ndarray."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import voice_worker as vw

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "voice_worker.py"


def test_pyav_stub_installed():
    av = sys.modules.get("av")
    assert av is not None
    assert getattr(av, vw._PYAV_STUB_ATTR, False) is True


def test_faster_whisper_imports_with_av_blocked():
    """Import réel de faster-whisper alors que tout import ``av`` lève ImportError."""
    import importlib

    class _BlockPyAV:
        def find_module(self, fullname, path=None):
            if fullname == "av" or fullname.startswith("av."):
                if fullname not in sys.modules:
                    return self
            return None

        def load_module(self, fullname):
            raise ImportError("PyAV simulé absent")

    saved_meta = list(sys.meta_path)
    saved_modules = {
        k: sys.modules[k]
        for k in list(sys.modules)
        if k == "av" or k.startswith("av.") or k == "faster_whisper" or k.startswith("faster_whisper.")
    }
    try:
        for key in saved_modules:
            sys.modules.pop(key, None)
        sys.meta_path.insert(0, _BlockPyAV())
        vw._install_pyav_import_stub()
        mod = importlib.import_module("faster_whisper")
        assert mod.WhisperModel is not None
    finally:
        sys.meta_path[:] = saved_meta
        for key in list(sys.modules):
            if key == "av" or key.startswith("av.") or key == "faster_whisper" or key.startswith("faster_whisper."):
                if key not in saved_modules:
                    sys.modules.pop(key, None)
        for key, val in saved_modules.items():
            sys.modules[key] = val


def test_worker_subprocess_deps_ok_without_real_pyav(tmp_path):
    """Le worker démarre (deps ok) avec faster_whisper réel et PyAV bloqué."""
    fakes = ROOT / "tests" / "fakes"
    script = (
        "import sys\n"
        "class _BlockPyAV:\n"
        "    def find_module(self, fullname, path=None):\n"
        "        if fullname == 'av' or fullname.startswith('av.'):\n"
        "            if fullname not in sys.modules:\n"
        "                return self\n"
        "        return None\n"
        "    def load_module(self, fullname):\n"
        "        raise ImportError('PyAV simulé absent')\n"
        f"sys.meta_path.insert(0, _BlockPyAV())\n"
        f"sys.path.insert(0, r'{fakes}')\n"
        f"sys.path.insert(0, r'{ROOT}')\n"
        "import voice_worker as vw\n"
        "ok, err = vw.check_deps()\n"
        "assert ok, err\n"
        "print('deps_ok')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr or out.stdout
    assert "deps_ok" in out.stdout


def test_load_wav_mono_float32_matches_ndarray(tmp_path):
    from tests.test_transcriber import make_wav

    path = make_wav(tmp_path, 0.5)
    audio = vw._load_wav_mono_float32(path)
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) == 8000

