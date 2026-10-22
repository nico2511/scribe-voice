# Composants tiers

`voice_worker.exe` (PyInstaller, onefile) embarque l'interpréteur Python et les paquets
ci-dessous. Le code de scribe-voice est sous licence MIT (voir `LICENSE`) ; chaque
composant reste soumis à sa propre licence. Versions = `requirements.txt` / `requirements-build.txt`.
Les textes de licence complets sont disponibles dans les dépôts / distributions de chaque projet.

| Composant | Version | Licence | Projet |
|---|---|---|---|
| CPython (interpréteur, bibliothèque standard) | 3.11.9 | PSF-2.0 | https://www.python.org/ |
| faster-whisper | 1.2.1 | MIT | https://github.com/SYSTRAN/faster-whisper |
| Silero VAD (`silero_vad_v6.onnx`, fourni par faster-whisper) | v6 | MIT | https://github.com/snakers4/silero-vad |
| CTranslate2 | 4.8.2 | MIT | https://github.com/OpenNMT/CTranslate2 |
| Intel OpenMP runtime (`libiomp5md.dll`, fourni avec CTranslate2) | — | Intel Simplified Software License | https://www.intel.com/ |
| ONNX Runtime | 1.30.0 | MIT | https://github.com/microsoft/onnxruntime |
| PyAV (`av`) | 18.1.0 | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| FFmpeg et codecs embarqués par la roue PyAV (`av.libs/` : avcodec, avformat, avutil, swresample, swscale, dav1d, libvpx, opus, lame, x264, x265, SVT-AV1, webp, opencore-amr…) | build PyAV 18.1.0 | LGPL-2.1+ pour FFmpeg ; **GPL-2.0+ pour libx264 / libx265** ; BSD/ISC/Apache/LGPL pour les autres — à vérifier, voir ci-dessous | https://ffmpeg.org/ |
| tokenizers | 0.23.2 | Apache-2.0 | https://github.com/huggingface/tokenizers |
| huggingface_hub | 1.33.0 | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| hf-xet | 1.6.0 | Apache-2.0 | https://github.com/huggingface/xet-core |
| NumPy (+ OpenBLAS `scipy_openblas64`) | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org/ |
| PyAudio | 0.2.14 | MIT | https://people.csail.mit.edu/hubert/pyaudio/ |
| PortAudio (dans PyAudio) | — | MIT (licence PortAudio) | https://www.portaudio.com/ |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | https://github.com/tqdm/tqdm |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org/ |
| httpx | 0.28.1 | BSD-3-Clause | https://www.python-httpx.org/ |
| httpcore | 1.0.9 | BSD-3-Clause | https://github.com/encode/httpcore |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| anyio | 4.15.1 | MIT | https://github.com/agronholm/anyio |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| click | 8.5.0 | BSD-3-Clause | https://palletsprojects.com/p/click/ |
| colorama | 0.4.6 | BSD-3-Clause | https://github.com/tartley/colorama |
| filelock | 4.0.6 | MIT | https://github.com/tox-dev/filelock |
| fsspec | 2026.9.0 | BSD-3-Clause | https://github.com/fsspec/filesystem_spec |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| protobuf / flatbuffers (dépendances pip d'onnxruntime, non embarquées dans l'exe de référence) | 7.36.2 / 25.12.19 | BSD-3-Clause / Apache-2.0 | https://protobuf.dev/ · https://flatbuffers.dev/ |
| PyInstaller (bootloader embarqué dans l'exe) | 6.22.3 | GPL-2.0-or-later **avec exception bootloader** (autorise la distribution d'exécutables sous toute licence) | https://pyinstaller.org/ |
| Microsoft Visual C++ Runtime (`vcruntime140*.dll`, `msvcp140*.dll`, `ucrtbase.dll`, `api-ms-win-*.dll`) | — | Microsoft Visual C++ Redistributable | https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist |

## Non embarqué

- **Modèles Whisper** (CTranslate2, ex. `Systran/faster-whisper-base`) : téléchargés à l'exécution depuis
  Hugging Face dans `~/Documents/CyberScribeNote/models`. Poids Whisper d'OpenAI sous licence MIT.

## Point à vérifier (FFmpeg / GPL)

L'exe de référence contient, via la roue binaire PyAV, `libx264` et `libx265` (licence GPL).
Le worker n'utilise que le décodage audio, mais la redistribution d'un binaire incluant ces
bibliothèques peut entraîner des obligations GPL (mise à disposition des sources correspondantes).
Ce point est hors périmètre de la v1.0 (aucun changement de dépendances) et devra être tranché
(par ex. roue PyAV LGPL-only ou exclusion de ces DLL dans la spec) dans une version ultérieure.
