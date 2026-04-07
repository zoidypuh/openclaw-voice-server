from __future__ import annotations

from ..catalog import CHATTERBOX_DEFAULT_DEVICE, CHATTERBOX_DEFAULT_MODEL
from ..errors import ValidationError
from .base import BaseSynthesizer, Synthesizer
from .chatterbox import (
    CHATTERBOX_DEFAULT_LANGUAGE,
    CHATTERBOX_SUPPORTED_DEVICES,
    CHATTERBOX_SUPPORTED_MODELS,
    ChatterboxSynthesizer,
    _load_chatterbox_model,
    list_local_chatterbox_voices,
    normalize_chatterbox_device,
    normalize_chatterbox_language,
    normalize_chatterbox_model,
    resolve_chatterbox_voice,
    validate_chatterbox_voice,
)
from .edge import EdgeSynthesizer, list_edge_voices, validate_edge_voice
from .elevenlabs import (
    ElevenLabsSynthesizer,
    list_elevenlabs_voices,
    normalize_elevenlabs_preset,
    validate_elevenlabs_api_key,
    validate_elevenlabs_voice,
)
from .piper import (
    PiperSynthesizer,
    _piper_command,
    default_piper_config_path,
    normalize_piper_model_path,
    normalize_piper_speaker,
    validate_piper_voice,
)
from .vibevoice import (
    VibeVoiceSynthesizer,
    _fetch_vibevoice_config,
    _pcm16le_to_wav,
    list_vibevoice_voices,
    normalize_vibevoice_base_url,
    validate_vibevoice_voice,
)


def build_synthesizer(tts_settings: dict, secrets: dict[str, str]) -> BaseSynthesizer:
    provider = tts_settings["default_provider"]
    if provider == "edge":
        return EdgeSynthesizer(
            voice=tts_settings["edge_voice"],
            rate=tts_settings["edge_rate"],
        )
    if provider == "elevenlabs":
        return ElevenLabsSynthesizer(
            api_key=secrets["elevenlabs_api_key"],
            voice_id=tts_settings["elevenlabs_voice_id"],
            model_id=tts_settings["elevenlabs_model"],
            default_preset=tts_settings["elevenlabs_preset"],
        )
    if provider == "piper":
        return PiperSynthesizer(
            model_path=tts_settings["piper_model_path"],
            config_path=tts_settings.get("piper_config_path", ""),
            speaker=tts_settings.get("piper_speaker", 0),
        )
    if provider == "chatterbox":
        return ChatterboxSynthesizer(
            model=tts_settings.get("chatterbox_model", CHATTERBOX_DEFAULT_MODEL),
            device=tts_settings.get("chatterbox_device", CHATTERBOX_DEFAULT_DEVICE),
            language=tts_settings.get("chatterbox_language", CHATTERBOX_DEFAULT_LANGUAGE),
            voice=tts_settings.get("chatterbox_voice", "default"),
        )
    if provider == "vibevoice":
        return VibeVoiceSynthesizer(
            base_url=tts_settings["vibevoice_base_url"],
            voice=tts_settings["vibevoice_voice"],
        )
    raise ValidationError(f"Unsupported TTS provider: {provider}")
