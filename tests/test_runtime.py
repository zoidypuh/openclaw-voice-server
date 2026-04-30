import asyncio
import base64
import json
import logging
from aiohttp import WSMsgType
import pytest

from maras_switchboard import runtime as runtime_module
from maras_switchboard.errors import ValidationError
from maras_switchboard.runtime import VoiceRuntime


class FakeStore:
    def load_runtime_settings(self):
        return {
            "stt": {
                "default_backend": "faster-whisper",
                "language": "de",
                "device": "cuda",
                "compute_type": "float16",
                "backend_models": {"faster-whisper": "large-v3"},
            },
            "tts": {},
            "secrets": {"gateway_token": "token"},
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "maras-switchboard:test",
                "session_key": "voice-main",
            },
        }


class FakeMessage:
    def __init__(self, msg_type, *, data=None, payload=None):
        self.type = msg_type
        self.data = data
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeWebSocketResponse:
    STOP = object()
    created = []

    def __init__(self, *args, **kwargs):
        self.messages = asyncio.Queue()
        self.json_messages = []
        self.binary_messages = []
        self.auto_accept_playback = False
        self.close_payload = None
        FakeWebSocketResponse.created.append(self)

    async def prepare(self, request):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.messages.get()
        if message is self.STOP:
            raise StopAsyncIteration
        return message

    async def send_json(self, payload):
        self.json_messages.append(payload)
        if (
            self.auto_accept_playback
            and payload.get("status") == "speaking"
            and payload.get("source") == "server_speak"
            and payload.get("request_id")
        ):
            await self.messages.put(
                FakeMessage(
                    WSMsgType.TEXT,
                    payload={"type": "playback-accepted", "request_id": payload["request_id"]},
                )
            )

    async def send_bytes(self, payload):
        self.binary_messages.append(payload)

    async def close(self, *, code=1000, message=b""):
        self.close_payload = {"code": code, "message": message}

    def exception(self):
        return None


def test_turn_stt_settings_disable_faster_whisper_vad():
    settings = VoiceRuntime._turn_stt_settings(
        {
            "default_backend": "faster-whisper",
            "language": "de",
            "device": "cuda",
            "compute_type": "float16",
            "backend_models": {"faster-whisper": "large-v3"},
        }
    )

    assert settings["vad_filter"] is False


def test_turn_stt_settings_leave_non_faster_whisper_unchanged():
    settings = VoiceRuntime._turn_stt_settings(
        {
            "default_backend": "whisper",
            "language": "de",
            "device": "cpu",
            "compute_type": "int8",
            "backend_models": {"whisper": "large"},
        }
    )

    assert "vad_filter" not in settings


def test_tts_settings_for_speaker_applies_supertonic_override():
    settings = {
        "tts": {
            "default_provider": "supertonic",
            "supertonic_python_path": "/envs/supertonic/bin/python",
            "supertonic_voice": "M4",
            "supertonic_language": "en",
            "supertonic_total_steps": 2,
            "supertonic_speed": 1.05,
            "speaker_overrides": {
                "speaker-b": {
                    "provider": "supertonic",
                    "voice": "F3",
                    "language": "fr",
                    "total_steps": 3,
                    "speed": 1.2,
                }
            },
        }
    }

    resolved = VoiceRuntime._tts_settings_for_speaker(settings, "Speaker B")

    assert resolved["default_provider"] == "supertonic"
    assert resolved["supertonic_voice"] == "F3"
    assert resolved["supertonic_language"] == "fr"
    assert resolved["supertonic_total_steps"] == 3
    assert resolved["supertonic_speed"] == 1.2


