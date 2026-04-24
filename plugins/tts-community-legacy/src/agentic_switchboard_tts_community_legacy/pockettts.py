from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from urllib.parse import urlparse

import numpy as np

from agentic_switchboard.errors import ValidationError
from agentic_switchboard.installer import ensure_python_package
from agentic_switchboard.tts.base import BaseSynthesizer

from .catalog import DEFAULT_SAMPLE_TEXT, SUPPORTED_TTS_PROVIDERS
from .vibevoice import _pcm16le_to_wav


POCKETTTS_DEFAULT_VARIANT = "b6369a24"
POCKETTTS_DEFAULT_VOICE = "alba"
POCKETTTS_PRESET_VOICES = {
    "alba": "Alba",
    "marius": "Marius",
    "javert": "Javert",
    "jean": "Jean",
    "fantine": "Fantine",
    "cosette": "Cosette",
    "eponine": "Eponine",
    "azelma": "Azelma",
}

_POCKETTTS_MODEL_CACHE: dict[str, object] = {}
_POCKETTTS_MODEL_LOCKS: dict[str, threading.Lock] = {}
_POCKETTTS_STATE_CACHE: dict[tuple[str, str], dict] = {}


def _ensure_pockettts_runtime() -> None:
    descriptor = SUPPORTED_TTS_PROVIDERS["pockettts"]
    ensure_python_package(descriptor["package"], descriptor["import_name"])


def normalize_pockettts_variant(value: str | None) -> str:
    return str(value or "").strip() or POCKETTTS_DEFAULT_VARIANT


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https", "hf"} and bool(parsed.netloc or parsed.path)


def normalize_pockettts_voice(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return POCKETTTS_DEFAULT_VOICE

    normalized_name = text.lower()
    if normalized_name in POCKETTTS_PRESET_VOICES:
        return normalized_name

    if _looks_like_url(text):
        return text

    path = Path(text).expanduser()
    if path.is_file():
        return str(path.resolve())

    if "/" in text or "\\" in text or Path(text).suffix:
        raise ValidationError(f"Pocket TTS voice reference was not found: {path}")

    raise ValidationError(
        "Pocket TTS voice must be one of the built-in presets "
        f"({', '.join(POCKETTTS_PRESET_VOICES)}) or a local audio/.safetensors path or http(s)/hf:// URL."
    )


def _pockettts_voice_name(value: str) -> str:
    if value in POCKETTTS_PRESET_VOICES:
        return POCKETTTS_PRESET_VOICES[value]
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https", "hf"}:
        return value
    return Path(value).name or value


def _float_audio_to_wav(audio, *, sample_rate: int) -> bytes:
    if hasattr(audio, "detach"):
        audio = audio.detach()
    if hasattr(audio, "cpu"):
        audio = audio.cpu()
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    pcm = np.clip(np.asarray(audio, dtype=np.float32).squeeze(), -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype(np.int16)
    return _pcm16le_to_wav(pcm16.tobytes(), sample_rate=sample_rate)


def _load_pockettts_model(*, variant: str):
    cached = _POCKETTTS_MODEL_CACHE.get(variant)
    if cached is not None:
        return cached

    _ensure_pockettts_runtime()
    from pocket_tts import TTSModel

    loaded = TTSModel.load_model(variant)
    _POCKETTTS_MODEL_CACHE[variant] = loaded
    _POCKETTTS_MODEL_LOCKS.setdefault(variant, threading.Lock())
    return loaded


def _load_pockettts_state(*, variant: str, voice: str) -> dict:
    cache_key = (variant, voice)
    cached = _POCKETTTS_STATE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    model = _load_pockettts_model(variant=variant)
    state = model.get_state_for_audio_prompt(voice)
    _POCKETTTS_STATE_CACHE[cache_key] = state
    return state


def _run_pockettts(text: str, *, variant: str, voice: str) -> bytes:
    model = _load_pockettts_model(variant=variant)
    model_state = _load_pockettts_state(variant=variant, voice=voice)
    model_lock = _POCKETTTS_MODEL_LOCKS.setdefault(variant, threading.Lock())
    with model_lock:
        audio = model.generate_audio(model_state, text, copy_state=True)
        return _float_audio_to_wav(audio, sample_rate=int(model.sample_rate))


class PocketTTSSynthesizer(BaseSynthesizer):
    audio_mime_type = "audio/wav"

    def __init__(self, *, voice: str, variant: str = POCKETTTS_DEFAULT_VARIANT):
        self.voice = normalize_pockettts_voice(voice)
        self.variant = normalize_pockettts_variant(variant)

    async def synthesize(
        self,
        text: str,
        *,
        preset_name: str | None = None,
        voice_id: str | None = None,
    ) -> bytes:
        if not text.strip():
            return b""
        return await asyncio.to_thread(
            _run_pockettts,
            text,
            variant=self.variant,
            voice=normalize_pockettts_voice(voice_id or self.voice),
        )


async def validate_pockettts_voice(*, voice: str | None = None) -> dict:
    normalized_voice = normalize_pockettts_voice(voice)
    synthesizer = PocketTTSSynthesizer(voice=normalized_voice)
    audio = await synthesizer.synthesize(DEFAULT_SAMPLE_TEXT)
    if not audio:
        raise ValidationError("Pocket TTS voice test returned no audio.")
    return {
        "ok": True,
        "voice": normalized_voice,
        "voice_name": _pockettts_voice_name(normalized_voice),
        "variant": synthesizer.variant,
    }
