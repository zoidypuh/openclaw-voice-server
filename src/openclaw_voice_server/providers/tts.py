from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import httpx

from ..catalog import (
    DEFAULT_SAMPLE_TEXT,
    ELEVENLABS_DEFAULT_PRESET,
    SUPPORTED_TTS_PROVIDERS,
)
from ..errors import ValidationError
from ..installer import ensure_python_package


ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"


class BaseSynthesizer(ABC):
    @abstractmethod
    async def synthesize(self, text: str, *, preset_name: str | None = None) -> bytes:
        raise NotImplementedError


class EdgeSynthesizer(BaseSynthesizer):
    def __init__(self, *, voice: str, rate: str):
        self.voice = voice
        self.rate = rate

    async def synthesize(self, text: str, *, preset_name: str | None = None) -> bytes:
        import edge_tts

        communicate = edge_tts.Communicate(text=text, voice=self.voice, rate=self.rate)
        chunks: list[bytes] = []
        async for item in communicate.stream():
            if item.get("type") == "audio":
                chunks.append(item["data"])
        return b"".join(chunks)


class ElevenLabsSynthesizer(BaseSynthesizer):
    def __init__(self, *, api_key: str, voice_id: str, model_id: str, default_preset: str):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.default_preset = normalize_elevenlabs_preset(default_preset)

    async def synthesize(self, text: str, *, preset_name: str | None = None) -> bytes:
        normalize_elevenlabs_preset(preset_name or self.default_preset)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{ELEVENLABS_API_BASE}/text-to-speech/{self.voice_id}",
                headers={
                    "xi-api-key": self.api_key,
                    "accept": "audio/mpeg",
                    "content-type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": self.model_id,
                    "output_format": "mp3_44100_128",
                },
            )
        if response.status_code >= 400:
            raise ValidationError(_http_error_message(response))
        return response.content


def normalize_elevenlabs_preset(preset_name: str | None) -> str:
    normalized = str(preset_name or "").strip().lower()
    if normalized in {"calm", "natural", "expressive", "focused"}:
        return normalized
    return ELEVENLABS_DEFAULT_PRESET


def _http_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"
    detail = payload.get("detail")
    if isinstance(detail, dict):
        message = detail.get("message")
        if message:
            return str(message)
    if isinstance(detail, str):
        return detail
    return payload.get("message") or f"HTTP {response.status_code}"


async def list_edge_voices() -> list[dict]:
    descriptor = SUPPORTED_TTS_PROVIDERS["edge"]
    ensure_python_package(descriptor["package"], descriptor["import_name"])
    import edge_tts

    voices = await edge_tts.list_voices()
    voices.sort(key=lambda item: (item.get("Locale", ""), item.get("ShortName", "")))
    return voices


async def validate_edge_voice(*, voice: str, rate: str) -> dict:
    if not voice:
        raise ValidationError("Choose an Edge voice.")
    voices = await list_edge_voices()
    selected = next((item for item in voices if item.get("ShortName") == voice), None)
    if selected is None:
        raise ValidationError("Selected Edge voice was not found.")
    synthesizer = EdgeSynthesizer(voice=voice, rate=rate)
    audio = await synthesizer.synthesize(DEFAULT_SAMPLE_TEXT)
    if not audio:
        raise ValidationError("Edge voice test returned no audio.")
    return {
        "ok": True,
        "voice": voice,
        "voice_name": selected.get("FriendlyName") or voice,
        "locale": selected.get("Locale"),
    }


async def list_elevenlabs_voices(api_key: str) -> list[dict]:
    if not api_key.strip():
        raise ValidationError("Enter an ElevenLabs API key.")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{ELEVENLABS_API_BASE}/voices",
            headers={"xi-api-key": api_key},
        )
    if response.status_code >= 400:
        raise ValidationError(_http_error_message(response))
    voices = response.json().get("voices", [])
    normalized = [
        {
            "voice_id": str(item.get("voice_id") or "").strip(),
            "name": str(item.get("name") or "").strip() or str(item.get("voice_id") or "").strip(),
        }
        for item in voices
        if str(item.get("voice_id") or "").strip()
    ]
    normalized.sort(key=lambda item: item["name"].lower())
    return normalized


async def validate_elevenlabs_api_key(api_key: str) -> dict:
    voices = await list_elevenlabs_voices(api_key)
    return {"ok": True, "voice_count": len(voices)}


async def validate_elevenlabs_voice(*, api_key: str, voice_id: str, model_id: str, preset_name: str) -> dict:
    if not api_key.strip():
        raise ValidationError("Validate and save the ElevenLabs API key first.")
    if not voice_id.strip():
        raise ValidationError("Enter an ElevenLabs voice ID.")

    async with httpx.AsyncClient(timeout=20) as client:
        voice_response = await client.get(
            f"{ELEVENLABS_API_BASE}/voices/{voice_id}",
            headers={"xi-api-key": api_key},
        )
        if voice_response.status_code >= 400:
            raise ValidationError(_http_error_message(voice_response))
        voice_payload = voice_response.json()

        test_response = await client.post(
            f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": api_key,
                "accept": "audio/mpeg",
                "content-type": "application/json",
            },
            json={
                "text": DEFAULT_SAMPLE_TEXT,
                "model_id": model_id,
                "output_format": "mp3_44100_128",
            },
        )
    if test_response.status_code >= 400:
        raise ValidationError(_http_error_message(test_response))
    if not test_response.content:
        raise ValidationError("ElevenLabs voice test returned no audio.")
    return {
        "ok": True,
        "voice_id": voice_id,
        "voice_name": voice_payload.get("name") or voice_id,
    }


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
    raise ValidationError(f"Unsupported TTS provider: {provider}")