def test_tts_settings_for_speaker_applies_chatterbox_turbo_override():
    settings = {
        "tts": {
            "default_provider": "supertonic",
            "chatterbox_python_path": "/envs/chatterbox/bin/python",
            "chatterbox_voice_prompt_path": "/voices/default.wav",
            "chatterbox_device": "auto",
            "chatterbox_exaggeration": 0.5,
            "chatterbox_temperature": 0.8,
            "chatterbox_top_p": 0.95,
            "chatterbox_top_k": 1000,
            "chatterbox_repetition_penalty": 1.2,
            "speaker_overrides": {
                "speaker-b": {
                    "provider": "chatterbox-turbo",
                    "voice_prompt_path": "/voices/speaker-b.wav",
                    "device": "cpu",
                    "exaggeration": 0.6,
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "top_k": 900,
                    "repetition_penalty": 1.1,
                }
            },
        }
    }

    resolved = VoiceRuntime._tts_settings_for_speaker(settings, "Speaker B")

    assert resolved["default_provider"] == "chatterbox-turbo"
    assert resolved["chatterbox_voice_prompt_path"] == "/voices/speaker-b.wav"
    assert resolved["chatterbox_device"] == "cpu"
    assert resolved["chatterbox_exaggeration"] == 0.6
    assert resolved["chatterbox_temperature"] == 0.7
    assert resolved["chatterbox_top_p"] == 0.9
    assert resolved["chatterbox_top_k"] == 900
    assert resolved["chatterbox_repetition_penalty"] == 1.1


def test_handle_ws_interrupts_active_stream_and_rejects_overlap(monkeypatch):
    FakeWebSocketResponse.created.clear()
    transcribe_calls = 0

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            nonlocal transcribe_calls
            transcribe_calls += 1
            return type("Result", (), {"text": "hello there speaker-a", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"audio"

    started = asyncio.Event()
    aborted = asyncio.Event()

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            started.set()
            try:
                while True:
                    await asyncio.sleep(3600)
                    if False:  # pragma: no cover - keeps this as an async generator
                        yield ""
            finally:
                if abort_event.is_set():
                    aborted.set()

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]

        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        await started.wait()
        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"y" * 3200))
        await ws.messages.put(FakeMessage(WSMsgType.TEXT, payload={"type": "interrupt"}))
        await aborted.wait()
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert transcribe_calls == 1
    assert ws.binary_messages == []
    assert ws.json_messages[0] == {"status": "thinking"}
    assert ws.json_messages[-1] == {"status": "idle"}
    assert {"status": "speaking"} not in ws.json_messages


def test_handle_ws_applies_reply_style_directive_once(monkeypatch):
    FakeWebSocketResponse.created.clear()
    synth_calls = []

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello there speaker-a", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            synth_calls.append((text, preset_name))
            return b"audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            yield "[voice:expressive]First sentence."
            yield " Second sentence."

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]

        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        while len(synth_calls) < 2:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert synth_calls == [
        ("First sentence.", "expressive"),
        ("Second sentence.", "expressive"),
    ]
    assert any(
        message.get("status") == "speaking"
        and message.get("source") == "voice_reply"
        and message.get("request_id")
        for message in ws.json_messages
    )


def test_handle_ws_keeps_short_real_speech_for_gateway(monkeypatch):
    FakeWebSocketResponse.created.clear()
    gateway_calls = []

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello there", "duration_seconds": 0.9})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            gateway_calls.append(text)
            if False:  # pragma: no cover - keeps this as an async generator
                yield ""

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]

        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        while not ws.json_messages:
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert gateway_calls == ["hello there"]
    assert ws.binary_messages == []
    assert ws.json_messages == [
        {"status": "thinking"},
        {"type": "transcript", "text": "hello there"},
        {"type": "reply-text", "text": "", "replace": True},
        {"status": "idle"},
    ]


def test_handle_ws_logs_human_readable_turn_timing(monkeypatch, caplog):
    FakeWebSocketResponse.created.clear()

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello there speaker-a", "duration_seconds": 1.2})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return f"audio:{text}".encode("utf-8")

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            yield "First chunk."
            yield " Second chunk."

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]

        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        while ws.json_messages[-1:] != [{"status": "idle"}]:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    with caplog.at_level(logging.INFO):
        ws = asyncio.run(scenario())

    assert len(ws.binary_messages) == 2
    assert "🎤 hello there speaker-a" in caplog.text
    assert "🔊 First chunk." in caplog.text
    assert "roundtrip" in caplog.text


