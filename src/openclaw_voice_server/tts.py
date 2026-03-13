from __future__ import annotations

from .config import VoiceServerConfig


class ElevenLabsSynthesizer:
    def __init__(self, config: VoiceServerConfig):
        self.config = config
        self._client = None

    def _client_instance(self):
        if self._client is None:
            from elevenlabs import ElevenLabs

            self._client = ElevenLabs(api_key=self.config.elevenlabs_api_key)
        return self._client

    def synthesize(self, text: str) -> bytes:
        client = self._client_instance()
        audio_iter = client.text_to_speech.convert(
            voice_id=self.config.elevenlabs_voice_id,
            text=text,
            model_id=self.config.elevenlabs_model,
            output_format="mp3_44100_128",
        )
        return b"".join(audio_iter)

