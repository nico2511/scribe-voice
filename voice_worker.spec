# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — scribe-voice worker
# Build:  pyinstaller voice_worker.spec  (à la racine du dépôt ou via build.ps1)
# Output: dist/voice_worker.exe

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# faster_whisper VAD (silero_vad_v6.onnx) — requis pour vad_filter=True
_fw_datas = collect_data_files("faster_whisper")

a = Analysis(
    ['voice_worker.py'],
    pathex=[],
    binaries=[],
    datas=_fw_datas,
    hiddenimports=[
        'faster_whisper',
        'ctranslate2',
        'pyaudio',
        'tokenizers',
        'huggingface_hub',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'tkinter', 'PyQt5', 'PySide2', 'av'],
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
    name='voice_worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # sous-système console : stdin/stdout pipés fiables pour le processus parent
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
