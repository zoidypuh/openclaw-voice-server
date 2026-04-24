# TTS Community Legacy Providers

This package archives TTS providers that were removed from Agentic Switchboard core:

- Piper
- Chatterbox
- Pocket TTS
- VibeVoice Realtime
- NeuTTS

Status: unmaintained by core. These files are kept so someone can turn them into a real plugin without making Agentic Switchboard carry their setup, dependencies, UI, or validation paths.

Install locally for experimentation:

```bash
pip install -e plugins/tts-community-legacy
```

Provider dependency extras:

```bash
pip install -e plugins/tts-community-legacy[piper]
pip install -e plugins/tts-community-legacy[chatterbox]
pip install -e plugins/tts-community-legacy[pockettts]
pip install -e plugins/tts-community-legacy[neutts]
```

VibeVoice still expects a separate VibeVoice server. Core does not auto-discover or load this package yet; a future plugin loader must register these providers explicitly.

Any local voice/model assets that used to live at the repo root were moved under `local-data/`, which is intentionally git-ignored.
