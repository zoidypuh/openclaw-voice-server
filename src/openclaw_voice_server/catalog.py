from __future__ import annotations

from copy import deepcopy
from pathlib import Path


APP_VERSION_LABEL = "v0.04"
DEFAULT_SAMPLE_TEXT = "OpenClaw voice setup validation."
DEFAULT_VOICE_SESSION_KEY = "agent:main:voice-chat-main"
DEFAULT_LOCAL_GATEWAY_URL = "http://127.0.0.1:18789"
DEFAULT_HERMES_ROOT = str((Path.home() / ".hermes" / "hermes-agent").resolve())
DEFAULT_REMOTE_WHISPER_HOST_ALIAS = "remote-whisper"
DEFAULT_REMOTE_WHISPER_PORT = 18000
DEFAULT_REMOTE_WHISPER_ENDPOINT_PATH = "/v1/audio/transcriptions"
DEFAULT_REMOTE_WHISPER_MODEL = ""
DEFAULT_VIBEVOICE_BASE_URL = "http://127.0.0.1:3000"
DEFAULT_WINDOWS_SHORTCUTS = {
    "toggle_window": "Ctrl+Shift+Space",
    "pause_resume": "Ctrl+Shift+P",
    "interrupt": "Ctrl+Alt+A",
}
CHATTERBOX_DEFAULT_MODEL = "multilingual"
CHATTERBOX_DEFAULT_DEVICE = "auto"
CHATTERBOX_DEFAULT_VOICE = "default"
ELEVENLABS_DEFAULT_PRESET = "natural"
ELEVENLABS_PRESETS = {
    "calm": {
        "label": "Calm",
        "voice_settings": {
            "stability": 0.72,
            "similarity_boost": 0.9,
            "style": 0.05,
            "use_speaker_boost": True,
            "speed": 0.95,
        },
    },
    "natural": {
        "label": "Natural",
        "voice_settings": {
            "stability": 0.55,
            "similarity_boost": 0.86,
            "style": 0.12,
            "use_speaker_boost": True,
            "speed": 1.0,
        },
    },
    "expressive": {
        "label": "Expressive",
        "voice_settings": {
            "stability": 0.34,
            "similarity_boost": 0.88,
            "style": 0.46,
            "use_speaker_boost": True,
            "speed": 0.98,
        },
    },
    "focused": {
        "label": "Focused",
        "voice_settings": {
            "stability": 0.68,
            "similarity_boost": 0.83,
            "style": 0.08,
            "use_speaker_boost": True,
            "speed": 1.03,
        },
    },
}

SUPPORTED_STT_BACKENDS = {
    "faster-whisper": {
        "id": "faster-whisper",
        "label": "Faster Whisper",
        "package": "faster-whisper>=1.1.0",
        "import_name": "faster_whisper",
        "default_model": "large-v3",
        "models": [
            "tiny",
            "base",
            "small",
            "medium",
            "large-v2",
            "large-v3",
            "distil-large-v3",
        ],
    },
    "whisper": {
        "id": "whisper",
        "label": "OpenAI Whisper",
        "package": "openai-whisper>=20240930",
        "import_name": "whisper",
        "default_model": "large",
        "models": [
            "tiny",
            "base",
            "small",
            "medium",
            "large",
            "turbo",
        ],
    },
}

SUPPORTED_TTS_PROVIDERS = {
    "edge": {
        "id": "edge",
        "label": "Edge TTS",
        "package": "edge-tts>=6.1.0",
        "import_name": "edge_tts",
    },
    "piper": {
        "id": "piper",
        "label": "Piper",
        "package": "piper-tts>=1.4.1",
        "import_name": "piper",
    },
    "chatterbox": {
        "id": "chatterbox",
        "label": "Chatterbox",
        "package": "chatterbox-tts>=0.1.7",
        "import_name": "chatterbox",
    },
    "elevenlabs": {
        "id": "elevenlabs",
        "label": "ElevenLabs",
        "package": None,
        "import_name": None,
    },
    "vibevoice": {
        "id": "vibevoice",
        "label": "VibeVoice Realtime",
        "package": None,
        "import_name": None,
    },
}

SUPPORTED_AGENT_BACKENDS = {
    "openclaw": {
        "id": "openclaw",
        "label": "OpenClaw Agent",
    },
    "hermes": {
        "id": "hermes",
        "label": "Hermes Agent",
    },
}

SECRET_ENV_KEYS = {
    "OPENCLAW_VOICE_GATEWAY_TOKEN",
    "OPENCLAW_VOICE_ELEVENLABS_API_KEY",
}