def test_handle_ws_logs_vad_ignored_noise(monkeypatch, caplog):
    FakeWebSocketResponse.created.clear()

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hmm", "duration_seconds": 0.2})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            if False:  # pragma: no cover - keeps this as an async generator
                yield ""

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)
    monkeypatch.setattr(runtime_module, "should_drop_voice_transcript", lambda *args, **kwargs: True)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]

        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        while ws.json_messages[-1:] != [{"status": "idle"}]:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task

    with caplog.at_level(logging.DEBUG):
        asyncio.run(scenario())

    assert "dropped: hmm" in caplog.text


def test_speak_text_pushes_server_side_audio_to_active_client(monkeypatch):
    FakeWebSocketResponse.created.clear()

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello there speaker-a", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            assert text == "Speaker A says hello."
            assert preset_name == "expressive"
            return b"audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            if False:  # pragma: no cover - keeps this as an async generator
                yield ""

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]
        ws.auto_accept_playback = True
        await ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={"type": "client-ready", "features": {"playback_accept": True}},
            )
        )
        await asyncio.sleep(0)

        result = await runtime.speak_text("[voice:expressive]Speaker A says hello.")
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return result, ws

    result, ws = asyncio.run(scenario())

    assert result == {
        "ok": True,
        "speaker_name": "",
        "spoken_text": "Speaker A says hello.",
        "preset_name": "expressive",
        "audio_bytes": 5,
    }
    assert ws.json_messages[0]["status"] == "speaking"
    assert ws.json_messages[0]["source"] == "server_speak"
    assert ws.json_messages[0]["request_id"]
    assert ws.json_messages[1] == {
        "status": "idle",
        "source": "server_speak",
        "request_id": ws.json_messages[0]["request_id"],
    }
    assert ws.binary_messages == [b"audio"]


def test_speak_text_routes_speaker_tag_to_speaker_specific_provider(monkeypatch):
    FakeWebSocketResponse.created.clear()
    synth_builds = []

    class SpeakerStore(FakeStore):
        def load_runtime_settings(self):
            settings = super().load_runtime_settings()
            settings["tts"] = {
                "default_provider": "supertonic",
                "supertonic_python_path": "/envs/supertonic/bin/python",
                "supertonic_voice": "M4",
                "supertonic_language": "en",
                "supertonic_total_steps": 3,
                "supertonic_speed": 1.05,
                "speaker_overrides": {
                    "speaker-b": {
                        "provider": "elevenlabs",
                        "voice_id": "WtA85syCrJwasGeHGH2p",
                    }
                },
            }
            settings["secrets"]["elevenlabs_api_key"] = "sk-test"
            return settings

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello there speaker-a", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        def __init__(self, provider, voice_id=""):
            self.provider = provider
            self.voice_id = voice_id
            self.audio_mime_type = "audio/mpeg" if provider == "elevenlabs" else "audio/wav"

        async def synthesize(self, text, *, preset_name=None, voice_id=None):
            synth_builds.append(
                {
                    "provider": self.provider,
                    "configured_voice_id": self.voice_id,
                    "text": text,
                    "preset_name": preset_name,
                }
            )
            return b"audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            if False:  # pragma: no cover - keeps this as an async generator
                yield ""

    def fake_build_synthesizer(tts, secrets):
        provider = tts["default_provider"]
        voice_id = tts.get("elevenlabs_voice_id", "")
        return FakeSynthesizer(provider, voice_id=voice_id)

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", fake_build_synthesizer)
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(SpeakerStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]
        ws.auto_accept_playback = True
        await ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={"type": "client-ready", "features": {"playback_accept": True}},
            )
        )
        await asyncio.sleep(0)

        result = await runtime.speak_text("[Speaker-B][voice:expressive]Hello there.")
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return result, ws

    result, ws = asyncio.run(scenario())

    assert result == {
        "ok": True,
        "speaker_name": "speaker-b",
        "spoken_text": "Hello there.",
        "preset_name": "expressive",
        "audio_bytes": 5,
    }
    assert synth_builds[-1]["provider"] == "elevenlabs"
    assert synth_builds[-1]["configured_voice_id"] == "WtA85syCrJwasGeHGH2p"
    assert synth_builds[-1]["text"] == "Hello there."
    assert synth_builds[-1]["preset_name"] == "expressive"
    assert ws.binary_messages == [b"audio"]


