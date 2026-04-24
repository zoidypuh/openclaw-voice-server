import asyncio
import sys
import types

from maras_switchboard.stt import backends as stt_module
from maras_switchboard.tts import backends as tts_module
from maras_switchboard.tts import edge as edge_module
from maras_switchboard.tts import elevenlabs as elevenlabs_module
from maras_switchboard.tts import supertonic as supertonic_module
from maras_switchboard.tts.backends import (
    ElevenLabsSynthesizer,
    list_elevenlabs_voices,
    normalize_elevenlabs_preset,
    normalize_supertonic_voice,
    validate_elevenlabs_voice,
    validate_edge_voice,
    validate_supertonic_voice,
)


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

    monkeypatch.setattr(edge_module, "ensure_python_package", lambda requirement, import_name: {"installed": False})
    monkeypatch.setitem(sys.modules, "edge_tts", fake_module)

    result = asyncio.run(validate_edge_voice(voice="de-DE-KatjaNeural", rate="+0%"))

    assert result["ok"] is True
    assert result["voice_name"] == "Katja"


def test_validate_supertonic_voice_uses_external_python_and_returns_audio(monkeypatch, tmp_path):
    python_path = tmp_path / "python"
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    python_path.chmod(0o755)
    calls = []

    def fake_run(
        text,
        *,
        python_path,
        voice,
        language,
        total_steps,
        speed,
    ):
        calls.append(
            {
                "text": text,
                "python_path": python_path,
                "voice": voice,
                "language": language,
                "total_steps": total_steps,
                "speed": speed,
            }
        )
        return b"RIFFdemo"

    monkeypatch.setattr(supertonic_module, "_run_supertonic_synthesis", fake_run)

    result = asyncio.run(
        validate_supertonic_voice(
            python_path=str(python_path),
            voice="m4",
            language="en",
            total_steps="2",
            speed="1.1",
        )
    )

    assert calls == [
        {
            "text": "Mara's Switchboard setup validation.",
            "python_path": str(python_path.resolve()),
            "voice": "M4",
            "language": "en",
            "total_steps": 2,
            "speed": 1.1,
        }
    ]
    assert result == {
        "ok": True,
        "python_path": str(python_path.resolve()),
        "voice": "M4",
        "voice_name": "Male 4",
        "language": "en",
        "language_name": "English",
        "total_steps": 2,
        "speed": 1.1,
    }


def test_normalize_supertonic_voice_uppercases_known_voice():
    assert normalize_supertonic_voice("m4") == "M4"


def test_normalize_supertonic_total_steps_defaults_to_three():
    assert supertonic_module.normalize_supertonic_total_steps(None) == 3


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


def test_validate_stt_selection_uses_remote_whisper_endpoint(monkeypatch):
    install_calls = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, data, files):
            assert url == "http://127.0.0.1:18000/v1/audio/transcriptions"
            assert data["language"] == "en"
            assert "model" not in data
            assert files["file"][0] == "audio.wav"
            return types.SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"text": "ok"},
            )

    class LocalWhisperShouldNotLoad:
        def __init__(self, **kwargs):
            raise AssertionError("local whisper should not load when a remote endpoint is configured")

    monkeypatch.setattr(
        stt_module,
        "ensure_python_package",
        lambda requirement, import_name: install_calls.append((requirement, import_name)) or {"installed": False},
    )
    monkeypatch.setattr(stt_module, "BACKEND_CLASSES", {"whisper": LocalWhisperShouldNotLoad})
    monkeypatch.setattr(stt_module.httpx, "Client", lambda timeout: FakeClient())

    result = stt_module.validate_stt_selection(
        {
            "enabled_backends": ["whisper"],
            "default_backend": "whisper",
            "language": "en",
            "device": "cpu",
            "compute_type": "int8",
            "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            "backend_models": {"whisper": "medium"},
        }
    )

    assert install_calls == []
    assert result["results"][0]["whisper_endpoint_url"] == "http://127.0.0.1:18000/v1/audio/transcriptions"


def test_validate_stt_selection_sends_remote_whisper_override_model(monkeypatch):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, data, files):
            assert data["model"] == "mlx-community/whisper-large-v3-mlx"
            return types.SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"text": "ok"},
            )

    monkeypatch.setattr(stt_module, "ensure_python_package", lambda requirement, import_name: {"installed": False})
    monkeypatch.setattr(stt_module.httpx, "Client", lambda timeout: FakeClient())

    result = stt_module.validate_stt_selection(
        {
            "enabled_backends": ["whisper"],
            "default_backend": "whisper",
            "language": "en",
            "device": "cpu",
            "compute_type": "int8",
            "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            "whisper_endpoint_model": "mlx-community/whisper-large-v3-mlx",
            "backend_models": {"whisper": "medium"},
        }
    )

    assert result["results"][0]["whisper_endpoint_model"] == "mlx-community/whisper-large-v3-mlx"


