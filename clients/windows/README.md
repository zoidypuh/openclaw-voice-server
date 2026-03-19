# OpenClaw Voice Windows Client

This is a Windows-oriented client wrapper for the existing Python voice server.

It does not replace the Python backend. It opens the existing voice runtime at `http://127.0.0.1:8765/voice` inside a hidden Tauri window, keeps the app available in the tray, and registers a few global shortcuts. The tray is the primary presence for normal use: the shell starts stopped/paused, and the tray menu can start voice and surface the window when microphone permission needs to be accepted. Spoken commands are handled by the backend, for example `hey stop` and `hey pause`.

## Default shortcuts

- `Ctrl+Shift+Space`: show or hide the main window
- `Ctrl+Shift+P`: click the existing pause or resume button in the voice UI
- immediate interrupt: `Ctrl+Alt+A`

This is still a hardcoded default. It should move into user-configurable shortcut settings later.

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

## Run in development

Start the Python backend first in Linux/macOS/WSL:

```bash
cd /path/to/openclaw-voice-server
source .venv/bin/activate
openclaw-voice-server
```

Then from this folder on Windows:

```powershell
cd C:\dev\openclaw-voice-server\clients\windows
npm install
npm run tauri:dev
```

## Build a Windows bundle

From this folder on Windows:

```powershell
cd C:\dev\openclaw-voice-server\clients\windows
npm install
npm run tauri:build
```

The shell does not bundle the Python server. Keep the backend and client as separate components.

## Manual verification

When testing voice control behavior, verify all of these cases explicitly:

- `Ctrl+Alt+A` interrupts immediately while the agent is speaking.
- Tray `Interrupt Now` interrupts immediately while the agent is speaking.
- saying `hey stop` interrupts the current reply reliably.
- saying `hey pause` pauses or resumes voice mode reliably.
- minor non-speech noises near the mic do not trigger `hey stop` or `hey pause`: sniffing, rustling, touching the mic, desk bumps.
- with the app configured for German STT, English or mixed German/English speech must not cause premature command detection from half-awake mumbling or partial speech.
