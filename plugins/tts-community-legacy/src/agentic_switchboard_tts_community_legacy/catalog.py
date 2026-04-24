DEFAULT_SAMPLE_TEXT = "Agentic Switchboard setup validation."

CHATTERBOX_DEFAULT_MODEL = "multilingual"
CHATTERBOX_DEFAULT_DEVICE = "auto"
CHATTERBOX_DEFAULT_VOICE = "default"

SUPPORTED_TTS_PROVIDERS = {
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
    "pockettts": {
        "id": "pockettts",
        "label": "Pocket TTS",
        "package": "pocket-tts>=1.1.1",
        "import_name": "pocket_tts",
    },
    "vibevoice": {
        "id": "vibevoice",
        "label": "VibeVoice Realtime",
        "package": None,
        "import_name": None,
    },
    "neutts": {
        "id": "neutts",
        "label": "NeuTTS",
        "package": "neutts",
        "import_name": "neutts",
    },
}