def test_build_transcriber_uses_local_whisper_when_endpoint_is_blank(monkeypatch):
    class FakeLocalWhisper:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(stt_module, "BACKEND_CLASSES", {"whisper": FakeLocalWhisper})

    transcriber = stt_module.build_transcriber(
        {
            "default_backend": "whisper",
            "language": "en",
            "device": "cpu",
            "compute_type": "int8",
            "whisper_endpoint_url": "",
            "backend_models": {"whisper": "medium"},
        }
    )

    assert isinstance(transcriber, FakeLocalWhisper)


def test_build_transcriber_passes_faster_whisper_vad_settings(monkeypatch):
    captured = {}

    class FakeFasterWhisper:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(stt_module, "BACKEND_CLASSES", {"faster-whisper": FakeFasterWhisper})

    transcriber = stt_module.build_transcriber(
        {
            "default_backend": "faster-whisper",
            "language": "de",
            "device": "cuda",
            "compute_type": "float16",
            "vad_filter": False,
            "vad_min_silence_duration_ms": 120,
            "backend_models": {"faster-whisper": "large-v3"},
        }
    )

    assert isinstance(transcriber, FakeFasterWhisper)
    assert captured["vad_filter"] is False
    assert captured["vad_min_silence_duration_ms"] == 120


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

    monkeypatch.setattr(elevenlabs_module.httpx, "AsyncClient", lambda timeout: FakeClient())

    voices = asyncio.run(list_elevenlabs_voices("sk-test"))

    assert voices == [
        {"voice_id": "voice-a", "name": "Alpha"},
        {"voice_id": "voice-b", "name": "Zulu"},
    ]


def test_auto_language_normalizes_to_none():
    class FakeTranscriber(stt_module.BaseTranscriber):
        def load(self):
            return None

        def transcribe(self, audio_bytes):
            return stt_module.TranscriptionResult(text="ok", duration_seconds=1.0)

    transcriber = FakeTranscriber(model="small", language="auto", device="cpu", compute_type="int8")

    assert transcriber.language is None


def test_elevenlabs_preset_helpers_fall_back_to_natural():
    assert normalize_elevenlabs_preset("EXPRESSIVE") == "expressive"
    assert normalize_elevenlabs_preset("unknown") == "natural"


def test_elevenlabs_synthesize_includes_voice_settings_and_voice_override(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        content = b"mp3"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(elevenlabs_module.httpx, "AsyncClient", lambda timeout: FakeClient())

    audio = asyncio.run(
        ElevenLabsSynthesizer(
            api_key="sk-test",
            voice_id="voice-123",
            model_id="eleven-model",
            default_preset="natural",
        ).synthesize("hello", preset_name="expressive", voice_id="voice-override")
    )

    assert audio == b"mp3"
    assert captured["url"].endswith("/voice-override")
    assert captured["json"]["voice_settings"]["style"] == 0.46


def test_elevenlabs_synthesize_archives_mp3_to_tts_eleven(monkeypatch, tmp_path):
    class FakeResponse:
        status_code = 200
        content = b"fake-mp3-data"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(elevenlabs_module.httpx, "AsyncClient", lambda timeout: FakeClient())

    audio = asyncio.run(
        ElevenLabsSynthesizer(
            api_key="sk-test",
            voice_id="Voice Test/123",
            model_id="eleven-model",
            default_preset="natural",
        ).synthesize("Hello from ElevenLabs")
    )

    archived_files = list((tmp_path / "tts-eleven").glob("*.mp3"))

    assert audio == b"fake-mp3-data"
    assert len(archived_files) == 1
    assert archived_files[0].read_bytes() == b"fake-mp3-data"


def test_validate_elevenlabs_voice_omits_voice_settings(monkeypatch):
    captured = {}

    class FakeVoiceResponse:
        status_code = 200

        def json(self):
            return {"name": "Voice Name"}

    class FakeAudioResponse:
        status_code = 200
        content = b"mp3"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            return FakeVoiceResponse()

        async def post(self, url, headers, json):
            captured["json"] = json
            return FakeAudioResponse()

    monkeypatch.setattr(elevenlabs_module.httpx, "AsyncClient", lambda timeout: FakeClient())

    result = asyncio.run(
        validate_elevenlabs_voice(
            api_key="sk-test",
            voice_id="voice-123",
            model_id="eleven-model",
            preset_name="focused",
        )
    )

    assert result["ok"] is True
    assert "voice_settings" not in captured["json"]
