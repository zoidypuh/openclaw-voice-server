from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass

import numpy as np

from .config import VoiceServerConfig


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    duration_seconds: float


class FasterWhisperTranscriber:
    def __init__(self, config: VoiceServerConfig):
        self.config = config
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return

        from faster_whisper import WhisperModel

        gpu_before = self._read_gpu_memory()
        started = time.time()
        self._model = WhisperModel(
            self.config.whisper_model,
            device=self.config.whisper_device,
            compute_type=self.config.whisper_compute_type,
        )
        loaded = time.time() - started

        warmup_audio = np.random.randn(16000).astype(np.float32) * 0.01
        warmup_started = time.time()
        list(
            self._model.transcribe(
                warmup_audio,
                language=self.config.whisper_language,
                beam_size=1,
            )[0]
        )
        warmup_elapsed = time.time() - warmup_started
        gpu_after = self._read_gpu_memory()

        if gpu_before is not None and gpu_after is not None:
            LOGGER.info(
                "Loaded Whisper model=%s device=%s in %.2fs (warmup %.2fs, gpu_delta=%sMB)",
                self.config.whisper_model,
                self.config.whisper_device,
                loaded,
                warmup_elapsed,
                gpu_after - gpu_before,
            )
        else:
            LOGGER.info(
                "Loaded Whisper model=%s device=%s in %.2fs (warmup %.2fs)",
                self.config.whisper_model,
                self.config.whisper_device,
                loaded,
                warmup_elapsed,
            )

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        if self._model is None:
            self.load()

        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        duration = len(samples) / 16000
        segments, _ = self._model.transcribe(
            samples,
            language=self.config.whisper_language,
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text for segment in segments).strip()
        return TranscriptionResult(text=text, duration_seconds=duration)

    @staticmethod
    def _read_gpu_memory() -> int | None:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        stdout = result.stdout.strip()
        if not stdout:
            return None

        first_line = stdout.splitlines()[0].strip()
        try:
            return int(first_line)
        except ValueError:
            return None

