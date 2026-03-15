from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

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
        self.language = language
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


def _build_transcriber(backend_id: str, settings: dict) -> BaseTranscriber:
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

    backend_models = settings.get("backend_models") or {}
    results = []
    for backend_id in enabled_backends:
        descriptor = SUPPORTED_STT_BACKENDS.get(backend_id)
        if descriptor is None:
            raise ValidationError(f"Unsupported STT backend: {backend_id}")
        model_name = str(backend_models.get(backend_id) or descriptor["default_model"])
        settings["backend_models"][backend_id] = model_name
        install_result = ensure_python_package(descriptor["package"], descriptor["import_name"])
        if settings["device"].startswith("cuda"):
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
            }
        )

    return {
        "ok": True,
        "sample_text": DEFAULT_SAMPLE_TEXT,
        "results": results,
    }


def build_transcriber(settings: dict) -> BaseTranscriber:
    return _build_transcriber(settings["default_backend"], settings)
