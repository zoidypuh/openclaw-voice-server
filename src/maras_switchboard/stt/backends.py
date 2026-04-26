from __future__ import annotations

import contextlib

import httpx
import numpy as np

from ..catalog import DEFAULT_SAMPLE_TEXT, SUPPORTED_STT_BACKENDS
from ..errors import ValidationError
from ..installer import ensure_python_package
from .base import BaseTranscriber, Transcriber, TranscriptionResult
from .faster_whisper import FasterWhisperTranscriber
from .openai_whisper import OpenAIWhisperTranscriber
from .remote_whisper import RemoteWhisperAPITranscriber, normalize_whisper_endpoint_url
from .xai import XAITranscriber


BACKEND_CLASSES = {
    "faster-whisper": FasterWhisperTranscriber,
    "whisper": OpenAIWhisperTranscriber,
    "xai": XAITranscriber,
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


def _uses_remote_whisper_endpoint(settings: dict) -> bool:
    return bool(normalize_whisper_endpoint_url(settings.get("whisper_endpoint_url", "")))


def _build_transcriber(backend_id: str, settings: dict) -> BaseTranscriber:
    if backend_id == "whisper" and _uses_remote_whisper_endpoint(settings):
        return RemoteWhisperAPITranscriber(
            model=settings.get("backend_models", {}).get(
                backend_id,
                SUPPORTED_STT_BACKENDS[backend_id]["default_model"],
            ),
            language=settings["language"],
            device=normalize_stt_device(settings["device"]),
            compute_type=settings["compute_type"],
            endpoint_url=settings.get("whisper_endpoint_url", ""),
            endpoint_model=settings.get("whisper_endpoint_model", ""),
        )

    transcriber_cls = BACKEND_CLASSES.get(backend_id)
    if transcriber_cls is None:
        raise ValidationError(f"Unsupported STT backend: {backend_id}")
    kwargs = {
        "model": settings.get("backend_models", {}).get(
            backend_id,
            SUPPORTED_STT_BACKENDS[backend_id]["default_model"],
        ),
        "language": settings["language"],
        "device": normalize_stt_device(settings["device"]),
        "compute_type": settings["compute_type"],
    }
    if backend_id == "faster-whisper":
        kwargs["vad_filter"] = bool(settings.get("vad_filter", True))
        kwargs["vad_min_silence_duration_ms"] = int(settings.get("vad_min_silence_duration_ms", 500) or 0)
        kwargs["speech_precheck"] = bool(settings.get("speech_precheck", True))
    if backend_id == "xai":
        kwargs["api_key"] = str(settings.get("xai_api_key") or "").strip()
    return transcriber_cls(**kwargs)


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
    settings["backend_models"] = backend_models
    results = []
    for backend_id in enabled_backends:
        descriptor = SUPPORTED_STT_BACKENDS.get(backend_id)
        if descriptor is None:
            raise ValidationError(f"Unsupported STT backend: {backend_id}")
        model_name = str(backend_models.get(backend_id) or descriptor["default_model"])
        settings["backend_models"][backend_id] = model_name
        install_result = {"installed": False}
        if (
            (descriptor["package"] or descriptor["import_name"])
            and not (backend_id == "whisper" and _uses_remote_whisper_endpoint(settings))
        ):
            install_result = ensure_python_package(descriptor["package"], descriptor["import_name"])
        if settings["device"].startswith("cuda") and not (backend_id == "whisper" and _uses_remote_whisper_endpoint(settings)):
            _ensure_gpu_runtime(backend_id)
        transcriber = _build_transcriber(backend_id, settings)
        try:
            transcriber.load()
            sample_audio = (np.random.randn(16000).astype(np.float32) * 0.01 * 32767.0).astype(np.int16).tobytes()
            transcriber.transcribe(sample_audio)
        finally:
            close = getattr(transcriber, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    close()
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
