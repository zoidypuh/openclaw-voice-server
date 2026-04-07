from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import uuid

import httpx

from ..catalog import DEFAULT_SAMPLE_TEXT, ELEVENLABS_DEFAULT_PRESET, ELEVENLABS_PRESETS
from ..errors import ValidationError
from .base import BaseSynthesizer


ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"
ELEVENLABS_ARCHIVE_DIRNAME = "tts-eleven"
LOGGER = logging.getLogger(__name__)


def normalize_elevenlabs_preset(preset_name: str | None) -> str:
    normalized = str(preset_name or "").strip().lower()
    if normalized in {"calm", "natural", "expressive", "focused"}:
        return normalized
    return ELEVENLABS_DEFAULT_PRESET


def _slugify_filename_fragment(value: str, *, fallback: str = "speech", limit: int = 48) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    if not normalized:
        return fallback
    return normalized[:limit].rstrip("-") or fallback


def _archive_elevenlabs_audio(audio_bytes: bytes, *, voice_id: str, text: str) -> Path:
    archive_dir = Path.cwd() / ELEVENLABS_ARCHIVE_DIRNAME
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    voice_slug = _slugify_filename_fragment(voice_id, fallback="voice", limit=24)
    text_slug = _slugify_filename_fragment(text, fallback="speech", limit=48)
    filename = f"{timestamp}-{voice_slug}-{text_slug}-{uuid.uuid4().hex[:8]}.mp3"

    path = archive_dir / filename
    path.write_bytes(audio_bytes)
    LOGGER.info("saved ElevenLabs audio to %s", path)
    return path


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


class ElevenLabsSynthesizer(BaseSynthesizer):
    def __init__(self, *, api_key: str, voice_id: str, model_id: str, default_preset: str):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.default_preset = normalize_elevenlabs_preset(default_preset)

    async def synthesize(
        self,
        text: str,
        *,
        preset_name: str | None = None,
        voice_id: str | None = None,
    ) -> bytes:
        resolved_preset = normalize_elevenlabs_preset(preset_name or self.default_preset)
        resolved_voice_id = str(voice_id or self.voice_id).strip() or self.voice_id
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{ELEVENLABS_API_BASE}/text-to-speech/{resolved_voice_id}",
                headers={
                    "xi-api-key": self.api_key,
                    "accept": "audio/mpeg",
                    "content-type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": self.model_id,
                    "output_format": "mp3_44100_128",
                    "voice_settings": ELEVENLABS_PRESETS[resolved_preset]["voice_settings"],
                },
            )
        if response.status_code >= 400:
            raise ValidationError(_http_error_message(response))
        audio = response.content
        if audio:
            _archive_elevenlabs_audio(audio, voice_id=resolved_voice_id, text=text)
        return audio


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
