from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class Synthesizer(Protocol):
    audio_mime_type: str

    async def synthesize(
        self,
        text: str,
        *,
        preset_name: str | None = None,
        voice_id: str | None = None,
    ) -> bytes:
        ...


class BaseSynthesizer(ABC):
    audio_mime_type = "audio/mpeg"

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        preset_name: str | None = None,
        voice_id: str | None = None,
    ) -> bytes:
        raise NotImplementedError
