param(
  [string]$InstallDir = $PSScriptRoot,
  [string]$DataDir = "$PSScriptRoot\storage",
  [string]$FfmpegPath = "",
  [string]$NssmPath = "$PSScriptRoot\nssm.exe",
  [int]$Port = 8420,
  [string]$AdminUser = $env:TRANSCRIBE_ADMIN_USER,
  [string]$AdminPassword = $env:TRANSCRIBE_ADMIN_PASSWORD
)
$ErrorActionPreference = 'Stop'

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Zingsa Files Center - Windows Service Installation" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan

# Check Python
$pyCmd = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
if (-not $pyCmd -and -not (Test-Path "$InstallDir\.venv\Scripts\python.exe")) {
    throw 'Python 3.11+ is required. Install Python or run setup.bat first.'
}

# Check NSSM
if (-not (Test-Path $NssmPath)) {
    throw "NSSM not found at $NssmPath. Please place nssm.exe in this project directory."
}

# Auto-detect FFmpeg if not explicitly given
if (-not $FfmpegPath -or (-not (Test-Path $FfmpegPath) -and -not (Get-Command $FfmpegPath -ErrorAction SilentlyContinue))) {
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
        $FfmpegPath = (Get-Command ffmpeg).Source
    } else {
        $candidatePaths = @(
            "C:\ffmpeg\bin\ffmpeg.exe",
            "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg-*\bin\ffmpeg.exe",
            "C:\ProgramData\chocolatey\bin\ffmpeg.exe",
            "$PSScriptRoot\ffmpeg.exe"
        )
        foreach ($p in $candidatePaths) {
            $resolved = Resolve-Path $p -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path -First 1
            if ($resolved -and (Test-Path $resolved)) {
                $FfmpegPath = $resolved
                break
            }
        }
    }
}

if (-not $FfmpegPath) {
    $FfmpegPath = "ffmpeg"
}

# Prompt for Admin Credentials if not set
if (-not $AdminUser) {
    $AdminUser = "admin"
}

if (-not $AdminPassword) {
    Write-Host "`nAdmin password not pre-configured." -ForegroundColor Yellow
    $AdminPassword = Read-Host "Enter an Admin password for the web portal"
    if ([string]::IsNullOrWhiteSpace($AdminPassword)) {
        throw 'Admin password cannot be empty.'
    }
}

# Ensure directories
New-Item -ItemType Directory -Force "$DataDir\logs" | Out-Null
New-Item -ItemType Directory -Force "$DataDir\uploads" | Out-Null
New-Item -ItemType Directory -Force "$DataDir\jobs" | Out-Null

# Virtual environment setup
if (-not (Test-Path "$InstallDir\.venv\Scripts\python.exe")) {
    Write-Host "Creating Python virtual environment..."
    & $pyCmd -m venv "$InstallDir\.venv"
}

Write-Host "Installing Python dependencies..."
& "$InstallDir\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& "$InstallDir\.venv\Scripts\python.exe" -m pip install -r "$InstallDir\requirements.txt"

# Pre-cache models
$env:TRANSCRIBE_FFMPEG = $FfmpegPath
Write-Host "Caching Whisper models for offline transcription..."
& "$InstallDir\.venv\Scripts\python.exe" "$InstallDir\preload_models.py"

# Stop existing service if running
$existingService = Get-Service ZingsaFilesCenter -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "Stopping existing ZingsaFilesCenter service..."
    Stop-Service ZingsaFilesCenter -Force -ErrorAction SilentlyContinue
    & $NssmPath remove ZingsaFilesCenter confirm
}

# Install service with NSSM
Write-Host "Registering Windows Service..."
& $NssmPath install ZingsaFilesCenter "$InstallDir\.venv\Scripts\python.exe" "-m uvicorn app.main:app --host 0.0.0.0 --port $Port"
& $NssmPath set ZingsaFilesCenter AppDirectory $InstallDir
& $NssmPath set ZingsaFilesCenter AppStdout "$DataDir\logs\service.stdout.log"
& $NssmPath set ZingsaFilesCenter AppStderr "$DataDir\logs\service.stderr.log"
& $NssmPath set ZingsaFilesCenter AppRotateFiles 1
& $NssmPath set ZingsaFilesCenter AppExit Default Restart
& $NssmPath set ZingsaFilesCenter Start SERVICE_AUTO_START
& $NssmPath set ZingsaFilesCenter AppEnvironmentExtra "TRANSCRIBE_DATA_DIR=$DataDir" "TRANSCRIBE_FFMPEG=$FfmpegPath" "TRANSCRIBE_ADMIN_USER=$AdminUser" "TRANSCRIBE_ADMIN_PASSWORD=$AdminPassword"

# Firewall configuration
Write-Host "Configuring Windows Firewall..."
New-NetFirewallRule -DisplayName 'Zingsa Files Center (Internal)' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Domain,Private -ErrorAction SilentlyContinue | Out-Null

# Start Service
Write-Host "Starting ZingsaFilesCenter service..."
Start-Service ZingsaFilesCenter
Get-Service ZingsaFilesCenter

Write-Host "`n[OK] Service successfully installed and started!" -ForegroundColor Green
Write-Host "Access the application at: http://localhost:$Port/ or http://server-name:$Port/" -ForegroundColor Cyan