def test_handle_ws_routes_speaker_directive_to_override_voice(monkeypatch):
    FakeWebSocketResponse.created.clear()
    synth_calls = []

    class SpeakerStore(FakeStore):
        def load_runtime_settings(self):
            settings = super().load_runtime_settings()
            settings["tts"] = {
                "default_provider": "elevenlabs",
                "elevenlabs_voice_id": "voice-speaker-a",
                "elevenlabs_model": "eleven-model",
                "elevenlabs_preset": "natural",
                "speaker_voice_ids": {"speaker-b": "voice-speaker-b"},
            }
            settings["secrets"]["elevenlabs_api_key"] = "sk-test"
            return settings

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "start debate", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        def __init__(self, voice_id):
            self.voice_id = voice_id

        async def synthesize(self, text, *, preset_name=None, voice_id=None):
            synth_calls.append(
                {
                    "voice_id": self.voice_id,
                    "text": text,
                    "preset_name": preset_name,
                }
            )
            return f"audio:{self.voice_id}".encode("utf-8")

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            yield "[Speaker-B][voice:expressive] Hello there."

    def fake_build_synthesizer(tts, secrets):
        return FakeSynthesizer(tts.get("elevenlabs_voice_id", ""))

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", fake_build_synthesizer)
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(SpeakerStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]
        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        while ws.json_messages[-1:] != [{"status": "idle"}]:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert synth_calls == [
        {
            "voice_id": "voice-speaker-b",
            "text": "Hello there.",
            "preset_name": "expressive",
        }
    ]
    assert ws.binary_messages == [b"audio:voice-speaker-b"]


def test_speak_text_rejects_when_client_cannot_accept_playback(monkeypatch):
    FakeWebSocketResponse.created.clear()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"audio"

    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]
        await ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={"type": "client-ready", "features": {"playback_accept": True}},
            )
        )
        await asyncio.sleep(0)

        async def reject_when_prompted():
            while not ws.json_messages:
                await asyncio.sleep(0)
            request_id = ws.json_messages[0]["request_id"]
            await ws.messages.put(
                FakeMessage(
                    WSMsgType.TEXT,
                    payload={
                        "type": "playback-rejected",
                        "request_id": request_id,
                        "error": "The voice client is paused.",
                    },
                )
            )

        reject_task = asyncio.create_task(reject_when_prompted())
        with pytest.raises(ValidationError, match="The voice client is paused."):
            await runtime.speak_text("hello")
        await reject_task
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task

    asyncio.run(scenario())


def test_handle_ws_reports_initialization_error_and_clears_active_client(monkeypatch):
    FakeWebSocketResponse.created.clear()

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "", "duration_seconds": 0.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"audio"

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    def fail_build_agent(self, settings):
        raise ValidationError("Hermes Agent was not found at /missing")

    monkeypatch.setattr(VoiceRuntime, "_build_conversation_agent", fail_build_agent)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        ws = await runtime.handle_ws(object())
        active_ws = await runtime._get_active_ws()
        return ws, active_ws

    ws, active_ws = asyncio.run(scenario())

    assert active_ws is None
    assert ws.json_messages == [
        {"status": "idle", "error": "Hermes Agent was not found at /missing"}
    ]
    assert ws.close_payload == {
        "code": 1011,
        "message": b"Hermes Agent was not found at /missing",
    }


def test_speak_text_requires_active_voice_client(monkeypatch):
    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"audio"

    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        with pytest.raises(ValidationError, match="No active voice client is connected."):
            await runtime.speak_text("hello")

    asyncio.run(scenario())


def test_speak_text_rejects_when_tts_disabled(monkeypatch):
    class DisabledTtsStore(FakeStore):
        def load_runtime_settings(self):
            settings = super().load_runtime_settings()
            settings["tts"] = {
                "enabled_providers": ["disabled"],
                "default_provider": "disabled",
            }
            return settings

    async def fake_get_active_ws(self):
        return object()

    monkeypatch.setattr(VoiceRuntime, "_get_active_ws", fake_get_active_ws)
    monkeypatch.setattr(
        runtime_module,
        "build_synthesizer",
        lambda tts, secrets: (_ for _ in ()).throw(AssertionError("build_synthesizer should not run")),
    )

    async def scenario():
        runtime = VoiceRuntime(DisabledTtsStore())
        with pytest.raises(ValidationError, match="TTS is disabled for this runtime."):
            await runtime.speak_text("hello")

    asyncio.run(scenario())


