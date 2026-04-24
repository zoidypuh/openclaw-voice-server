from __future__ import annotations

import asyncio
import copy
from pathlib import Path
import pickle

import numpy as np

from maras_switchboard.errors import ValidationError
from maras_switchboard.installer import ensure_python_package
from maras_switchboard.tts.base import BaseSynthesizer

from .catalog import (
    CHATTERBOX_DEFAULT_DEVICE,
    CHATTERBOX_DEFAULT_MODEL,
    CHATTERBOX_DEFAULT_VOICE,
    DEFAULT_SAMPLE_TEXT,
    SUPPORTED_TTS_PROVIDERS,
)
from .vibevoice import _pcm16le_to_wav


CHATTERBOX_SUPPORTED_MODELS = {
    "multilingual": "Chatterbox Multilingual",
    "original": "Chatterbox",
}
CHATTERBOX_SUPPORTED_DEVICES = {"auto", "cpu", "cuda", "mps"}
CHATTERBOX_DEFAULT_LANGUAGE = "en"
_CHATTERBOX_MODEL_CACHE: dict[tuple[str, str], object] = {}
CHATTERBOX_VOICE_DIRNAME = "chatterbox-voices"


def _ensure_chatterbox_runtime() -> None:
    descriptor = SUPPORTED_TTS_PROVIDERS["chatterbox"]
    ensure_python_package(descriptor["package"], descriptor["import_name"])


def chatterbox_voices_dir() -> Path:
    return (Path.cwd() / CHATTERBOX_VOICE_DIRNAME).resolve()


def list_local_chatterbox_voices() -> list[dict[str, str]]:
    directory = chatterbox_voices_dir()
    if not directory.is_dir():
        return []
    voices: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.pt")):
        voice_id = path.stem.strip().lower()
        if not voice_id:
            continue
        voices.append(
            {
                "id": voice_id,
                "label": path.stem.replace("_", " ").replace("-", " ").title(),
                "path": str(path.resolve()),
            }
        )
    return voices


