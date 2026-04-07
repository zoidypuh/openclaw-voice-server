@echo off
setlocal

if not defined OPENCLAW_WSL_REPO_PATH call :resolve_repo_path
if not defined OPENCLAW_WSL_REPO_PATH (
  >&2 echo Failed to resolve the repository path for WSL. Set OPENCLAW_WSL_REPO_PATH manually.
  exit /b 1
)

if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
if not defined OPENCLAW_VOICE_AUTOSTART_LOG_DIR set "OPENCLAW_VOICE_AUTOSTART_LOG_DIR=%LOCALAPPDATA%\OpenClawVoice\logs"

call :append_wslenv OPENCLAW_WSL_REPO_PATH
call :append_wslenv OPENCLAW_VOICE_AUTOSTART_LOG_DIR/p

set "WSL_START_COMMAND=set -eu; mkdir -p \"$OPENCLAW_VOICE_AUTOSTART_LOG_DIR\"; LOG_FILE=\"$OPENCLAW_VOICE_AUTOSTART_LOG_DIR/wsl-voice-server.log\"; if bash -lc 'exec 3<>/dev/tcp/127.0.0.1/8765' >/dev/null 2>&1; then exit 0; fi; if [ ! -d \"$OPENCLAW_WSL_REPO_PATH\" ]; then printf '[%%s] Missing repo path: %%s\n' \"$(date -Iseconds)\" \"$OPENCLAW_WSL_REPO_PATH\" >> \"$LOG_FILE\"; exit 1; fi; cd \"$OPENCLAW_WSL_REPO_PATH\"; if [ ! -f .venv/bin/activate ]; then printf '[%%s] Missing virtualenv at %%s/.venv\n' \"$(date -Iseconds)\" \"$OPENCLAW_WSL_REPO_PATH\" >> \"$LOG_FILE\"; exit 1; fi; . .venv/bin/activate; if command -v openclaw-voice-server >/dev/null 2>&1; then nohup openclaw-voice-server >> \"$LOG_FILE\" 2>&1 </dev/null & exit 0; fi; if command -v uv >/dev/null 2>&1; then nohup uv run openclaw-voice-server >> \"$LOG_FILE\" 2>&1 </dev/null & exit 0; fi; printf '[%%s] Could not find openclaw-voice-server or uv in WSL.\n' \"$(date -Iseconds)\" >> \"$LOG_FILE\"; exit 1"

if defined OPENCLAW_WSL_DISTRO (
  wsl.exe -d "%OPENCLAW_WSL_DISTRO%" bash -lc "%WSL_START_COMMAND%"
) else (
  wsl.exe bash -lc "%WSL_START_COMMAND%"
)

exit /b %errorlevel%

:resolve_repo_path
for %%I in ("%~dp0..\..") do set "OPENCLAW_REPO_WIN_PATH=%%~fI"
if not defined OPENCLAW_REPO_WIN_PATH exit /b 0
if defined OPENCLAW_WSL_DISTRO (
  for /f "usebackq delims=" %%I in (`wsl.exe -d "%OPENCLAW_WSL_DISTRO%" wslpath -a "%OPENCLAW_REPO_WIN_PATH%" 2^>nul`) do set "OPENCLAW_WSL_REPO_PATH=%%I"
) else (
  for /f "usebackq delims=" %%I in (`wsl.exe wslpath -a "%OPENCLAW_REPO_WIN_PATH%" 2^>nul`) do set "OPENCLAW_WSL_REPO_PATH=%%I"
)
exit /b 0

:append_wslenv
if defined WSLENV (
  set "WSLENV=%WSLENV%:%~1"
) else (
  set "WSLENV=%~1"
)
exit /b 0
