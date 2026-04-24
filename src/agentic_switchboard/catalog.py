from __future__ import annotations

from copy import deepcopy
from pathlib import Path


APP_VERSION_LABEL = "v0.1"
DEFAULT_SAMPLE_TEXT = "Agentic Switchboard setup validation."
DEFAULT_VOICE_SESSION_KEY = "agent:main:voice-chat-main"
DEFAULT_LOCAL_GATEWAY_URL = "http://127.0.0.1:18789"
DEFAULT_HERMES_ROOT = str((Path.home() / ".hermes" / "hermes-agent").resolve())
DEFAULT_REMOTE_WHISPER_HOST_ALIAS = "remote-whisper"
DEFAULT_REMOTE_WHISPER_PORT = 18000
DEFAULT_REMOTE_WHISPER_ENDPOINT_PATH = "/v1/audio/transcriptions"
DEFAULT_REMOTE_WHISPER_MODEL = ""
DEFAULT_WINDOWS_SHORTCUTS = {
    "toggle_window": "Ctrl+Shift+Space",
    "pause_resume": "Ctrl+Shift+P",
    "interrupt": "Ctrl+Alt+A",
}
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
    "disabled": {
        "id": "disabled",
        "label": "Disabled (text only)",
        "package": None,
        "import_name": None,
    },
    "edge": {
        "id": "edge",
        "label": "Edge TTS",
        "package": "edge-tts>=6.1.0",
        "import_name": "edge_tts",
    },
    "supertonic": {
        "id": "supertonic",
        "label": "Supertonic",
        "package": None,
        "import_name": None,
    },
    "elevenlabs": {
        "id": "elevenlabs",
        "label": "ElevenLabs",
        "package": None,
        "import_name": None,
    },
}

SUPPORTED_AGENT_BACKENDS = {
    "gateway": {
        "id": "gateway",
        "label": "Gateway Agent",
    },
    "hermes": {
        "id": "hermes",
        "label": "Hermes Agent",
    },
}

SECRET_ENV_KEYS = {
    "AGENTIC_SWITCHBOARD_GATEWAY_TOKEN",
    "AGENTIC_SWITCHBOARD_ELEVENLABS_API_KEY",
}

ENV_TO_CONFIG = {
    "AGENTIC_SWITCHBOARD_GATEWAY_URL": ("gateway", "url"),
    "AGENTIC_SWITCHBOARD_GATEWAY_MODEL": ("gateway", "model"),
    "AGENTIC_SWITCHBOARD_GATEWAY_SESSION_KEY": ("gateway", "session_key"),
    "AGENTIC_SWITCHBOARD_HERMES_ROOT": ("agent", "hermes_root"),
    "AGENTIC_SWITCHBOARD_HTTP_HOST": ("server", "host"),
    "AGENTIC_SWITCHBOARD_HTTP_PORT": ("server", "port"),
    "AGENTIC_SWITCHBOARD_WHISPER_MODEL": ("stt", "backend_models", "faster-whisper"),
    "AGENTIC_SWITCHBOARD_WHISPER_ENDPOINT_URL": ("stt", "whisper_endpoint_url"),
    "AGENTIC_SWITCHBOARD_WHISPER_ENDPOINT_MODEL": ("stt", "whisper_endpoint_model"),
    "AGENTIC_SWITCHBOARD_WHISPER_DEVICE": ("stt", "device"),
    "AGENTIC_SWITCHBOARD_WHISPER_COMPUTE_TYPE": ("stt", "compute_type"),
    "AGENTIC_SWITCHBOARD_WHISPER_LANG": ("stt", "language"),
    "AGENTIC_SWITCHBOARD_ELEVENLABS_VOICE_ID": ("tts", "elevenlabs_voice_id"),
    "AGENTIC_SWITCHBOARD_ELEVENLABS_MODEL": ("tts", "elevenlabs_model"),
}


def normalize_agent_backend(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "gateway"}:
        return "gateway"
    if normalized == "hermes":
        return "hermes"
    return "gateway"

DEFAULT_CONFIG = {
    "schema_version": 1,
    "server": {
        "host": "127.0.0.1",
        "port": 8765,
    },
    "gateway": {
        "url": DEFAULT_LOCAL_GATEWAY_URL,
        "model": "agentic-switchboard:main",
        "session_key": DEFAULT_VOICE_SESSION_KEY,
    },
    "agent": {
        "backend": "gateway",
        "hermes_root": DEFAULT_HERMES_ROOT,
        "use_context_files": True,
        "use_memory": True,
        "toolsets": ["browser", "file", "web"],
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
        "supertonic_python_path": "",
        "supertonic_voice": "M4",
        "supertonic_language": "en",
        "supertonic_total_steps": 3,
        "supertonic_speed": 1.05,
        "speaker_voice_ids": {},
        "speaker_overrides": {},
        "news_speakers": [],
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
        "supertonic": {
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
