@echo off
REM Start agentic-switchboard natively on Windows (no WSL required).
REM
REM Prerequisites:
REM   1. Run bootstrap-windows.py once to create .venv and .env
REM   2. Edit config.json for CPU STT or a remote whisper_endpoint_url
REM
REM Usage: double-click this file, or put a shortcut in Startup for auto-launch.

setlocal

REM Resolve repo root relative to this .bat location
set "BAT_DIR=%~dp0"
set "REPO_DIR=%BAT_DIR%..\.."

REM Activate .venv
if exist "%REPO_DIR%\.venv\Scripts\activate.bat" (
    call "%REPO_DIR%\.venv\Scripts\activate.bat"
) else (
    echo ERROR: .venv not found at %REPO_DIR%\.venv
    echo Run bootstrap-windows.py first.
    pause
    exit /b 1
)

REM Change to repo root and start the server
cd /d "%REPO_DIR%"
echo Starting agentic-switchboard on http://127.0.0.1:8765 ...
python -m agentic_switchboard

echo.
echo Server exited. Press any key to close.
pause >nul
