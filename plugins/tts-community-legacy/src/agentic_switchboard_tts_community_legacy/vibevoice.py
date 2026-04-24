from __future__ import annotations

import asyncio
import io
import json
from urllib.parse import urlencode, urlparse, urlunparse
import wave

import aiohttp
import httpx

from agentic_switchboard.errors import ValidationError
from agentic_switchboard.tts.base import BaseSynthesizer
from agentic_switchboard.tts.elevenlabs import _http_error_message

from .catalog import DEFAULT_SAMPLE_TEXT


VIBEVOICE_SAMPLE_RATE = 24_000


def normalize_vibevoice_base_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError("Enter the VibeVoice server URL.")
    if "://" not in text:
        text = f"http://{text}"

    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        raise ValidationError("Enter a valid VibeVoice server URL.")

    path = parsed.path.rstrip("/")
    for suffix in ("/config", "/stream"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break

    normalized = urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    return normalized.rstrip("/")


def _vibevoice_http_url(base_url: str, path: str) -> str:
    normalized = normalize_vibevoice_base_url(base_url)
    suffix = path.lstrip("/")
    if not suffix:
        return normalized
    if not normalized:
        return f"/{suffix}"
    return f"{normalized}/{suffix}"


def _vibevoice_ws_url(base_url: str, *, voice: str, text: str) -> str:
    http_url = _vibevoice_http_url(base_url, "stream")
    parsed = urlparse(http_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    query = urlencode({"text": text, "voice": voice})
    return urlunparse((scheme, parsed.netloc, parsed.path, "", query, ""))


def _pcm16le_to_wav(audio_bytes: bytes, *, sample_rate: int) -> bytes:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_bytes)
        return buffer.getvalue()


async def _fetch_vibevoice_config(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(_vibevoice_http_url(base_url, "config"))
    if response.status_code >= 400:
        raise ValidationError(_http_error_message(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValidationError("VibeVoice config endpoint returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValidationError("VibeVoice config endpoint returned an unexpected payload.")
    return payload


def _normalize_vibevoice_voices(payload: dict) -> list[dict]:
    voices = payload.get("voices")
    if not isinstance(voices, list):
        raise ValidationError("VibeVoice config endpoint did not include a voice list.")

    normalized = []
    for item in voices:
        voice_id = str(item or "").strip()
        if not voice_id:
            continue
        normalized.append({"voice_id": voice_id, "name": voice_id})

    normalized.sort(key=lambda item: item["name"].lower())
    return normalized


async def _collect_vibevoice_pcm_audio(*, base_url: str, voice: str, text: str) -> bytes:
    if not text.strip():
        return b""

    ws_url = _vibevoice_ws_url(base_url, voice=voice, text=text)
    timeout = aiohttp.ClientTimeout(total=120, connect=10, sock_read=90)
    chunks: list[bytes] = []
    service_error = ""

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(ws_url) as ws:
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.BINARY:
                        chunks.append(bytes(message.data))
                        continue
                    if message.type == aiohttp.WSMsgType.TEXT:
                        try:
                            payload = message.json(loads=json.loads)
                        except Exception:
                            payload = None
                        if isinstance(payload, dict):
                            event = str(payload.get("event") or "").strip()
                            data = payload.get("data") or {}
                            if event == "backend_busy":
                                service_error = str(data.get("message") or "").strip() or "VibeVoice is busy."
                            elif event == "backend_error":
                                service_error = str(data.get("message") or "").strip() or "VibeVoice failed to synthesize audio."
                        continue
                    if message.type == aiohttp.WSMsgType.ERROR:
                        raise ValidationError("Connection to VibeVoice failed while streaming audio.")
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise ValidationError(f"Could not reach the VibeVoice server: {exc}") from exc

    if not chunks:
        if service_error:
            raise ValidationError(service_error)
        raise ValidationError("VibeVoice returned no audio.")
    return b"".join(chunks)


class VibeVoiceSynthesizer(BaseSynthesizer):
    audio_mime_type = "audio/wav"

    def __init__(self, *, base_url: str, voice: str):
        self.base_url = normalize_vibevoice_base_url(base_url)
        self.voice = voice.strip()

    async def synthesize(
        self,
        text: str,
        *,
        preset_name: str | None = None,
        voice_id: str | None = None,
    ) -> bytes:
        pcm_audio = await _collect_vibevoice_pcm_audio(
            base_url=self.base_url,
            voice=self.voice,
            text=text,
        )
        if not pcm_audio:
            return b""
        return _pcm16le_to_wav(pcm_audio, sample_rate=VIBEVOICE_SAMPLE_RATE)


async def list_vibevoice_voices(base_url: str) -> list[dict]:
    payload = await _fetch_vibevoice_config(base_url)
    return _normalize_vibevoice_voices(payload)


async def validate_vibevoice_voice(*, base_url: str, voice: str) -> dict:
    normalized_base_url = normalize_vibevoice_base_url(base_url)
    payload = await _fetch_vibevoice_config(normalized_base_url)
    voices = _normalize_vibevoice_voices(payload)
    default_voice = str(payload.get("default_voice") or "").strip()
    selected_voice = str(voice or "").strip() or default_voice
    if not selected_voice:
        raise ValidationError("Choose a VibeVoice voice preset.")
    if voices and not any(item["voice_id"] == selected_voice for item in voices):
        raise ValidationError("Selected VibeVoice voice preset was not found.")

    synthesizer = VibeVoiceSynthesizer(base_url=normalized_base_url, voice=selected_voice)
    audio = await synthesizer.synthesize(DEFAULT_SAMPLE_TEXT)
    if not audio:
        raise ValidationError("VibeVoice voice test returned no audio.")
    return {
        "ok": True,
        "base_url": normalized_base_url,
        "voice_id": selected_voice,
        "voice_name": selected_voice,
        "voice_count": len(voices),
    }
