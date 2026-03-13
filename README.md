# OpenClaw Voice Server

`openclaw-voice-server` turns a browser into a thin voice client for an OpenClaw gateway session.

It keeps the heavy work on the server:

- Browser mic capture over WebSocket
- STT with `faster-whisper`
- streamed reply generation via the OpenClaw-compatible chat endpoint
- TTS with ElevenLabs
- audio streamed back to the browser

This project was extracted from the ad hoc Bonnie voice prototype in `~/.openclaw/workspace/voice-chat` and cleans out the user-specific glue.

## Current scope

- One configured OpenClaw session target per server instance
- One active browser client at a time for interrupt/toggle control
- `faster-whisper` STT
- ElevenLabs TTS
- static browser client served by the same process

Not migrated from the prototype:

- Telegram mirroring
- transcript-file mutation
- Windows temp-file handoff
- AutoHotkey launch scripts
- Deepgram experiments

## Installation

```bash
cd /home/gismar/openclaw-voice-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Configuration

Configuration is environment-driven.

Required:

- `OPENCLAW_VOICE_GATEWAY_TOKEN`
- `OPENCLAW_VOICE_ELEVENLABS_API_KEY`
- `OPENCLAW_VOICE_ELEVENLABS_VOICE_ID`

Common optional settings:

```bash
export OPENCLAW_VOICE_GATEWAY_URL="http://127.0.0.1:18789/v1/chat/completions"
export OPENCLAW_VOICE_GATEWAY_TOKEN="bonnie"
export OPENCLAW_VOICE_GATEWAY_SESSION_KEY="agent:main:telegram:direct:7001453699"
export OPENCLAW_VOICE_GATEWAY_MODEL="openclaw:main"

export OPENCLAW_VOICE_ELEVENLABS_API_KEY="..."
export OPENCLAW_VOICE_ELEVENLABS_VOICE_ID="..."
export OPENCLAW_VOICE_ELEVENLABS_MODEL="eleven_flash_v2_5"

export OPENCLAW_VOICE_WHISPER_MODEL="large-v3"
export OPENCLAW_VOICE_WHISPER_DEVICE="cuda"
export OPENCLAW_VOICE_WHISPER_LANG="de"

export OPENCLAW_VOICE_HTTP_HOST="127.0.0.1"
export OPENCLAW_VOICE_HTTP_PORT="8765"
export OPENCLAW_VOICE_WS_HOST="127.0.0.1"
export OPENCLAW_VOICE_WS_PORT="8766"
```

## Running

```bash
source .venv/bin/activate
openclaw-voice-server

# or
python -m openclaw_voice_server
```

Open the UI at `http://127.0.0.1:8765/`.

## HTTP endpoints

- `GET /` browser client
- `GET /health` liveness information
- `POST /interrupt` interrupt the active turn
- `POST /toggle-listen` toggle listen state in the browser
- `POST /say` queue proactive speech to the connected browser

Example:

```bash
curl -s http://127.0.0.1:8765/health
curl -s -X POST http://127.0.0.1:8765/say \
  -H 'content-type: application/json' \
  -d '{"text":"Dinner is ready."}'
```

## Development

```bash
pytest
```

The test suite currently covers the text normalization and send-phrase logic that was most likely to regress during extraction.
