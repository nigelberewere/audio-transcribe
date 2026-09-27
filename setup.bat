@echo off
title Zingsa Files Center - Setup Assistant
cd /d "%~dp0"

echo ============================================================
echo   Launching Zingsa Files Center Setup Assistant...
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Setup encountered an issue. Press any key to close this window.
    pause >nul
)
