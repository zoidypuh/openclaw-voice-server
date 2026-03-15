# OpenClaw Voice Server

`openclaw-voice-server` is an alpha browser voice client for a direct OpenClaw agent session.

It is provided as-is. It works well in the tested path, but it can still break, regress, or have rough edges.

## What It Does

- serves a browser setup flow at `/setup`
- serves a minimal voice runtime at `/voice`
- records mic audio in the browser
- detects end-of-utterance in the browser
- sends speech to the Python server for transcription
- sends the transcript to an OpenClaw gateway chat-completions endpoint
- synthesizes the reply with Edge TTS or ElevenLabs
- streams reply audio back to the browser

## How It Works

High level flow:

1. The browser captures microphone input.
2. The browser decides when the user finished speaking.
3. The Python server transcribes the audio with a Whisper-family backend.
4. The server sends the transcript to OpenClaw through the local gateway.
5. The server synthesizes the model reply with the selected TTS provider.
6. The browser plays the streamed reply audio and returns to listening.

## Alpha Status

- this is alpha software
- it is meant for real-world testing, not polished distribution
- gateway restarts, shared-session edge cases, and UI gaps can still cause failures
- if you need a stable production-grade voice client, this is not there yet

## Requirements

- Python 3.11+
- an existing OpenClaw installation
- an OpenClaw gateway reachable locally from the same host, typically `http://127.0.0.1:18789`
- one working STT backend
- one working TTS backend
- a browser with microphone access
- Tailscale if you want to use the app from other devices over MagicDNS

Optional, depending on chosen providers:

- CUDA if using GPU STT
- ElevenLabs API key if using ElevenLabs
- Edge TTS package if using Edge TTS

This app works from any device that can reach the host over Tailscale, for example through:

- `http://127.0.0.1:8765` on the host itself
- `https://<machine>.ts.net/voice/` from other tailnet devices through the existing proxy route

Network model:

- `127.0.0.1` is local to the machine running the service
- the voice server itself runs locally on that machine
- the browser can still reach it from other devices when your existing OpenClaw/Tailscale setup proxies `/voice/`
- the voice server talks to the OpenClaw gateway locally on the same host
- Tailscale/MagicDNS is for browser access from other devices, not for the voice server's backend-to-backend gateway call

## Tests

Run tests with:

```bash
PYTHONPATH=src python3 -m pytest
```

## Install

```bash
git clone <repo-url>
cd openclaw-voice-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Optional extras:

```bash
pip install -e .[dev,stt-faster-whisper,stt-whisper,tts-edge]
```

Run:

```bash
source .venv/bin/activate
openclaw-voice-server
```

Default local bind:

```text
http://127.0.0.1:8765
```

Recommended Tailscale/MagicDNS address when routed through the existing OpenClaw gateway:

```text
https://<machine>.ts.net/voice/
```

## Configuration

Configuration is split across:

- `config.json` for normal settings
- `.env` for secrets

The setup UI validates each section before saving it.

Setup sections:

1. `STT`
   Pick the speech-to-text backend, language, device, and model.
2. `TTS`
   Pick the speech provider.
3. `Edge Voice`
   If Edge is selected, choose and validate the voice.
4. `ElevenLabs`
   If ElevenLabs is selected, validate the API key and voice.
5. `Conversation Backend`
   Point the app at the local OpenClaw gateway and validate the session/model/token.

Important gateway rule:

- use the local gateway URL, for example `http://127.0.0.1:18789`
- the app will normalize it to `/v1/chat/completions`
- do not use the public `.ts.net` URL in the gateway field
- the `.ts.net` URL is for opening the voice UI from another device in a browser

## Sessions

By default, the app is intended to use a dedicated voice-chat session key.

That default can be overridden with another existing session key, including one that also routes messages to a channel such as Telegram.

That gives you two useful modes:

- dedicated voice session
  voice chat stays isolated from other channels
- shared channel-linked session
  for example, if voice uses the same session as Telegram:
  the agent can speak with you in voice chat and also send messages into Telegram
  and if you write to the agent in Telegram, that context can later be recalled inside the voice chat

This shared-session mode is powerful, but it also means voice and the other channel are using the same OpenClaw session state.

## Known Bugs

- minor: unnecessary OpenAI/OpenAI-compat sessions may still be spawned in some flows

## Tested

Tested successfully in the main path:

- Faster Whisper on CUDA
- ElevenLabs TTS
- OpenClaw local gateway on `127.0.0.1:18789`
- proxied `/voice/` route behind the existing OpenClaw/Tailscale setup

## Not Yet Tested

- Edge TTS
- OpenAI Whisper on CPU

## TODO

- add a pause control
- add interrupt-while-speaking support
- test Edge TTS end to end
- test Whisper on CPU end to end

## Routes

- `GET /` active page for current state
- `GET /setup` setup flow
- `GET /voice` voice runtime
- `GET /health` liveness/readiness
- `GET /api/setup/state` setup state
- `GET /api/runtime/state` runtime browser settings
- `GET /ws/voice` voice websocket
