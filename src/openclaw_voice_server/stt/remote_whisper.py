from __future__ import annotations

import io
import wave

import httpx

from ..errors import ValidationError
from .base import BaseTranscriber, TranscriptionResult


def normalize_whisper_endpoint_url(endpoint_url: str) -> str:
    return str(endpoint_url or "").strip()


class RemoteWhisperAPITranscriber(BaseTranscriber):
    def __init__(self, *, endpoint_url: str, endpoint_model: str = "", **kwargs):
        super().__init__(**kwargs)
        self.endpoint_url = normalize_whisper_endpoint_url(endpoint_url)
        self.endpoint_model = str(endpoint_model or "").strip()

    def load(self) -> None:
        if not self.endpoint_url:
            raise ValidationError("Enter a Whisper endpoint URL or leave it blank to use the local Whisper install.")

    @staticmethod
    def _pcm16_to_wav(audio_bytes: bytes) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(audio_bytes)
        return buffer.getvalue()

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        self.load()
        duration = len(audio_bytes) / 2 / 16000
        files = {
            "file": ("audio.wav", self._pcm16_to_wav(audio_bytes), "audio/wav"),
        }
        data = {}
        if self.endpoint_model:
            data["model"] = self.endpoint_model
        if self.language:
            data["language"] = self.language
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(self.endpoint_url, data=data, files=files)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            detail = ""
            response = getattr(exc, "response", None)
            if response is not None:
                try:
                    payload = response.json()
                    detail = str(payload.get("detail") or payload.get("error") or "").strip()
                except ValueError:
                    detail = response.text.strip()
            if detail:
                raise ValidationError(f"Whisper endpoint request failed: {detail}") from exc
            raise ValidationError(f"Whisper endpoint request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ValidationError("Whisper endpoint returned invalid JSON.") from exc

        text = str(payload.get("text") or "").strip()
        return TranscriptionResult(text=text, duration_seconds=duration)
