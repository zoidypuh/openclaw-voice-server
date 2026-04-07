from __future__ import annotations

import logging
import time

import numpy as np

from .base import BaseTranscriber, TranscriptionResult


LOGGER = logging.getLogger(__name__)


class FasterWhisperTranscriber(BaseTranscriber):
    def __init__(
        self,
        *,
        vad_filter: bool = True,
        vad_min_silence_duration_ms: int = 500,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._model = None
        self.vad_filter = bool(vad_filter)
        self.vad_min_silence_duration_ms = max(0, int(vad_min_silence_duration_ms))

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
                beam_size=5,
                condition_on_previous_text=False,
            )[0]
        )
        LOGGER.debug("Loaded faster-whisper model=%s in %.2fs", self.model_name, time.time() - started)

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        self.load()
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        duration = len(samples) / 16000
        transcribe_kwargs = {
            "language": self.language,
            "beam_size": 1,
            "condition_on_previous_text": False,
        }
        if self.vad_filter:
            transcribe_kwargs["vad_filter"] = True
            transcribe_kwargs["vad_parameters"] = {
                "min_silence_duration_ms": self.vad_min_silence_duration_ms,
            }
        segments, _ = self._model.transcribe(samples, **transcribe_kwargs)
        text = " ".join(segment.text for segment in segments).strip()
        return TranscriptionResult(text=text, duration_seconds=duration)
