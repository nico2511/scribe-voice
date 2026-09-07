# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — CyberScribeNote voice worker sidecar
# Build:  cd voice && pyinstaller voice_worker.spec
# Output: voice/dist/voice_worker.exe  (copied next to cyberscribe-note.exe / resources)

block_cipher = None

a = Analysis(
    ['voice_worker.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'faster_whisper',
        'ctranslate2',
        'pyaudio',
        'av',
        'tokenizers',
        'huggingface_hub',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'tkinter', 'PyQt5', 'PySide2'],
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
    console=False,  # fenêtre cachée — Tauri parle via stdin/stdout pipés
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
