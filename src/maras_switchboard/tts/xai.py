from __future__ import annotations

import httpx

from ..catalog import DEFAULT_SAMPLE_TEXT
from ..errors import ValidationError
from .base import BaseSynthesizer


XAI_TTS_ENDPOINT_URL = "https://api.x.ai/v1/tts"
XAI_TTS_DEFAULT_VOICE = "Eve"
XAI_TTS_DEFAULT_LANGUAGE = "en"
XAI_TTS_DEFAULT_CODEC = "mp3"
XAI_TTS_DEFAULT_SAMPLE_RATE = 44100
XAI_TTS_DEFAULT_BIT_RATE = 128000
XAI_TTS_VOICES = {
    "Eve": "Energetic & upbeat",
    "Ara": "Warm & friendly",
    "Leo": "Authoritative & strong",
    "Rex": "Confident & clear",
    "Sal": "Smooth & balanced",
}
XAI_TTS_OUTPUT_FORMATS = {
    ("mp3", 22050): {"bit_rates": [32000], "mime_type": "audio/mpeg"},
    ("mp3", 24000): {"bit_rates": [128000], "mime_type": "audio/mpeg"},
    ("mp3", 44100): {"bit_rates": [64000, 128000, 192000], "mime_type": "audio/mpeg"},
    ("wav", 16000): {"bit_rates": [None], "mime_type": "audio/wav"},
    ("wav", 44100): {"bit_rates": [None], "mime_type": "audio/wav"},
    ("wav", 48000): {"bit_rates": [None], "mime_type": "audio/wav"},
}


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("detail") or error).strip()
        return str(payload.get("detail") or error or payload.get("message") or f"HTTP {response.status_code}")
    return f"HTTP {response.status_code}"


def normalize_xai_tts_voice(value: str | None) -> str:
    text = str(value or "").strip()
    for voice_id in XAI_TTS_VOICES:
        if text.lower() == voice_id.lower():
            return voice_id
    return XAI_TTS_DEFAULT_VOICE


def normalize_xai_tts_language(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text or XAI_TTS_DEFAULT_LANGUAGE


def normalize_xai_tts_codec(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in {"mp3", "wav"}:
        return text
    return XAI_TTS_DEFAULT_CODEC


def normalize_xai_tts_sample_rate(codec: str, value: object) -> int:
    try:
        sample_rate = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        sample_rate = XAI_TTS_DEFAULT_SAMPLE_RATE
    codec = normalize_xai_tts_codec(codec)
    if (codec, sample_rate) in XAI_TTS_OUTPUT_FORMATS:
        return sample_rate
    return XAI_TTS_DEFAULT_SAMPLE_RATE if codec == "mp3" else 44100


def normalize_xai_tts_bit_rate(codec: str, sample_rate: int, value: object) -> int | None:
    codec = normalize_xai_tts_codec(codec)
    sample_rate = normalize_xai_tts_sample_rate(codec, sample_rate)
    supported = XAI_TTS_OUTPUT_FORMATS[(codec, sample_rate)]["bit_rates"]
    if supported == [None]:
        return None
    try:
        bit_rate = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        bit_rate = XAI_TTS_DEFAULT_BIT_RATE
    if bit_rate in supported:
        return bit_rate
    if codec == "mp3" and sample_rate == 44100:
        return XAI_TTS_DEFAULT_BIT_RATE
    return int(supported[0])


def normalize_xai_tts_output_format(
    *,
    codec: str | None,
    sample_rate: object,
    bit_rate: object,
) -> dict[str, int | str]:
    normalized_codec = normalize_xai_tts_codec(codec)
    normalized_sample_rate = normalize_xai_tts_sample_rate(normalized_codec, sample_rate)
    normalized_bit_rate = normalize_xai_tts_bit_rate(normalized_codec, normalized_sample_rate, bit_rate)
    output_format: dict[str, int | str] = {
        "codec": normalized_codec,
        "sample_rate": normalized_sample_rate,
    }
    if normalized_bit_rate is not None:
        output_format["bit_rate"] = normalized_bit_rate
    return output_format


def xai_tts_mime_type(codec: str, sample_rate: int) -> str:
    normalized_codec = normalize_xai_tts_codec(codec)
    normalized_sample_rate = normalize_xai_tts_sample_rate(normalized_codec, sample_rate)
    return str(XAI_TTS_OUTPUT_FORMATS[(normalized_codec, normalized_sample_rate)]["mime_type"])


class XAITTSSynthesizer(BaseSynthesizer):
    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str,
        language: str,
        codec: str,
        sample_rate: int,
        bit_rate: int | None,
    ):
        self.api_key = str(api_key or "").strip()
        self.voice_id = normalize_xai_tts_voice(voice_id)
        self.language = normalize_xai_tts_language(language)
        self.output_format = normalize_xai_tts_output_format(
            codec=codec,
            sample_rate=sample_rate,
            bit_rate=bit_rate,
        )
        self.audio_mime_type = xai_tts_mime_type(
            str(self.output_format["codec"]),
            int(self.output_format["sample_rate"]),
        )

    async def synthesize(
        self,
        text: str,
        *,
        preset_name: str | None = None,
        voice_id: str | None = None,
    ) -> bytes:
        if not self.api_key:
            raise ValidationError("Set XAI_API_KEY to use xAI TTS.")
        resolved_voice_id = normalize_xai_tts_voice(voice_id or self.voice_id)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                XAI_TTS_ENDPOINT_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "voice_id": resolved_voice_id,
                    "output_format": self.output_format,
                    "language": self.language,
                },
            )
        if response.status_code >= 400:
            raise ValidationError(_extract_error_message(response))
        if not response.content:
            raise ValidationError("xAI TTS returned no audio.")
        return response.content


async def validate_xai_tts_voice(
    *,
    api_key: str,
    voice_id: str,
    language: str,
    codec: str,
    sample_rate: int,
    bit_rate: int | None,
) -> dict:
    synthesizer = XAITTSSynthesizer(
        api_key=api_key,
        voice_id=voice_id,
        language=language,
        codec=codec,
        sample_rate=sample_rate,
        bit_rate=bit_rate,
    )
    audio = await synthesizer.synthesize(DEFAULT_SAMPLE_TEXT)
    return {
        "ok": True,
        "voice_id": synthesizer.voice_id,
        "voice_name": synthesizer.voice_id,
        "language": synthesizer.language,
        "output_format": synthesizer.output_format,
        "audio_bytes": len(audio),
    }