def resolve_chatterbox_voice(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return CHATTERBOX_DEFAULT_VOICE
    if normalized == CHATTERBOX_DEFAULT_VOICE:
        return CHATTERBOX_DEFAULT_VOICE
    available = {item["id"] for item in list_local_chatterbox_voices()}
    if normalized not in available:
        raise ValidationError(f"Chatterbox voice was not found: {normalized}")
    return normalized


def resolve_chatterbox_voice_path(value: str | None) -> str | None:
    voice_id = resolve_chatterbox_voice(value)
    if voice_id == CHATTERBOX_DEFAULT_VOICE:
        return None
    for item in list_local_chatterbox_voices():
        if item["id"] == voice_id:
            return item["path"]
    raise ValidationError(f"Chatterbox voice was not found: {voice_id}")


def normalize_chatterbox_model(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in CHATTERBOX_SUPPORTED_MODELS:
        return normalized
    return CHATTERBOX_DEFAULT_MODEL


def normalize_chatterbox_device(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in CHATTERBOX_SUPPORTED_DEVICES:
        normalized = CHATTERBOX_DEFAULT_DEVICE

    if normalized == "auto":
        _ensure_chatterbox_runtime()
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    if normalized == "cuda":
        _ensure_chatterbox_runtime()
        import torch

        if not torch.cuda.is_available():
            raise ValidationError("Chatterbox CUDA was selected, but CUDA is not available in this environment.")
        return "cuda"

    if normalized == "mps":
        _ensure_chatterbox_runtime()
        import torch

        if not hasattr(torch.backends, "mps") or not torch.backends.mps.is_available():
            raise ValidationError("Chatterbox MPS was selected, but MPS is not available in this environment.")
        return "mps"

    return normalized


def normalize_chatterbox_language(value: str | None, *, model: str) -> str:
    normalized_model = normalize_chatterbox_model(model)
    if normalized_model == "original":
        return "en"

    text = str(value or "").strip().lower()
    if not text or text == "auto":
        return CHATTERBOX_DEFAULT_LANGUAGE
    return text


def _float_audio_to_wav(audio: np.ndarray, *, sample_rate: int) -> bytes:
    pcm = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype(np.int16)
    return _pcm16le_to_wav(pcm16.tobytes(), sample_rate=sample_rate)


def _load_chatterbox_model(*, model: str, device: str):
    cache_key = (model, device)
    cached = _CHATTERBOX_MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    _ensure_chatterbox_runtime()
    if model == "multilingual":
        from chatterbox import ChatterboxMultilingualTTS

        loaded = ChatterboxMultilingualTTS.from_pretrained(device=device)
    else:
        from chatterbox import ChatterboxTTS

        loaded = ChatterboxTTS.from_pretrained(device=device)
    loaded._maras_switchboard_default_conds = copy.deepcopy(getattr(loaded, "conds", None))
    _CHATTERBOX_MODEL_CACHE[cache_key] = loaded
    return loaded


def _load_saved_conditionals(*, voice_path: str, model: str, device: str):
    if model == "multilingual":
        from chatterbox.mtl_tts import Conditionals as TargetConditionals
        from chatterbox.tts import Conditionals as AlternateConditionals
    else:
        from chatterbox.tts import Conditionals as TargetConditionals
        from chatterbox.mtl_tts import Conditionals as AlternateConditionals

    try:
        return TargetConditionals.load(voice_path, map_location=device).to(device)
    except (pickle.UnpicklingError, RuntimeError, ValueError):
        pass

    import torch

    with torch.serialization.safe_globals([TargetConditionals, AlternateConditionals]):
        loaded = torch.load(voice_path, map_location=device, weights_only=False)

    if isinstance(loaded, TargetConditionals):
        return loaded.to(device)
    if isinstance(loaded, AlternateConditionals):
        return TargetConditionals(loaded.t3, loaded.gen).to(device)
    if isinstance(loaded, dict) and "t3" in loaded and "gen" in loaded:
        return TargetConditionals.load(voice_path, map_location=device).to(device)
    raise ValidationError(f"Unsupported Chatterbox voice format: {voice_path}")


def _run_chatterbox(text: str, *, model: str, device: str, language: str, voice: str) -> bytes:
    loaded = _load_chatterbox_model(model=model, device=device)
    voice_path = resolve_chatterbox_voice_path(voice)
    if voice_path:
        loaded.conds = _load_saved_conditionals(voice_path=voice_path, model=model, device=device)
    else:
        loaded.conds = copy.deepcopy(getattr(loaded, "_maras_switchboard_default_conds", None))
    if model == "multilingual":
        wav_tensor = loaded.generate(text, language_id=language)
    else:
        wav_tensor = loaded.generate(text)
    wav = wav_tensor.squeeze(0).detach().cpu().numpy()
    return _float_audio_to_wav(wav, sample_rate=int(getattr(loaded, "sr", 24_000)))


class ChatterboxSynthesizer(BaseSynthesizer):
    audio_mime_type = "audio/wav"

    def __init__(self, *, model: str, device: str, language: str | None = None, voice: str | None = None):
        self.model = normalize_chatterbox_model(model)
        self.device = normalize_chatterbox_device(device)
        self.language = normalize_chatterbox_language(language, model=self.model)
        self.voice = resolve_chatterbox_voice(voice)

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
            _run_chatterbox,
            text,
            model=self.model,
            device=self.device,
            language=self.language,
            voice=self.voice,
        )


async def validate_chatterbox_voice(
    *,
    model: str,
    device: str,
    language: str,
    voice: str | None = None,
) -> dict:
    normalized_model = normalize_chatterbox_model(model)
    normalized_device = normalize_chatterbox_device(device)
    normalized_language = normalize_chatterbox_language(language, model=normalized_model)
    normalized_voice = resolve_chatterbox_voice(voice)
    synthesizer = ChatterboxSynthesizer(
        model=normalized_model,
        device=normalized_device,
        language=normalized_language,
        voice=normalized_voice,
    )
    audio = await synthesizer.synthesize(DEFAULT_SAMPLE_TEXT)
    if not audio:
        raise ValidationError("Chatterbox voice test returned no audio.")
    available_voices = {item["id"]: item["label"] for item in list_local_chatterbox_voices()}
    return {
        "ok": True,
        "model": normalized_model,
        "device": normalized_device,
        "language": normalized_language,
        "voice": normalized_voice,
        "voice_name": available_voices.get(normalized_voice, CHATTERBOX_SUPPORTED_MODELS[normalized_model]),
    }
