from __future__ import annotations

from ..catalog import DEFAULT_SAMPLE_TEXT, SUPPORTED_TTS_PROVIDERS
from ..errors import ValidationError
from ..installer import ensure_python_package
from .base import BaseSynthesizer


class EdgeSynthesizer(BaseSynthesizer):
    def __init__(self, *, voice: str, rate: str):
        self.voice = voice
        self.rate = rate

    async def synthesize(
        self,
        text: str,
        *,
        preset_name: str | None = None,
        voice_id: str | None = None,
    ) -> bytes:
        import edge_tts

        communicate = edge_tts.Communicate(text=text, voice=self.voice, rate=self.rate)
        chunks: list[bytes] = []
        async for item in communicate.stream():
            if item.get("type") == "audio":
                chunks.append(item["data"])
        return b"".join(chunks)


async def list_edge_voices() -> list[dict]:
    descriptor = SUPPORTED_TTS_PROVIDERS["edge"]
    ensure_python_package(descriptor["package"], descriptor["import_name"])
    import edge_tts

    voices = await edge_tts.list_voices()
    voices.sort(key=lambda item: (item.get("Locale", ""), item.get("ShortName", "")))
    return voices


async def validate_edge_voice(*, voice: str, rate: str) -> dict:
    if not voice:
        raise ValidationError("Choose an Edge voice.")
    voices = await list_edge_voices()
    selected = next((item for item in voices if item.get("ShortName") == voice), None)
    if selected is None:
        raise ValidationError("Selected Edge voice was not found.")
    synthesizer = EdgeSynthesizer(voice=voice, rate=rate)
    audio = await synthesizer.synthesize(DEFAULT_SAMPLE_TEXT)
    if not audio:
        raise ValidationError("Edge voice test returned no audio.")
    return {
        "ok": True,
        "voice": voice,
        "voice_name": selected.get("FriendlyName") or voice,
        "locale": selected.get("Locale"),
    }
