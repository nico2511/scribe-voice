# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — lanceur graphique scribe-voice (demo)
# NE PAS embarquer voice_worker : le moteur reste voice_worker.exe a cote du lanceur.
# Build (depuis la racine du depot, sans lancer ici) :
#   pyinstaller examples/voice_launcher_gui.spec
# Sortie : dist/voice_launcher_gui.exe

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

_kokoro_datas = collect_data_files("kokoro", include_py_files=False)
_espeak_datas = collect_data_files("espeakng_loader", include_py_files=False)
datas = _kokoro_datas + _espeak_datas

hiddenimports = [
    "kokoro",
    "sounddevice",
    "soundfile",
    "espeakng_loader",
    "numpy",
    "huggingface_hub",
    "torch",
] + collect_submodules("kokoro")

a = Analysis(
    ["examples/voice_launcher_gui.py"],
    pathex=["examples"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "voice_worker",
        "faster_whisper",
        "ctranslate2",
        "pyaudio",
        "matplotlib",
        "PyQt5",
        "PySide2",
        "av",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="voice_launcher_gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)