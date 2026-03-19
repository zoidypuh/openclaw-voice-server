from __future__ import annotations

import io
import logging
import time
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
import numpy as np

from ..catalog import DEFAULT_SAMPLE_TEXT, SUPPORTED_STT_BACKENDS
from ..errors import ValidationError
from ..installer import ensure_python_package


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    duration_seconds: float


class BaseTranscriber(ABC):
    def __init__(self, *, model: str, language: str, device: str, compute_type: str):
        self.model_name = model
        normalized_language = str(language or "").strip().lower()
        self.language = None if normalized_language in {"", "auto"} else normalized_language
        self.device = device
        self.compute_type = compute_type

    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        raise NotImplementedError


class FasterWhisperTranscriber(BaseTranscriber):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        started = time.time()
        self._model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
        )
        warmup_audio = np.random.randn(16000).astype(np.float32) * 0.01
        list(
            self._model.transcribe(
                warmup_audio,
                language=self.language,
                beam_size=1,
                condition_on_previous_text=False,
            )[0]
        )
        LOGGER.info("Loaded faster-whisper model=%s in %.2fs", self.model_name, time.time() - started)

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        self.load()
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        duration = len(samples) / 16000
        segments, _ = self._model.transcribe(
            samples,
            language=self.language,
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text for segment in segments).strip()
        return TranscriptionResult(text=text, duration_seconds=duration)


class OpenAIWhisperTranscriber(BaseTranscriber):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        import whisper

        started = time.time()
        self._model = whisper.load_model(self.model_name, device=self.device)
        warmup_audio = np.random.randn(16000).astype(np.float32) * 0.01
        self._model.transcribe(
            warmup_audio,
            language=self.language,
            fp16=self.device.startswith("cuda"),
            condition_on_previous_text=False,
            verbose=False,
        )
        LOGGER.info("Loaded whisper model=%s in %.2fs", self.model_name, time.time() - started)

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        self.load()
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        duration = len(samples) / 16000
        result = self._model.transcribe(
            samples,
            language=self.language,
            fp16=self.device.startswith("cuda"),
            condition_on_previous_text=False,
            verbose=False,
        )
        text = str(result.get("text", "")).strip()
        return TranscriptionResult(text=text, duration_seconds=duration)


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


BACKEND_CLASSES = {
    "faster-whisper": FasterWhisperTranscriber,
    "whisper": OpenAIWhisperTranscriber,
}


def normalize_stt_device(device: str) -> str:
    normalized = device.strip().lower()
    if normalized == "gpu":
        return "cuda"
    return normalized or "cpu"


def _ensure_gpu_runtime(backend_id: str) -> None:
    if backend_id == "faster-whisper":
        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            raise ValidationError(
                "No CUDA device was detected for Faster Whisper. "
                "Check that NVIDIA drivers and WSL CUDA support are working, then try again."
            )
        return

    if backend_id == "whisper":
        ensure_python_package("torch", "torch")
        import torch

        if not torch.cuda.is_available():
            raise ValidationError(
                "PyTorch could not access CUDA. "
                "Check that NVIDIA drivers and CUDA support are working, then try again."
            )


def normalize_whisper_endpoint_url(endpoint_url: str) -> str:
    return str(endpoint_url or "").strip()


def _uses_remote_whisper_endpoint(settings: dict) -> bool:
    return bool(normalize_whisper_endpoint_url(settings.get("whisper_endpoint_url", "")))


def _build_transcriber(backend_id: str, settings: dict) -> BaseTranscriber:
    if backend_id == "whisper" and _uses_remote_whisper_endpoint(settings):
        return RemoteWhisperAPITranscriber(
            model=settings["backend_models"][backend_id],
            language=settings["language"],
            device=normalize_stt_device(settings["device"]),
            compute_type=settings["compute_type"],
            endpoint_url=settings.get("whisper_endpoint_url", ""),
            endpoint_model=settings.get("whisper_endpoint_model", ""),
        )

    transcriber_cls = BACKEND_CLASSES.get(backend_id)
    if transcriber_cls is None:
        raise ValidationError(f"Unsupported STT backend: {backend_id}")
    return transcriber_cls(
        model=settings["backend_models"][backend_id],
        language=settings["language"],
        device=normalize_stt_device(settings["device"]),
        compute_type=settings["compute_type"],
    )


def validate_stt_selection(settings: dict) -> dict:
    enabled_backends = list(settings.get("enabled_backends") or [])
    default_backend = settings.get("default_backend") or ""
    if not enabled_backends:
        raise ValidationError("Select at least one STT backend.")
    if default_backend not in enabled_backends:
        raise ValidationError("Default STT backend must be one of the selected backends.")
    settings["device"] = normalize_stt_device(str(settings.get("device") or "cpu"))
    settings["whisper_endpoint_url"] = normalize_whisper_endpoint_url(settings.get("whisper_endpoint_url", ""))
    settings["whisper_endpoint_model"] = str(settings.get("whisper_endpoint_model") or "").strip()

    backend_models = settings.get("backend_models") or {}
    results = []
    for backend_id in enabled_backends:
        descriptor = SUPPORTED_STT_BACKENDS.get(backend_id)
        if descriptor is None:
            raise ValidationError(f"Unsupported STT backend: {backend_id}")
        model_name = str(backend_models.get(backend_id) or descriptor["default_model"])
        settings["backend_models"][backend_id] = model_name
        install_result = {"installed": False}
        if not (backend_id == "whisper" and _uses_remote_whisper_endpoint(settings)):
            install_result = ensure_python_package(descriptor["package"], descriptor["import_name"])
        if settings["device"].startswith("cuda") and not (backend_id == "whisper" and _uses_remote_whisper_endpoint(settings)):
            _ensure_gpu_runtime(backend_id)
        transcriber = _build_transcriber(backend_id, settings)
        transcriber.load()
        sample_audio = (np.random.randn(16000).astype(np.float32) * 0.01 * 32767.0).astype(np.int16).tobytes()
        transcriber.transcribe(sample_audio)
        results.append(
            {
                "backend": backend_id,
                "label": descriptor["label"],
                "model": model_name,
                "device": settings["device"],
                "installed_now": bool(install_result["installed"]),
                "whisper_endpoint_url": settings["whisper_endpoint_url"] if backend_id == "whisper" else "",
                "whisper_endpoint_model": settings["whisper_endpoint_model"] if backend_id == "whisper" else "",
            }
        )

    return {
        "ok": True,
        "sample_text": DEFAULT_SAMPLE_TEXT,
        "results": results,
    }


def build_transcriber(settings: dict) -> BaseTranscriber:
    return _build_transcriber(settings["default_backend"], settings)
