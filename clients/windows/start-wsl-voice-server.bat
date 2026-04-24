@echo off
setlocal

if not defined AGENTIC_SWITCHBOARD_WSL_REPO_PATH call :resolve_repo_path
if not defined AGENTIC_SWITCHBOARD_WSL_REPO_PATH (
  >&2 echo Failed to resolve the repository path for WSL. Set AGENTIC_SWITCHBOARD_WSL_REPO_PATH manually.
  exit /b 1
)

if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
if not defined AGENTIC_SWITCHBOARD_AUTOSTART_LOG_DIR set "AGENTIC_SWITCHBOARD_AUTOSTART_LOG_DIR=%LOCALAPPDATA%\AgenticSwitchboard\logs"

call :append_wslenv AGENTIC_SWITCHBOARD_WSL_REPO_PATH
call :append_wslenv AGENTIC_SWITCHBOARD_AUTOSTART_LOG_DIR/p

set "WSL_START_COMMAND=set -eu; mkdir -p \"$AGENTIC_SWITCHBOARD_AUTOSTART_LOG_DIR\"; LOG_FILE=\"$AGENTIC_SWITCHBOARD_AUTOSTART_LOG_DIR/wsl-voice-server.log\"; if bash -lc 'exec 3<>/dev/tcp/127.0.0.1/8765' >/dev/null 2>&1; then exit 0; fi; if [ ! -d \"$AGENTIC_SWITCHBOARD_WSL_REPO_PATH\" ]; then printf '[%%s] Missing repo path: %%s\n' \"$(date -Iseconds)\" \"$AGENTIC_SWITCHBOARD_WSL_REPO_PATH\" >> \"$LOG_FILE\"; exit 1; fi; cd \"$AGENTIC_SWITCHBOARD_WSL_REPO_PATH\"; if [ ! -f .venv/bin/activate ]; then printf '[%%s] Missing virtualenv at %%s/.venv\n' \"$(date -Iseconds)\" \"$AGENTIC_SWITCHBOARD_WSL_REPO_PATH\" >> \"$LOG_FILE\"; exit 1; fi; . .venv/bin/activate; if command -v agentic-switchboard >/dev/null 2>&1; then nohup agentic-switchboard >> \"$LOG_FILE\" 2>&1 </dev/null & exit 0; fi; if command -v uv >/dev/null 2>&1; then nohup uv run agentic-switchboard >> \"$LOG_FILE\" 2>&1 </dev/null & exit 0; fi; printf '[%%s] Could not find agentic-switchboard or uv in WSL.\n' \"$(date -Iseconds)\" >> \"$LOG_FILE\"; exit 1"

if defined AGENTIC_SWITCHBOARD_WSL_DISTRO (
  wsl.exe -d "%AGENTIC_SWITCHBOARD_WSL_DISTRO%" bash -lc "%WSL_START_COMMAND%"
) else (
  wsl.exe bash -lc "%WSL_START_COMMAND%"
)

exit /b %errorlevel%

:resolve_repo_path
for %%I in ("%~dp0..\..") do set "AGENTIC_SWITCHBOARD_REPO_WIN_PATH=%%~fI"
if not defined AGENTIC_SWITCHBOARD_REPO_WIN_PATH exit /b 0
if defined AGENTIC_SWITCHBOARD_WSL_DISTRO (
  for /f "usebackq delims=" %%I in (`wsl.exe -d "%AGENTIC_SWITCHBOARD_WSL_DISTRO%" wslpath -a "%AGENTIC_SWITCHBOARD_REPO_WIN_PATH%" 2^>nul`) do set "AGENTIC_SWITCHBOARD_WSL_REPO_PATH=%%I"
) else (
  for /f "usebackq delims=" %%I in (`wsl.exe wslpath -a "%AGENTIC_SWITCHBOARD_REPO_WIN_PATH%" 2^>nul`) do set "AGENTIC_SWITCHBOARD_WSL_REPO_PATH=%%I"
)
exit /b 0

:append_wslenv
if defined WSLENV (
  set "WSLENV=%WSLENV%:%~1"
) else (
  set "WSLENV=%~1"
)
exit /b 0
