from __future__ import annotations

from copy import deepcopy


APP_VERSION_LABEL = "v0.04"
DEFAULT_SAMPLE_TEXT = "OpenClaw voice setup validation."
DEFAULT_VOICE_SESSION_KEY = "agent:main:voice-chat-main"
DEFAULT_LOCAL_GATEWAY_URL = "http://127.0.0.1:18789"
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
    "elevenlabs": {
        "id": "elevenlabs",
        "label": "ElevenLabs",
        "package": None,
        "import_name": None,
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
    },
    "audio": {
        "silence_threshold": 0.015,
        "silence_ms": 2000,
        "min_speech_ms": 500,
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
        "gateway": {
            "config_hash": "",
            "token_fingerprint": "",
        },
    },
}


def default_config() -> dict:
    return deepcopy(DEFAULT_CONFIG)
