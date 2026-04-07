"""Lightweight Silero VAD wrapper for speech detection.

Uses the Silero VAD bundled with faster-whisper to quickly detect
whether an audio buffer contains speech — without running full Whisper
transcription.  Typical latency is <10 ms for a few seconds of audio.
"""
from __future__ import annotations

import logging

import numpy as np

LOGGER = logging.getLogger(__name__)

SAMPLE_RATE = 16000


def audio_contains_speech(
    audio_bytes: bytes,
    *,
    threshold: float = 0.35,
    min_silence_duration_ms: int = 100,
) -> bool:
    """Return True if the PCM16 audio buffer likely contains speech.

    *audio_bytes* must be raw 16-bit signed-integer PCM at 16 kHz mono.
    """
    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) < 512:
        return False

    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(
        threshold=threshold,
        min_speech_duration_ms=0,
        min_silence_duration_ms=min_silence_duration_ms,
    )
    timestamps = get_speech_timestamps(samples, vad_options=options)
    return len(timestamps) > 0