def test_handle_ws_uses_hermes_agent_when_selected(monkeypatch):
    FakeWebSocketResponse.created.clear()
    hermes_calls = []

    class HermesStore(FakeStore):
        def load_runtime_settings(self):
            settings = super().load_runtime_settings()
            settings["agent"] = {
                "backend": "hermes",
                "hermes_root": "/tmp/hermes-agent",
                "use_context_files": True,
                "use_memory": True,
                "hermes_session_id": "current-mara-session",
            }
            return settings

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello from mic", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            assert text == "Hermes says hi."
            return b"audio"

    class FakeHermesConversationAgent:
        def __init__(
            self,
            *,
            project_root=None,
            gateway_url=None,
            gateway_token=None,
            gateway_model=None,
            profile=None,
            use_context_files=True,
            use_memory=True,
            enabled_toolsets=None,
            reply_sanity_check=True,
            session_id=None,
            api_model=None,
            delegate_api_model=None,
            delegate_enabled_toolsets=None,
            delegate_use_context_files=True,
            delegate_use_memory=True,
        ):
            assert project_root == "/tmp/hermes-agent"
            assert gateway_url is None
            assert gateway_token is None
            assert gateway_model is None
            assert profile == "voice"
            assert use_context_files is True
            assert use_memory is True
            assert enabled_toolsets == []
            assert reply_sanity_check is True
            assert session_id == "current-mara-session"
            assert api_model is None
            assert delegate_api_model is None
            assert delegate_enabled_toolsets is None
            assert delegate_use_context_files is True
            assert delegate_use_memory is True

        async def stream_reply(self, text, abort_event):
            hermes_calls.append(text)
            yield "Hermes says hi."

    class UnexpectedGateway:
        def __init__(self, **kwargs):
            raise AssertionError("DirectGatewayClient should not be used for Hermes voice chat.")

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "HermesConversationAgent", FakeHermesConversationAgent)
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", UnexpectedGateway)
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(HermesStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]
        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        while ws.json_messages[-1:] != [{"status": "idle"}]:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert hermes_calls == ["hello from mic"]
    assert ws.binary_messages == [b"audio"]


def test_handle_ws_skips_audio_when_tts_disabled(monkeypatch):
    FakeWebSocketResponse.created.clear()
    gateway_calls = []

    class DisabledTtsStore(FakeStore):
        def load_runtime_settings(self):
            settings = super().load_runtime_settings()
            settings["tts"] = {
                "enabled_providers": ["disabled"],
                "default_provider": "disabled",
            }
            return settings

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello from mic", "duration_seconds": 1.0})()

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            gateway_calls.append(text)
            yield "Acknowledged."

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(
        runtime_module,
        "build_synthesizer",
        lambda tts, secrets: (_ for _ in ()).throw(AssertionError("build_synthesizer should not run")),
    )
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(DisabledTtsStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]
        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        while ws.json_messages[-1:] != [{"status": "idle"}]:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert gateway_calls == ["hello from mic"]
    assert ws.binary_messages == []
    assert ws.json_messages == [
        {"status": "thinking"},
        {"type": "transcript", "text": "hello from mic"},
        {"type": "reply-text", "text": "", "replace": True},
        {"type": "reply-text", "text": "Acknowledged.", "append": True},
        {"status": "idle"},
    ]


def test_handle_ws_skips_empty_reply_sentinel_before_tts(monkeypatch):
    FakeWebSocketResponse.created.clear()
    synth_calls = []

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello from mic", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            synth_calls.append((text, preset_name))
            return b"audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            yield "EMPTY"

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]
        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        while ws.json_messages[-1:] != [{"status": "idle"}]:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert synth_calls == []
    assert ws.binary_messages == []
    assert ws.json_messages == [
        {"status": "thinking"},
        {"type": "transcript", "text": "hello from mic"},
        {"type": "reply-text", "text": "", "replace": True},
        {"status": "idle"},
    ]


