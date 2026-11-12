# Build autonome de scribe-voice : voice_worker.exe + zip + SHA256SUMS.
# Usage (PowerShell, à la racine du dépôt) :
#   .\build.ps1 -Version v1.0.0
#
# Requiert : CPython 3.11 x64 (l'exe de référence a été produit avec 3.11.9).
# Le build reprend tel quel voice_worker.spec (identique à CyberScribeNote).
# build_sidecar.ps1 reste le script historique propre à CyberScribeNote (Tauri).

param(
  [string]$Version = "dev"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python --version
python -m pip install --disable-pip-version-check -r requirements-build.txt
python -m PyInstaller --noconfirm --clean voice_worker.spec

$Exe = Join-Path $PSScriptRoot "dist\voice_worker.exe"
if (-not (Test-Path $Exe)) { throw "Build échoué : $Exe absent" }

# PyAV / FFmpeg GPL (x264, x265) ne doivent pas être embarqués (v1.1+).
$ForbiddenPatterns = @('av\.libs', 'x264', 'x265', 'avcodec')
$ScanRoots = @(
  (Join-Path $PSScriptRoot "dist"),
  (Join-Path $PSScriptRoot "build")
)
$Hits = @()
foreach ($root in $ScanRoots) {
  if (-not (Test-Path $root)) { continue }
  foreach ($item in Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue) {
    $rel = $item.FullName.Substring($PSScriptRoot.Length + 1)
    foreach ($pat in $ForbiddenPatterns) {
      if ($item.Name -match $pat -or $rel -match $pat) {
        $Hits += $rel
        break
      }
    }
  }
  foreach ($toc in Get-ChildItem -Path $root -Recurse -Filter "*.toc" -ErrorAction SilentlyContinue) {
    $text = Get-Content -Raw -LiteralPath $toc.FullName
    foreach ($pat in $ForbiddenPatterns) {
      if ($text -match $pat) {
        $Hits += "$($toc.FullName.Substring($PSScriptRoot.Length + 1)) (contenu TOC)"
        break
      }
    }
  }
}
if ($Hits.Count -gt 0) {
  $Hits | ForEach-Object { Write-Error "Artefact GPL / PyAV interdit : $_" }
  throw "Build rejeté : PyAV / x264 / x265 / avcodec détectés dans dist ou build."
}

$Out = Join-Path $PSScriptRoot "release"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Copy-Item $Exe (Join-Path $Out "voice_worker.exe") -Force

$Stage = Join-Path $PSScriptRoot "build\zip-stage"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
Copy-Item $Exe, "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md" $Stage
$ZipName = "scribe-voice-$Version-win-x64.zip"
$Zip = Join-Path $Out $ZipName
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip

# SHA256SUMS au format sha256sum (minuscules, deux espaces, LF).
$Lines = foreach ($f in @("voice_worker.exe", $ZipName)) {
  $h = (Get-FileHash -Algorithm SHA256 (Join-Path $Out $f)).Hash.ToLowerInvariant()
  "$h  $f"
}
[IO.File]::WriteAllText((Join-Path $Out "SHA256SUMS"), (($Lines -join "`n") + "`n"))

Get-Content (Join-Path $Out "SHA256SUMS")
Write-Host "OK -> $Out"
