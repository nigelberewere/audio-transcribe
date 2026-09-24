# Zingsa Files Center

A self-hosted Windows Server transcription queue for confidential meeting recordings. Audio is converted locally with ffmpeg and transcribed with faster-whisper/CTranslate2 on CPU using `int8`. No cloud API is used during operation.

## Architecture

FastAPI serves the browser UI and authenticated JSON API. SQLite stores job state. A single FIFO worker processes one job at a time. The model is selected when processing starts: `large-v3` is the default; `medium` is selected when the configured number of jobs are still waiting. An explicit upload override wins. Segment checkpoints are written under each job directory after every Whisper segment.

`config.json` controls `default_model`, `fallback_model`, `queue_threshold`, and `auto_delete_days` (zero means disabled). Environment variables with the `TRANSCRIBE_` prefix override these values. Source recordings and generated outputs live under `TRANSCRIBE_DATA_DIR`.

## Windows Server setup

1. Install Python 3.11 or newer and ffmpeg. For example, with winget: `winget install Gyan.FFmpeg`.
2. Download NSSM, place `nssm.exe` in this project directory, and open PowerShell as Administrator.
3. Set an initial password and run the installer:

```powershell
$env:TRANSCRIBE_ADMIN_PASSWORD = 'use-a-long-random-password'
.\install-service.ps1 -DataDir 'D:\LegalTranscription' -FfmpegPath 'C:\ffmpeg\bin\ffmpeg.exe'
```

The installer creates `.venv`, installs requirements, pre-caches `large-v3` and `medium` from Hugging Face, registers an automatic-restart NSSM service, and opens the port only for Domain and Private firewall profiles. Model caching requires setup-time internet access. After caching, inference is local and can run offline.

Change the generated service environment or config before production. Replace the default session secret with a private value using `TRANSCRIBE_SESSION_SECRET`. Confirm that the chosen data volume has enough space for uploads, normalized WAV files, checkpoints, and outputs.

The service starts at boot without a logged-in user. Check `Get-Service OfflineLegalTranscription`, `storage\logs\transcribe.log`, and the NSSM stdout/stderr files when diagnosing startup.

## Use

Browse to `http://server-name:8420/` from the internal network, sign in, drag a supported file into the upload area, choose output formats, and submit. The UI shows queue position, progress, ETA, requested model, selected model, and downloads. The preview endpoint exposes checkpoint segments; the edit endpoint stores a corrected plain-text version before external use.

Supported input: mp3, wav, m4a, mp4, mkv, ogg, flac, webm. Outputs: txt, timestamped txt, srt, vtt, docx, and json.

CLI example:

```powershell
.\.venv\Scripts\python.exe transcribe.py .\meeting.mp3 --model auto --format docx,srt
```

The CLI uses the same SQLite queue policy but processes its submitted job synchronously.

## Diarization and cleanup

The default path intentionally works without diarization. The dependency comment in `requirements.txt` identifies the optional `pyannote.audio` package. Enabling a production diarization adapter requires downloading its local model during setup and satisfying any model terms/access requirements; no remote inference is used. The current toggle is retained in job metadata so this can be added without changing the queue contract.

Automatic source deletion is disabled by default. Before enabling `auto_delete_days`, confirm the retention policy with Legal. A production cleanup task should delete only source audio after the configured age and retain transcripts according to policy.

## Reverse proxy later

Keep this service bound to the internal interface/firewall. For nginx, proxy a private upstream such as `http://127.0.0.1:8420`, forward `Host`, `X-Forwarded-For`, and `X-Forwarded-Proto`, and enable HTTPS at nginx. For IIS, install URL Rewrite plus ARR, create a reverse-proxy rule to `http://127.0.0.1:8420`, bind an HTTPS certificate, and restrict the site binding/firewall. Preserve the application authentication layer even behind a proxy.

## Tests

Run `py -m pytest -q`. The included tests cover adaptive model selection. Keep adding unit coverage for segment merging/checkpoint resume as the transcription adapter evolves. A full end-to-end run requires ffmpeg, the Python dependencies, cached models, and a short local sample recording.
