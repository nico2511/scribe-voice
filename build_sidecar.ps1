# Build the voice_worker.exe sidecar (PyInstaller) and stage it for Tauri.
# Usage (PowerShell, from repo root):
#   .\voice\build_sidecar.ps1
#
# Requires: Python 3.10+, pip install pyinstaller + voice/requirements.txt

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $PSScriptRoot "voice_worker.py"))) {
  $Root = (Get-Location).Path
  $VoiceDir = Join-Path $Root "voice"
} else {
  $VoiceDir = $PSScriptRoot
  $Root = Split-Path -Parent $VoiceDir
}

Write-Host "Voice dir: $VoiceDir"
Set-Location $VoiceDir

python -m pip install -q -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm voice_worker.spec

$Dist = Join-Path $VoiceDir "dist\voice_worker.exe"
if (-not (Test-Path $Dist)) {
  throw "Build failed: $Dist missing"
}

$BinDir = Join-Path $Root "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

# Tauri externalBin naming: <name>-<target-triple>
$Target = "x86_64-pc-windows-msvc"
$Dest = Join-Path $BinDir "voice-worker-$Target.exe"
Copy-Item $Dist $Dest -Force
# Also keep a plain name next to resources for fallback discovery
Copy-Item $Dist (Join-Path $VoiceDir "voice_worker.exe") -Force

Write-Host "OK → $Dest"
Write-Host "OK → $(Join-Path $VoiceDir 'voice_worker.exe')"
Write-Host "Next: npm run tauri build  (sidecar embarqué si présent dans binaries/)"
