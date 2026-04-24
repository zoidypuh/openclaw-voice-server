from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    duration_seconds: float


class Transcriber(Protocol):
    def load(self) -> None:
        ...

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        ...


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
