param(
  [string]$InstallDir = $PSScriptRoot,
  [string]$DataDir = "$PSScriptRoot\storage",
  [string]$FfmpegPath = "ffmpeg.exe",
  [string]$NssmPath = "$PSScriptRoot\nssm.exe",
  [int]$Port = 8420
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python 3.11+ is required.' }
if (-not (Test-Path $NssmPath)) { throw "NSSM not found at $NssmPath. Download nssm.exe and place it there." }
if (-not (Test-Path "$InstallDir\.venv\Scripts\python.exe")) { python -m venv "$InstallDir\.venv" }
& "$InstallDir\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$InstallDir\.venv\Scripts\python.exe" -m pip install -r "$InstallDir\requirements.txt"
if (-not (Get-Command $FfmpegPath -ErrorAction SilentlyContinue) -and -not (Test-Path $FfmpegPath)) { throw "ffmpeg was not found. Install it or pass -FfmpegPath." }
$env:TRANSCRIBE_FFMPEG = $FfmpegPath
& "$InstallDir\.venv\Scripts\python.exe" "$InstallDir\preload_models.py"
& $NssmPath install OfflineLegalTranscription "$InstallDir\.venv\Scripts\python.exe" "-m uvicorn app.main:app --host 0.0.0.0 --port $Port"
& $NssmPath set OfflineLegalTranscription AppDirectory $InstallDir
& $NssmPath set OfflineLegalTranscription AppStdout "$DataDir\logs\service.stdout.log"
& $NssmPath set OfflineLegalTranscription AppStderr "$DataDir\logs\service.stderr.log"
& $NssmPath set OfflineLegalTranscription AppRotateFiles 1
& $NssmPath set OfflineLegalTranscription AppExit Default Restart
& $NssmPath set OfflineLegalTranscription Start SERVICE_AUTO_START
& $NssmPath set OfflineLegalTranscription AppEnvironmentExtra "TRANSCRIBE_DATA_DIR=$DataDir" "TRANSCRIBE_FFMPEG=$FfmpegPath"
New-NetFirewallRule -DisplayName 'Offline Legal Transcription (Internal)' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Domain,Private -ErrorAction SilentlyContinue | Out-Null
Start-Service OfflineLegalTranscription
Get-Service OfflineLegalTranscription
Write-Host "Service installed. Open http://server-name:$Port/ from the internal network."
