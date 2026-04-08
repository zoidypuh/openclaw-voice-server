import asyncio
import io
import wave

from agent_switchboard.tts.backends import (
    _pcm16le_to_wav,
    normalize_vibevoice_base_url,
    validate_vibevoice_voice,
)
from agent_switchboard.tts import vibevoice as vibevoice_module


def test_normalize_vibevoice_base_url_rewrites_common_inputs():
    assert normalize_vibevoice_base_url("127.0.0.1:3000") == "http://127.0.0.1:3000"
    assert normalize_vibevoice_base_url("http://127.0.0.1:3000/") == "http://127.0.0.1:3000"
    assert normalize_vibevoice_base_url("http://127.0.0.1:3000/config") == "http://127.0.0.1:3000"
    assert normalize_vibevoice_base_url("https://voice.test/base/stream") == "https://voice.test/base"


def test_pcm16le_to_wav_wraps_mono_audio():
    raw_audio = b"\x00\x00\xff\x7f\x00\x80"

    wrapped = _pcm16le_to_wav(raw_audio, sample_rate=24_000)

    with wave.open(io.BytesIO(wrapped), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24_000
        assert wav_file.readframes(wav_file.getnframes()) == raw_audio


def test_validate_vibevoice_voice_uses_default_voice_when_blank(monkeypatch):
    async def fake_fetch_config(base_url):
        assert base_url == "http://127.0.0.1:3000"
        return {
            "voices": ["en-Carter_man", "en-Emma_woman"],
            "default_voice": "en-Carter_man",
        }

    async def fake_synthesize(self, text, *, preset_name=None):
        assert self.base_url == "http://127.0.0.1:3000"
        assert self.voice == "en-Carter_man"
        assert text
        return b"RIFFdemo"

    monkeypatch.setattr(vibevoice_module, "_fetch_vibevoice_config", fake_fetch_config)
    monkeypatch.setattr(
        vibevoice_module.VibeVoiceSynthesizer,
        "synthesize",
        fake_synthesize,
    )

    result = asyncio.run(validate_vibevoice_voice(base_url="127.0.0.1:3000", voice=""))

    assert result["ok"] is True
    assert result["voice_id"] == "en-Carter_man"
    assert result["voice_count"] == 2
