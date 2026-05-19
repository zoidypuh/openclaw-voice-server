from __future__ import annotations

import io
import wave

import httpx

from ..errors import ValidationError
from .base import BaseTranscriber, TranscriptionResult


DEFAULT_PARAKEET_ENDPOINT_URL = "http://127.0.0.1:18765"


def normalize_parakeet_endpoint_url(endpoint_url: str | None) -> str:
    return str(endpoint_url or "").strip().rstrip("/") or DEFAULT_PARAKEET_ENDPOINT_URL


def _extract_text(payload: dict) -> str:
    text = payload.get("text")
    if isinstance(text, str):
        return text.strip()
    results = payload.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict) and isinstance(first.get("text"), str):
            return first["text"].strip()
    return ""


class ParakeetTranscriber(BaseTranscriber):
    def __init__(self, *, endpoint_url: str = "", **kwargs):
        super().__init__(**kwargs)
        self.endpoint_url = normalize_parakeet_endpoint_url(endpoint_url)
        self._client: httpx.Client | None = None

    def load(self) -> None:
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
        try:
            assert self._client is not None
            response = self._client.post(
                f"{self.endpoint_url}/transcribe?suffix=wav",
                content=self._pcm16_to_wav(audio_bytes),
                headers={"Content-Type": "application/octet-stream"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            detail = ""
            response = getattr(exc, "response", None)
            if response is not None:
                try:
                    payload = response.json()
                    detail = str(payload.get("error") or payload.get("detail") or "").strip()
                except ValueError:
                    detail = response.text.strip()
            if detail:
                raise ValidationError(f"Parakeet request failed: {detail}") from exc
            raise ValidationError(f"Parakeet request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ValidationError("Parakeet returned invalid JSON.") from exc
        if payload.get("ok") is False:
            raise ValidationError(str(payload.get("error") or "Parakeet transcription failed."))

        return TranscriptionResult(text=_extract_text(payload), duration_seconds=duration)
