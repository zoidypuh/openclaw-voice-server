from __future__ import annotations

import asyncio
from pathlib import Path

from maras_switchboard.errors import ValidationError
from maras_switchboard.installer import ensure_python_package
from maras_switchboard.tts.base import BaseSynthesizer

from .catalog import SUPPORTED_TTS_PROVIDERS
from .vibevoice import _pcm16le_to_wav

import numpy as np


NEUTTS_DEFAULT_BACKBONE = "neuphonic/neutts-nano-german"
NEUTTS_DEFAULT_CODEC = "neuphonic/neucodec"
NEUTTS_DEFAULT_DEVICE = "auto"
NEUTTS_SAMPLE_RATE = 24_000
NEUTTS_SUPPORTED_DEVICES = {"auto", "cpu", "cuda"}
NEUTTS_VOICE_DIRNAME = "neutts-voices"

_NEUTTS_MODEL_CACHE: dict[tuple[str, str, str], object] = {}
_NEUTTS_REF_CACHE: dict[str, tuple[object, str]] = {}


def _ensure_neutts_runtime() -> None:
    descriptor = SUPPORTED_TTS_PROVIDERS["neutts"]
    ensure_python_package(descriptor["package"], descriptor["import_name"])


def neutts_voices_dir() -> Path:
    return (Path.cwd() / NEUTTS_VOICE_DIRNAME).resolve()


def list_local_neutts_voices() -> list[dict[str, str]]:
    directory = neutts_voices_dir()
    if not directory.is_dir():
        return []
    voices: list[dict[str, str]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_dir():
            continue
        wav_files = list(path.glob("*.wav"))
        txt_files = list(path.glob("*.txt"))
        if not wav_files or not txt_files:
            continue
        voice_id = path.name.strip().lower()
        if not voice_id:
            continue
        voices.append(
            {
                "id": voice_id,
                "label": path.name.replace("_", " ").replace("-", " ").title(),
                "wav_path": str(wav_files[0].resolve()),
                "txt_path": str(txt_files[0].resolve()),
            }
        )
    return voices


def resolve_neutts_voice(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    available = {item["id"] for item in list_local_neutts_voices()}
    if normalized not in available:
        raise ValidationError(
            f"NeuTTS voice not found: {normalized}. "
            f"Place a subdirectory with a .wav and .txt file in {neutts_voices_dir()}."
        )
    return normalized


def normalize_neutts_device(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in NEUTTS_SUPPORTED_DEVICES:
        normalized = NEUTTS_DEFAULT_DEVICE

    if normalized == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    if normalized == "cuda":
        try:
            import torch
            if not torch.cuda.is_available():
                raise ValidationError("NeuTTS CUDA was selected, but CUDA is not available.")
        except ImportError:
            raise ValidationError("NeuTTS CUDA was selected, but torch is not installed.")
        return "cuda"

    return normalized


def _load_neutts_model(*, backbone: str, codec: str, device: str):
    cache_key = (backbone, codec, device)
    cached = _NEUTTS_MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    _ensure_neutts_runtime()
    from neutts import NeuTTS

    loaded = NeuTTS(
        backbone_repo=backbone,
        backbone_device=device,
        codec_repo=codec,
        codec_device=device,
    )
    _NEUTTS_MODEL_CACHE[cache_key] = loaded
    return loaded


def _load_reference(tts_model, *, voice: str) -> tuple[object, str]:
    cached = _NEUTTS_REF_CACHE.get(voice)
    if cached is not None:
        return cached

    voices = list_local_neutts_voices()
    match = next((v for v in voices if v["id"] == voice), None)
    if match is None:
        raise ValidationError(f"NeuTTS voice not found: {voice}")

    ref_codes = tts_model.encode_reference(match["wav_path"])
    ref_text = Path(match["txt_path"]).read_text(encoding="utf-8").strip()
    if not ref_text:
        raise ValidationError(f"NeuTTS reference text is empty: {match['txt_path']}")

    _NEUTTS_REF_CACHE[voice] = (ref_codes, ref_text)
    return ref_codes, ref_text


def _float_audio_to_wav(audio: np.ndarray, *, sample_rate: int) -> bytes:
    pcm = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype(np.int16)
    return _pcm16le_to_wav(pcm16.tobytes(), sample_rate=sample_rate)


def _run_neutts(text: str, *, backbone: str, codec: str, device: str, voice: str) -> bytes:
    model = _load_neutts_model(backbone=backbone, codec=codec, device=device)

    if voice:
        ref_codes, ref_text = _load_reference(model, voice=voice)
    else:
        ref_codes, ref_text = None, None

    if ref_codes is not None:
        wav = model.infer(text, ref_codes, ref_text)
    else:
        wav = model.infer(text)

    audio = np.asarray(wav, dtype=np.float32)
    return _float_audio_to_wav(audio, sample_rate=NEUTTS_SAMPLE_RATE)


class NeuTTSSynthesizer(BaseSynthesizer):
    audio_mime_type = "audio/wav"

    def __init__(
        self,
        *,
        backbone: str,
        codec: str,
        device: str,
        voice: str | None = None,
    ):
        self.backbone = backbone.strip() or NEUTTS_DEFAULT_BACKBONE
        self.codec = codec.strip() or NEUTTS_DEFAULT_CODEC
        self.device = normalize_neutts_device(device)
        self.voice = resolve_neutts_voice(voice)

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
            _run_neutts,
            text,
            backbone=self.backbone,
            codec=self.codec,
            device=self.device,
            voice=self.voice,
        )


async def validate_neutts_voice(
    *,
    backbone: str,
    codec: str,
    device: str,
    voice: str | None = None,
) -> dict:
    from .catalog import DEFAULT_SAMPLE_TEXT

    synthesizer = NeuTTSSynthesizer(
        backbone=backbone,
        codec=codec,
        device=device,
        voice=voice,
    )
    audio = await synthesizer.synthesize(DEFAULT_SAMPLE_TEXT)
    if not audio:
        raise ValidationError("NeuTTS voice test returned no audio.")
    return {
        "ok": True,
        "backbone": synthesizer.backbone,
        "codec": synthesizer.codec,
        "device": synthesizer.device,
        "voice": synthesizer.voice or "(default)",
    }
