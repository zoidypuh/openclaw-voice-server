from __future__ import annotations

from ..errors import ValidationError
from .base import BaseSynthesizer, Synthesizer
from .chatterbox_turbo import (
    CHATTERBOX_TURBO_DEFAULT_DEVICE,
    CHATTERBOX_TURBO_DEFAULT_EXAGGERATION,
    CHATTERBOX_TURBO_DEFAULT_REPETITION_PENALTY,
    CHATTERBOX_TURBO_DEFAULT_TEMPERATURE,
    CHATTERBOX_TURBO_DEFAULT_TOP_K,
    CHATTERBOX_TURBO_DEFAULT_TOP_P,
    ChatterboxTurboSynthesizer,
    detect_chatterbox_turbo_python_path,
    detect_chatterbox_turbo_voice_prompt_path,
    normalize_chatterbox_turbo_device,
    normalize_chatterbox_turbo_exaggeration,
    normalize_chatterbox_turbo_repetition_penalty,
    normalize_chatterbox_turbo_temperature,
    normalize_chatterbox_turbo_top_k,
    normalize_chatterbox_turbo_top_p,
    resolve_chatterbox_turbo_python_path,
    resolve_chatterbox_turbo_voice_prompt_path,
    validate_chatterbox_turbo_voice,
)
from .edge import EdgeSynthesizer, list_edge_voices, validate_edge_voice
from .elevenlabs import (
    ElevenLabsSynthesizer,
    list_elevenlabs_voices,
    normalize_elevenlabs_preset,
    validate_elevenlabs_api_key,
    validate_elevenlabs_voice,
)
from .supertonic import (
    SUPERTONIC_DEFAULT_LANGUAGE,
    SUPERTONIC_DEFAULT_SPEED,
    SUPERTONIC_DEFAULT_TOTAL_STEPS,
    SUPERTONIC_DEFAULT_VOICE,
    SUPERTONIC_SUPPORTED_LANGUAGES,
    SUPERTONIC_SUPPORTED_VOICES,
    SupertonicSynthesizer,
    detect_supertonic_python_path,
    normalize_supertonic_language,
    normalize_supertonic_speed,
    normalize_supertonic_total_steps,
    normalize_supertonic_voice,
    resolve_supertonic_python_path,
    validate_supertonic_voice,
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
    if provider == "supertonic":
        return SupertonicSynthesizer(
            python_path=tts_settings.get("supertonic_python_path", ""),
            voice=tts_settings.get("supertonic_voice", SUPERTONIC_DEFAULT_VOICE),
            language=tts_settings.get("supertonic_language", SUPERTONIC_DEFAULT_LANGUAGE),
            total_steps=tts_settings.get("supertonic_total_steps", SUPERTONIC_DEFAULT_TOTAL_STEPS),
            speed=tts_settings.get("supertonic_speed", SUPERTONIC_DEFAULT_SPEED),
        )
    if provider == "chatterbox-turbo":
        return ChatterboxTurboSynthesizer(
            python_path=tts_settings.get("chatterbox_python_path", ""),
            voice_prompt_path=tts_settings.get("chatterbox_voice_prompt_path", ""),
            device=tts_settings.get("chatterbox_device", CHATTERBOX_TURBO_DEFAULT_DEVICE),
            exaggeration=tts_settings.get(
                "chatterbox_exaggeration",
                CHATTERBOX_TURBO_DEFAULT_EXAGGERATION,
            ),
            temperature=tts_settings.get(
                "chatterbox_temperature",
                CHATTERBOX_TURBO_DEFAULT_TEMPERATURE,
            ),
            top_p=tts_settings.get("chatterbox_top_p", CHATTERBOX_TURBO_DEFAULT_TOP_P),
            top_k=tts_settings.get("chatterbox_top_k", CHATTERBOX_TURBO_DEFAULT_TOP_K),
            repetition_penalty=tts_settings.get(
                "chatterbox_repetition_penalty",
                CHATTERBOX_TURBO_DEFAULT_REPETITION_PENALTY,
            ),
        )
    raise ValidationError(f"Unsupported TTS provider: {provider}")
