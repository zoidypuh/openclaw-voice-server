from __future__ import annotations

from pathlib import Path
from copy import deepcopy


APP_VERSION_LABEL = "v0.1"
DEFAULT_SAMPLE_TEXT = "Mara's Switchboard setup validation."
DEFAULT_VOICE_SESSION_KEY = "agent:main:voice-chat-main"
DEFAULT_LOCAL_GATEWAY_URL = "http://127.0.0.1:18789"
DEFAULT_HERMES_ROOT = str((Path.home() / ".hermes" / "hermes-agent").resolve())
DEFAULT_REMOTE_WHISPER_HOST_ALIAS = "remote-whisper"
DEFAULT_REMOTE_WHISPER_PORT = 18000
DEFAULT_REMOTE_WHISPER_ENDPOINT_PATH = "/v1/audio/transcriptions"
DEFAULT_REMOTE_WHISPER_MODEL = "distil-large-v3"
HOLD_TO_TALK_SHORTCUT_LABEL = "Ctrl+Alt+Shift+A"
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
    "xai": {
        "id": "xai",
        "label": "xAI STT",
        "package": None,
        "import_name": None,
        "default_model": "xai-stt",
        "models": [
            "xai-stt",
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
    "chatterbox-turbo": {
        "id": "chatterbox-turbo",
        "label": "Chatterbox Turbo",
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
    "MARAS_SWITCHBOARD_GATEWAY_TOKEN",
    "MARAS_SWITCHBOARD_ELEVENLABS_API_KEY",
    "MARAS_SWITCHBOARD_XAI_API_KEY",
    "XAI_API_KEY",
}

LEGACY_SECRET_ENV_KEYS = {
    key.replace("MARAS_SWITCHBOARD_", "AGENTIC_SWITCHBOARD_")
    for key in SECRET_ENV_KEYS
}

ENV_TO_CONFIG = {
    "MARAS_SWITCHBOARD_GATEWAY_URL": ("gateway", "url"),
    "MARAS_SWITCHBOARD_GATEWAY_MODEL": ("gateway", "model"),
    "MARAS_SWITCHBOARD_GATEWAY_SESSION_KEY": ("gateway", "session_key"),
    "MARAS_SWITCHBOARD_HERMES_ROOT": ("agent", "hermes_root"),
    "MARAS_SWITCHBOARD_HTTP_HOST": ("server", "host"),
    "MARAS_SWITCHBOARD_HTTP_PORT": ("server", "port"),
    "MARAS_SWITCHBOARD_WHISPER_MODEL": ("stt", "backend_models", "faster-whisper"),
    "MARAS_SWITCHBOARD_WHISPER_ENDPOINT_URL": ("stt", "whisper_endpoint_url"),
    "MARAS_SWITCHBOARD_WHISPER_ENDPOINT_MODEL": ("stt", "whisper_endpoint_model"),
    "MARAS_SWITCHBOARD_WHISPER_DEVICE": ("stt", "device"),
    "MARAS_SWITCHBOARD_WHISPER_COMPUTE_TYPE": ("stt", "compute_type"),
    "MARAS_SWITCHBOARD_WHISPER_LANG": ("stt", "language"),
    "MARAS_SWITCHBOARD_ELEVENLABS_VOICE_ID": ("tts", "elevenlabs_voice_id"),
    "MARAS_SWITCHBOARD_ELEVENLABS_MODEL": ("tts", "elevenlabs_model"),
    "MARAS_SWITCHBOARD_CHATTERBOX_PYTHON_PATH": ("tts", "chatterbox_python_path"),
    "MARAS_SWITCHBOARD_CHATTERBOX_TURBO_PYTHON_PATH": ("tts", "chatterbox_python_path"),
    "MARAS_SWITCHBOARD_CHATTERBOX_VOICE_PROMPT_PATH": ("tts", "chatterbox_voice_prompt_path"),
    "MARAS_SWITCHBOARD_CHATTERBOX_TURBO_VOICE_PROMPT_PATH": ("tts", "chatterbox_voice_prompt_path"),
    "MARAS_SWITCHBOARD_CHATTERBOX_DEVICE": ("tts", "chatterbox_device"),
    "MARAS_SWITCHBOARD_CHATTERBOX_TURBO_DEVICE": ("tts", "chatterbox_device"),
}

LEGACY_ENV_TO_CONFIG = {
    key.replace("MARAS_SWITCHBOARD_", "AGENTIC_SWITCHBOARD_"): path
    for key, path in ENV_TO_CONFIG.items()
}
CONFIG_ENV_TO_CONFIG = {
    **LEGACY_ENV_TO_CONFIG,
    **ENV_TO_CONFIG,
}
ALL_SECRET_ENV_KEYS = SECRET_ENV_KEYS | LEGACY_SECRET_ENV_KEYS


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
        "model": "maras-switchboard:main",
        "session_key": DEFAULT_VOICE_SESSION_KEY,
    },
    "agent": {
        "backend": "gateway",
        "hermes_root": DEFAULT_HERMES_ROOT,
        "use_context_files": True,
        "use_memory": True,
        "reply_sanity_check": True,
        "toolsets": [],
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
            "xai": "xai-stt",
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
        "supertonic_total_steps": 1,
        "supertonic_speed": 1.2,
        "chatterbox_python_path": "",
        "chatterbox_voice_prompt_path": "",
        "chatterbox_device": "auto",
        "chatterbox_exaggeration": 0.5,
        "chatterbox_temperature": 0.8,
        "chatterbox_top_p": 0.95,
        "chatterbox_top_k": 1000,
        "chatterbox_repetition_penalty": 1.2,
        "speaker_voice_ids": {},
        "speaker_overrides": {},
        "news_speakers": [],
    },
    "audio": {
        "silence_threshold": 0.015,
        "silence_ms": 900,
        "min_speech_ms": 350,
    },
    "windows_client": {},
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
        "chatterbox_turbo": {
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
