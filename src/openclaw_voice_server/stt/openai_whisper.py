from __future__ import annotations

import logging
import time

import numpy as np

from .base import BaseTranscriber, TranscriptionResult


LOGGER = logging.getLogger(__name__)


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
        LOGGER.debug("Loaded whisper model=%s in %.2fs", self.model_name, time.time() - started)

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
