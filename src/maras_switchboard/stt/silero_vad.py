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


def _energy_vad_contains_speech(samples: np.ndarray) -> bool:
    """Fallback detector used when faster-whisper's bundled Silero VAD is absent."""
    window_size = 480  # 30 ms at 16 kHz
    if len(samples) < window_size * 2:
        return False
    voiced_windows = 0
    for offset in range(0, len(samples) - window_size + 1, window_size):
        window = samples[offset : offset + window_size]
        rms = float(np.sqrt(np.mean(np.square(window))))
        peak = float(np.max(np.abs(window)))
        if rms >= 0.006 and peak >= 0.025:
            voiced_windows += 1
            if voiced_windows >= 2:
                return True
    return False


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

    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ModuleNotFoundError as exc:
        if str(getattr(exc, "name", "")).split(".")[0] != "faster_whisper":
            raise
        LOGGER.debug("faster-whisper VAD is unavailable; using energy fallback for speech probe")
        return _energy_vad_contains_speech(samples)

    options = VadOptions(
        threshold=threshold,
        min_speech_duration_ms=0,
        min_silence_duration_ms=min_silence_duration_ms,
    )
    timestamps = get_speech_timestamps(samples, vad_options=options)
    return len(timestamps) > 0