def test_handle_speak_request_times_out_when_speak_stalls(monkeypatch):
    class FakeRequest:
        can_read_body = True

        async def json(self):
            return {"text": "hello", "timeout_seconds": 0.01}

    async def fake_speak_text(self, text, *, preset_name=None, speaker_name=None):
        await asyncio.sleep(3600)

    monkeypatch.setattr(VoiceRuntime, "speak_text", fake_speak_text)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        response = await runtime.handle_speak_request(FakeRequest())
        assert response.status == 504
        payload = json.loads(response.body.decode("utf-8"))
        assert payload == {
            "ok": False,
            "error": "Timed out waiting for the active voice client to accept playback.",
            "timeout_seconds": 0.01,
        }

    asyncio.run(scenario())


def test_handle_speak_request_sends_idle_when_playback_accept_times_out(monkeypatch):
    FakeWebSocketResponse.created.clear()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"audio"

    class FakeRequest:
        can_read_body = True

        async def json(self):
            return {"text": "hello", "timeout_seconds": 0.01}

    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))

        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]
        await ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={"type": "client-ready", "features": {"playback_accept": True}},
            )
        )
        await asyncio.sleep(0)

        response = await runtime.handle_speak_request(FakeRequest())

        for _ in range(50):
            if len(ws.json_messages) >= 2:
                break
            await asyncio.sleep(0)

        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return response, ws

    response, ws = asyncio.run(scenario())

    assert response.status == 504
    payload = json.loads(response.body.decode("utf-8"))
    assert payload == {
        "ok": False,
        "error": "Timed out waiting for the active voice client to accept playback.",
        "timeout_seconds": 0.01,
    }
    assert ws.json_messages[0]["status"] == "speaking"
    assert ws.json_messages[0]["source"] == "server_speak"
    assert ws.json_messages[1] == {
        "status": "idle",
        "source": "server_speak",
        "request_id": ws.json_messages[0]["request_id"],
    }
    assert ws.binary_messages == [b"audio"]


def test_handle_speak_request_rejects_invalid_timeout():
    class FakeRequest:
        can_read_body = True

        async def json(self):
            return {"text": "hello", "timeout_seconds": 0}

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        with pytest.raises(ValidationError, match="timeout_seconds must be a positive number."):
            await runtime.handle_speak_request(FakeRequest())

    asyncio.run(scenario())


def test_handle_speech_probe_returns_usable_speech(monkeypatch):
    class FakeRequest:
        can_read_body = True

        async def json(self):
            return {
                "audio_b64": base64.b64encode(b"x" * 3200).decode("ascii"),
            }

    monkeypatch.setattr("maras_switchboard.stt.silero_vad.audio_contains_speech", lambda audio: True)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        response = await runtime.handle_speech_probe(FakeRequest())
        return response

    response = asyncio.run(scenario())

    assert json.loads(response.text) == {
        "ok": True,
        "usable_speech": True,
    }


def test_handle_ws_builds_turn_transcriber_with_backend_vad_disabled(monkeypatch):
    FakeWebSocketResponse.created.clear()
    captured_settings = {}

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "", "duration_seconds": 0.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            if False:  # pragma: no cover - keeps this as an async generator
                yield ""

    def fake_build_transcriber(settings):
        captured_settings.update(settings)
        return FakeTranscriber()

    monkeypatch.setattr(runtime_module, "build_transcriber", fake_build_transcriber)
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        handler_task = asyncio.create_task(runtime.handle_ws(object()))
        while not FakeWebSocketResponse.created:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task

    asyncio.run(scenario())

    assert captured_settings["default_backend"] == "faster-whisper"
    assert captured_settings["language"] == "de"
    assert captured_settings["vad_filter"] is False
    assert captured_settings["speech_precheck"] is False


def test_handle_speech_probe_returns_false_without_speech(monkeypatch):
    class FakeRequest:
        can_read_body = True

        async def json(self):
            return {
                "audio_b64": base64.b64encode(b"x" * 3200).decode("ascii"),
            }

    monkeypatch.setattr("maras_switchboard.stt.silero_vad.audio_contains_speech", lambda audio: False)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        response = await runtime.handle_speech_probe(FakeRequest())
        return response

    response = asyncio.run(scenario())

    assert json.loads(response.text) == {
        "ok": True,
        "usable_speech": False,
    }