LEGACY_ENV_TO_CONFIG = {
    "OPENCLAW_VOICE_GATEWAY_URL": ("gateway", "url"),
    "OPENCLAW_VOICE_GATEWAY_MODEL": ("gateway", "model"),
    "OPENCLAW_VOICE_GATEWAY_SESSION_KEY": ("gateway", "session_key"),
    "OPENCLAW_VOICE_HERMES_ROOT": ("agent", "hermes_root"),
    "OPENCLAW_VOICE_HTTP_HOST": ("server", "host"),
    "OPENCLAW_VOICE_HTTP_PORT": ("server", "port"),
    "OPENCLAW_VOICE_WHISPER_MODEL": ("stt", "backend_models", "faster-whisper"),
    "OPENCLAW_VOICE_WHISPER_ENDPOINT_URL": ("stt", "whisper_endpoint_url"),
    "OPENCLAW_VOICE_WHISPER_ENDPOINT_MODEL": ("stt", "whisper_endpoint_model"),
    "OPENCLAW_VOICE_WHISPER_DEVICE": ("stt", "device"),
    "OPENCLAW_VOICE_WHISPER_COMPUTE_TYPE": ("stt", "compute_type"),
    "OPENCLAW_VOICE_WHISPER_LANG": ("stt", "language"),
    "OPENCLAW_VOICE_ELEVENLABS_VOICE_ID": ("tts", "elevenlabs_voice_id"),
    "OPENCLAW_VOICE_ELEVENLABS_MODEL": ("tts", "elevenlabs_model"),
    "OPENCLAW_VOICE_PIPER_MODEL": ("tts", "piper_model_path"),
    "OPENCLAW_VOICE_PIPER_CONFIG": ("tts", "piper_config_path"),
    "OPENCLAW_VOICE_PIPER_SPEAKER": ("tts", "piper_speaker"),
    "OPENCLAW_VOICE_VIBEVOICE_BASE_URL": ("tts", "vibevoice_base_url"),
    "OPENCLAW_VOICE_VIBEVOICE_VOICE": ("tts", "vibevoice_voice"),
}

DEFAULT_CONFIG = {
    "schema_version": 1,
    "server": {
        "host": "127.0.0.1",
        "port": 8765,
    },
    "gateway": {
        "url": DEFAULT_LOCAL_GATEWAY_URL,
        "model": "openclaw:main",
        "session_key": DEFAULT_VOICE_SESSION_KEY,
    },
    "agent": {
        "backend": "openclaw",
        "hermes_root": DEFAULT_HERMES_ROOT,
    },
    "stt": {
        "enabled_backends": ["faster-whisper"],
        "default_backend": "faster-whisper",
        "language": "de",
        "device": "cuda",
        "compute_type": "float16",
        "whisper_endpoint_url": "",
        "whisper_endpoint_model": "",
        "backend_models": {
            "faster-whisper": "large-v3",
            "whisper": "large",
        },
    },
    "tts": {
        "enabled_providers": ["edge"],
        "default_provider": "edge",
        "edge_voice": "",
        "edge_rate": "+0%",
        "elevenlabs_voice_id": "",
        "elevenlabs_voice_name": "",
        "elevenlabs_model": "eleven_flash_v2_5",
        "elevenlabs_preset": ELEVENLABS_DEFAULT_PRESET,
        "piper_model_path": "",
        "piper_config_path": "",
        "piper_speaker": 0,
        "chatterbox_model": CHATTERBOX_DEFAULT_MODEL,
        "chatterbox_device": CHATTERBOX_DEFAULT_DEVICE,
        "chatterbox_language": "de",
        "chatterbox_voice": CHATTERBOX_DEFAULT_VOICE,
        "speaker_voice_ids": {},
        "speaker_overrides": {},
        "news_speakers": [],
        "vibevoice_base_url": DEFAULT_VIBEVOICE_BASE_URL,
        "vibevoice_voice": "",
    },
    "audio": {
        "silence_threshold": 0.015,
        "silence_ms": 2000,
        "min_speech_ms": 500,
    },
    "windows_client": {
        "shortcuts": deepcopy(DEFAULT_WINDOWS_SHORTCUTS),
    },
    "validation": {
        "stt": {
            "config_hash": "",
        },
        "tts": {
            "config_hash": "",
        },
        "edge": {
            "config_hash": "",
        },
        "eleven_key": {
            "api_key_fingerprint": "",
        },
        "eleven_voice": {
            "config_hash": "",
            "api_key_fingerprint": "",
        },
        "piper": {
            "config_hash": "",
        },
        "chatterbox": {
            "config_hash": "",
        },
        "vibevoice": {
            "config_hash": "",
        },
        "gateway": {
            "config_hash": "",
            "token_fingerprint": "",
        },
        "hermes": {
            "config_hash": "",
        },
        "windows_client": {
            "config_hash": "",
        },
    },
}


def default_config() -> dict:
    return deepcopy(DEFAULT_CONFIG)
