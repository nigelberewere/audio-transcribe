# ==============================================================================
# Zingsa Files Center - Automated Setup & Management Script
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [switch]$InstallService,
    [switch]$PreloadModels,
    [string]$Port = "8420",
    [string]$AdminUser = "admin",
    [string]$AdminPassword = ""
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "`n[+] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[!] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[X] $Message" -ForegroundColor Red
}

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return "py"
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        return "python3"
    }
    return $null
}

function Find-Ffmpeg {
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
        return (Get-Command ffmpeg).Source
    }
    $candidatePaths = @(
        "C:\ffmpeg\bin\ffmpeg.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg-*\bin\ffmpeg.exe",
        "C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        "$env:USERPROFILE\scoop\shims\ffmpeg.exe",
        "$PSScriptRoot\ffmpeg.exe"
    )
    foreach ($path in $candidatePaths) {
        $resolved = Resolve-Path $path -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path -First 1
        if ($resolved -and (Test-Path $resolved)) {
            return $resolved
        }
    }
    return $null
}

function Check-Admin {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

Clear-Host
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Zingsa Files Center - Automated Setup Assistant" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Check Python
Write-Step "Checking Python installation..."
$pyCmd = Get-PythonCommand
if (-not $pyCmd) {
    Write-Fail "Python was not found on your system."
    Write-Host "Please install Python 3.11+ from https://www.python.org or run:" -ForegroundColor Yellow
    Write-Host "  winget install Python.Python.3.11" -ForegroundColor Yellow
    exit 1
}
$pyVersion = & $pyCmd --version 2>&1
Write-Success "Found: $pyVersion"

# 2. Check FFmpeg
Write-Step "Checking FFmpeg..."
$ffmpegPath = Find-Ffmpeg
if ($ffmpegPath) {
    Write-Success "Found FFmpeg at: $ffmpegPath"
} else {
    Write-Warn "FFmpeg is not installed or not found in standard paths."
    Write-Host "Audio conversion requires FFmpeg. You can install it via:" -ForegroundColor Yellow
    Write-Host "  winget install Gyan.FFmpeg" -ForegroundColor Yellow
    Write-Host "Or place ffmpeg.exe in this folder or C:\ffmpeg\bin\." -ForegroundColor Yellow
    if (-not $NonInteractive) {
        $installFfmpeg = Read-Host "Would you like to try installing FFmpeg automatically via winget now? (y/n)"
        if ($installFfmpeg -match '^[yY]') {
            try {
                winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
                $ffmpegPath = Find-Ffmpeg
                if ($ffmpegPath) {
                    Write-Success "FFmpeg successfully installed: $ffmpegPath"
                }
            } catch {
                Write-Warn "Automatic winget install failed. You can install FFmpeg manually later."
            }
        }
    }
}

# 3. Create or check Virtual Environment (.venv)
Write-Step "Setting up Python Virtual Environment..."
$venvPython = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating .venv virtual environment..."
    & $pyCmd -m venv "$PSScriptRoot\.venv"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Failed to create virtual environment."
        exit 1
    }
}
Write-Success "Virtual environment ready at: .venv"

# 4. Install Dependencies
Write-Step "Installing/Updating required dependencies..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r "$PSScriptRoot\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Dependency installation encountered errors. Please check the output above."
    exit 1
}
Write-Success "All Python dependencies are installed."

# 5. Environment and Security (.env)
Write-Step "Checking environment configuration (.env)..."
$envPath = "$PSScriptRoot\.env"
if (-not (Test-Path $envPath)) {
    Write-Host "Creating initial .env file..."
    $randomSecret = [System.Guid]::NewGuid().ToString("N") + [System.Guid]::NewGuid().ToString("N")
    
    $initialEnv = @"
# Zingsa Files Center Configuration
TRANSCRIBE_HOST=0.0.0.0
TRANSCRIBE_PORT=$Port
TRANSCRIBE_SESSION_SECRET=$randomSecret
TRANSCRIBE_ADMIN_USER=$AdminUser
"@
    if ($ffmpegPath) {
        $initialEnv += "`nTRANSCRIBE_FFMPEG=$ffmpegPath"
    }
    Set-Content -Path $envPath -Value $initialEnv -Encoding utf8
    Write-Success ".env created with a secure session secret."
} else {
    Write-Success ".env configuration exists."
}

# 6. Ensure Storage Directories
Write-Step "Checking storage directories..."
& $venvPython -c "from app.config import Settings; s = Settings(); s.ensure_directories(); print('Directories verified.')"
Write-Success "Storage directories ready."

# 7. Preload Models if requested
if ($PreloadModels) {
    Write-Step "Preloading Whisper models (requires internet connection)..."
    & $venvPython "$PSScriptRoot\preload_models.py"
    Write-Success "Models preloaded."
}

# 8. Service Installation or Interactive Prompt
if ($InstallService) {
    Write-Step "Configuring Windows Background Service..."
    if (-not (Check-Admin)) {
        Write-Fail "Administrator rights are required to install a Windows Service."
        Write-Host "Please re-run this script in an elevated (Administrator) PowerShell window." -ForegroundColor Yellow
        exit 1
    }
    & "$PSScriptRoot\install-service.ps1" -Port [int]$Port
    exit 0
}

if (-not $NonInteractive) {
    Write-Host "`n============================================================" -ForegroundColor Green
    Write-Host "   Setup is Complete! What would you like to do next?" -ForegroundColor White
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  1. Launch Zingsa Files Center locally now" -ForegroundColor Cyan
    Write-Host "  2. Preload/Cache Whisper AI Models (recommended before offline use)" -ForegroundColor Cyan
    Write-Host "  3. Install as an automatic Windows Background Service" -ForegroundColor Cyan
    Write-Host "  4. Exit" -ForegroundColor Cyan
    Write-Host "------------------------------------------------------------"
    
    $choice = Read-Host "Enter choice (1-4) [Default: 1]"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

    switch ($choice) {
        "1" {
            Write-Host "`nStarting Zingsa Files Center on http://localhost:$Port/ ..." -ForegroundColor Green
            Start-Process "http://localhost:$Port"
            & $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port [int]$Port
        }
        "2" {
            Write-Host "`nDownloading & caching default models (large-v3, medium)..." -ForegroundColor Cyan
            & $venvPython "$PSScriptRoot\preload_models.py"
            Write-Success "Model caching complete. You can now start the server with start.bat or setup.bat!"
            Pause
        }
        "3" {
            if (-not (Check-Admin)) {
                Write-Warn "Installing as a service requires Administrator privileges."
                Write-Host "Attempting to restart in an elevated prompt..." -ForegroundColor Yellow
                Start-Process powershell -Verb RunAs -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$PSScriptRoot\setup.ps1`"", "-InstallService"
            } else {
                & "$PSScriptRoot\install-service.ps1" -Port [int]$Port
            }
        }
        Default {
            Write-Host "Exiting setup. You can start the server anytime using start.bat." -ForegroundColor Yellow
        }
    }
}
