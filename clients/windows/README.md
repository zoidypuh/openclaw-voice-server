# Mara's Switchboard Windows Client

This is a Windows-oriented client wrapper for the existing Python voice server.

It does not replace the Python backend. It opens the existing voice runtime at `http://127.0.0.1:8765/voice` inside a hidden Tauri window and keeps the app available in the tray. The shell starts muted. Click `mute` to unmute for normal freehand conversation, or hold the single global shortcut to record one turn.

## Keyboard Shortcut

- `Alt+Shift+A`: hold to record, release to send the captured speech to the Python backend, then return to mute.

There are no configurable keyboard shortcuts in the setup UI.

## Tray status

The tray icon updates while the hidden voice page runs:

- teal microphone: listening
- amber dots: thinking
- green bars: speaking
- red cross: reconnecting or disconnected
- gray pause bars: paused

## Prerequisites

- Windows with WebView2 available
- Node.js 20+
- Rust toolchain installed through `rustup`
- the Python voice server from this repo running locally on `http://127.0.0.1:8765`

---

## Windows v1 Setup (native, no WSL)

This is the supported path for running the voice server **directly on Windows** without WSL.

**Constraints:**
- No local GPU Whisper. Use CPU Whisper or a remote Whisper endpoint.
- TTS works: ElevenLabs (paid) or Edge TTS (free).
- Local GPU STT requires CUDA on Windows — not in v1 scope.

### Step 1 — Bootstrap

```powershell
cd C:\path\to\maras-switchboard\clients\windows
py bootstrap-windows.py
```

This creates `.venv`, installs deps, and prompts for required secrets.

### Step 2 — Configure for Windows v1

Edit `config.json` in the repo root:

```json
{
  "stt": {
    "device": "cpu",
    "default_backend": "faster-whisper",
    "whisper_endpoint_url": ""
  },
  "tts": {
    "enabled_providers": ["elevenlabs"],
    "default_provider": "elevenlabs"
  }
}
```

Or set `MARAS_SWITCHBOARD_WHISPER_DEVICE=cpu` in `.env`.

For a **remote Whisper endpoint** instead of local CPU, set:
```
MARAS_SWITCHBOARD_WHISPER_ENDPOINT_URL=https://your-whisper-endpoint.com
MARAS_SWITCHBOARD_WHISPER_ENDPOINT_MODEL=large-v3
```

### Step 3 — Start

```powershell
.\start-windows-backend.bat
```

For autostart without a visible terminal, put a shortcut to `start-windows-backend-hidden.vbs` in Startup.

To test manually:

```powershell
wscript.exe .\start-windows-backend-hidden.vbs
```

### Quick reference

| File | Purpose |
|------|---------|
| `bootstrap-windows.py` | One-time setup: venv + deps + .env |
| `start-windows-backend.bat` | Launch backend natively on Windows |
| `start-windows-backend-hidden.vbs` | Launch `start-windows-backend.bat` hidden (Startup-safe) |
| `src-tauri/` | Tray client (Tauri) — connects to `http://127.0.0.1:8765/voice` |

---

## Run in development

Start the Python backend first in Linux/macOS/WSL:

```bash
cd /path/to/maras-switchboard
source .venv/bin/activate
maras-switchboard
```

Then from this folder on Windows:

```powershell
cd C:\path\to\maras-switchboard\clients\windows
npm install
npm run tauri:dev
```

## Headless WSL Autostart

If you want Windows login to bring up the WSL backend without a visible terminal, use the launcher pair in this folder:

- `start-wsl-voice-server.bat`
  contains the actual `wsl.exe` startup logic
- `start-wsl-voice-server-hidden.vbs`
  runs the batch file with window style `0`, so no extra console window appears

The batch script:

- resolves the repo root relative to this folder
- starts the backend inside WSL from that repo
- reuses the existing `.venv` if present
- skips startup if something is already listening on `127.0.0.1:8765`
- writes backend logs to `%LOCALAPPDATA%\MarasSwitchboard\logs\wsl-voice-server.log`

Optional environment variable:

- `MARAS_SWITCHBOARD_WSL_DISTRO`
  set this in Windows if you need a specific distro instead of the default WSL distro
- `MARAS_SWITCHBOARD_WSL_REPO_PATH`
  set this only if the repo is not next to this script or if you want to override the auto-detected WSL path

Startup usage:

1. Build or install the Windows tray client separately if you want it to launch too.
2. Press `Win+R`, run `shell:startup`.
3. Put a shortcut to `start-wsl-voice-server-hidden.vbs` into that Startup folder.

For a manual smoke test from Windows without showing a terminal:

```powershell
wscript.exe .\start-wsl-voice-server-hidden.vbs
```

## Build a Windows bundle

From this folder on Windows:

```powershell
cd C:\path\to\maras-switchboard\clients\windows
npm install
npm run tauri:build
```

The shell does not bundle the Python server. Keep the backend and client as separate components.

## Manual verification

When testing voice behavior, verify all of these cases explicitly:

- the UI starts muted.
- clicking `mute` un-mutes the mic for normal freehand conversation.
- holding `Alt+Shift+A` captures a held turn and releasing it sends immediately, then returns the UI to mute.
- Tray `Interrupt Now` interrupts immediately while the agent is speaking.
- no spoken command phrases are interpreted by the backend.
