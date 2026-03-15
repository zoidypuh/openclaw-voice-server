import asyncio
import sys
import types

from openclaw_voice_server.providers import stt as stt_module
from openclaw_voice_server.providers.tts import list_elevenlabs_voices, validate_edge_voice


def test_validate_stt_selection_runs_each_selected_backend(monkeypatch):
    calls = []

    class FakeTranscriber:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def load(self):
            calls.append(("load", self.kwargs["model"]))

        def transcribe(self, audio_bytes):
            calls.append(("transcribe", len(audio_bytes)))
            return stt_module.TranscriptionResult(text="ok", duration_seconds=1.0)

    monkeypatch.setattr(stt_module, "ensure_python_package", lambda requirement, import_name: {"installed": False})
    monkeypatch.setattr(
        stt_module,
        "BACKEND_CLASSES",
        {"faster-whisper": FakeTranscriber, "whisper": FakeTranscriber},
    )

    result = stt_module.validate_stt_selection(
        {
            "enabled_backends": ["faster-whisper", "whisper"],
            "default_backend": "faster-whisper",
            "language": "en",
            "device": "cpu",
            "compute_type": "int8",
            "backend_models": {"faster-whisper": "large-v3", "whisper": "medium"},
        }
    )

    assert result["ok"] is True
    assert calls[0] == ("load", "large-v3")
    assert calls[2] == ("load", "medium")


def test_validate_edge_voice_checks_listed_voice_and_audio(monkeypatch):
    fake_module = types.SimpleNamespace()

    async def list_voices():
        return [
            {"ShortName": "de-DE-KatjaNeural", "FriendlyName": "Katja", "Locale": "de-DE"},
        ]

    class Communicate:
        def __init__(self, text, voice, rate):
            self.text = text
            self.voice = voice
            self.rate = rate

        async def stream(self):
            yield {"type": "audio", "data": b"abc"}

    fake_module.list_voices = list_voices
    fake_module.Communicate = Communicate

    monkeypatch.setattr("openclaw_voice_server.providers.tts.ensure_python_package", lambda requirement, import_name: {"installed": False})
    monkeypatch.setitem(sys.modules, "edge_tts", fake_module)

    result = asyncio.run(validate_edge_voice(voice="de-DE-KatjaNeural", rate="+0%"))

    assert result["ok"] is True
    assert result["voice_name"] == "Katja"


def test_validate_stt_selection_normalizes_gpu_to_cuda(monkeypatch):
    calls = []

    class FakeTranscriber:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def load(self):
            calls.append(self.kwargs["device"])

        def transcribe(self, audio_bytes):
            return stt_module.TranscriptionResult(text="ok", duration_seconds=1.0)

    monkeypatch.setattr(stt_module, "ensure_python_package", lambda requirement, import_name: {"installed": False})
    monkeypatch.setattr(stt_module, "_ensure_gpu_runtime", lambda backend_id: None)
    monkeypatch.setattr(stt_module, "BACKEND_CLASSES", {"faster-whisper": FakeTranscriber})

    result = stt_module.validate_stt_selection(
        {
            "enabled_backends": ["faster-whisper"],
            "default_backend": "faster-whisper",
            "language": "en",
            "device": "gpu",
            "compute_type": "int8",
            "backend_models": {"faster-whisper": "small"},
        }
    )

    assert result["results"][0]["device"] == "cuda"
    assert calls == ["cuda"]


def test_list_elevenlabs_voices_returns_sorted_voice_names(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "voices": [
                    {"voice_id": "voice-b", "name": "Zulu"},
                    {"voice_id": "voice-a", "name": "Alpha"},
                ]
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            assert headers["xi-api-key"] == "sk-test"
            return FakeResponse()

    monkeypatch.setattr("openclaw_voice_server.providers.tts.httpx.AsyncClient", lambda timeout: FakeClient())

    voices = asyncio.run(list_elevenlabs_voices("sk-test"))

    assert voices == [
        {"voice_id": "voice-a", "name": "Alpha"},
        {"voice_id": "voice-b", "name": "Zulu"},
    ]
