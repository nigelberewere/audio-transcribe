@echo off
title Zingsa Files Center
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Virtual environment not found. Running initial setup...
    call "%~dp0setup.bat"
    exit /b
)

echo Starting Zingsa Files Center server...
start "" http://localhost:8420/

"%~dp0.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8420

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Server stopped unexpectedly.
    pause
)
