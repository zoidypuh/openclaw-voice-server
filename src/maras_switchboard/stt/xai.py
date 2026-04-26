from __future__ import annotations

import io
import os
import wave

import httpx

from ..errors import ValidationError
from .base import BaseTranscriber, TranscriptionResult


DEFAULT_XAI_STT_ENDPOINT_URL = "https://api.x.ai/v1/stt"


def _extract_error_detail(payload: object) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("detail") or error).strip()
        return str(payload.get("detail") or error or payload.get("message") or "").strip()
    return ""


class XAITranscriber(BaseTranscriber):
    def __init__(
        self,
        *,
        api_key: str = "",
        endpoint_url: str = DEFAULT_XAI_STT_ENDPOINT_URL,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.api_key = str(api_key or "").strip()
        self.endpoint_url = str(endpoint_url or DEFAULT_XAI_STT_ENDPOINT_URL).strip()
        self._client: httpx.Client | None = None

    def load(self) -> None:
        if not self.api_key:
            self.api_key = (
                os.environ.get("XAI_API_KEY")
                or os.environ.get("MARAS_SWITCHBOARD_XAI_API_KEY")
                or ""
            ).strip()
        if not self.api_key:
            raise ValidationError("Set XAI_API_KEY to use xAI STT.")
        if self._client is None:
            self._client = httpx.Client(timeout=120)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        try:
            self.close()
        except Exception:
            pass

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
        data = {"format": "true"}
        data["language"] = self.language or "en"

        try:
            assert self._client is not None
            response = self._client.post(
                self.endpoint_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files=files,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            detail = ""
            response = getattr(exc, "response", None)
            if response is not None:
                try:
                    detail = _extract_error_detail(response.json())
                except ValueError:
                    detail = response.text.strip()
            if detail:
                raise ValidationError(f"xAI STT request failed: {detail}") from exc
            raise ValidationError(f"xAI STT request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ValidationError("xAI STT returned invalid JSON.") from exc

        text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
        return TranscriptionResult(text=text, duration_seconds=duration)
