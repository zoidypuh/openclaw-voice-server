import asyncio
import base64
from aiohttp import WSMsgType
import pytest

from openclaw_voice_server import runtime as runtime_module
from openclaw_voice_server.errors import ValidationError
from openclaw_voice_server.runtime import VoiceRuntime


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
                "model": "openclaw:test",
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

    async def send_bytes(self, payload):
        self.binary_messages.append(payload)

    def exception(self):
        return None


def test_handle_ws_interrupts_active_stream_and_rejects_overlap(monkeypatch):
    FakeWebSocketResponse.created.clear()
    transcribe_calls = 0

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            nonlocal transcribe_calls
            transcribe_calls += 1
            return type("Result", (), {"text": "hello there assistant", "duration_seconds": 1.0})()

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
            return type("Result", (), {"text": "hello there assistant", "duration_seconds": 1.0})()

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
    assert {"status": "speaking"} in ws.json_messages


def test_handle_ws_intercepts_voice_pause_command_before_gateway(monkeypatch):
    FakeWebSocketResponse.created.clear()
    gateway_calls = []

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hey pause"})()

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

    assert gateway_calls == []
    assert {"type": "voice-command", "action": "pause", "heard": "hey pause"} in ws.json_messages
    assert ws.json_messages[-1] == {"status": "idle"}


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
    assert ws.json_messages == [{"status": "thinking"}, {"status": "idle"}]


def test_handle_ws_manual_finish_mode_strips_trailing_language_specific_phrase_before_gateway(monkeypatch):
    FakeWebSocketResponse.created.clear()
    gateway_calls = []

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "sag mir das wetter hey los", "duration_seconds": 1.4})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            gateway_calls.append(text)
            yield "Done."

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

        await ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={"type": "set-capture-mode", "manual_finish": True, "send_phrase": "hey go"},
            )
        )
        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        while not ws.binary_messages:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert gateway_calls == ["sag mir das wetter"]
    assert {"status": "speaking"} in ws.json_messages


def test_handle_ws_manual_finish_mode_keeps_language_specific_short_fallback(monkeypatch):
    FakeWebSocketResponse.created.clear()
    gateway_calls = []

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "sag mir das wetter los", "duration_seconds": 1.4})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            gateway_calls.append(text)
            yield "Done."

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

        await ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={"type": "set-capture-mode", "manual_finish": True, "send_phrase": "hey go"},
            )
        )
        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))
        while not ws.binary_messages:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    asyncio.run(scenario())

    assert gateway_calls == ["sag mir das wetter"]


def test_speak_text_pushes_server_side_audio_to_active_client(monkeypatch):
    FakeWebSocketResponse.created.clear()

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello there assistant", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            assert text == "Hello from OpenClaw voice."
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

        result = await runtime.speak_text("[voice:expressive]Hello from OpenClaw voice.")
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return result, ws

    result, ws = asyncio.run(scenario())

    assert result == {
        "ok": True,
        "spoken_text": "Hello from OpenClaw voice.",
        "preset_name": "expressive",
        "audio_bytes": 5,
    }
    assert ws.json_messages == [{"status": "speaking"}, {"status": "idle"}]
    assert ws.binary_messages == [b"audio"]


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


def test_handle_interrupt_probe_uses_configured_language(monkeypatch):
    captured_settings = {}

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hey stopp"})()

    class FakeRequest:
        can_read_body = True

        async def json(self):
            return {
                "audio_b64": base64.b64encode(b"x" * 3200).decode("ascii"),
            }

    def fake_build_transcriber(settings):
        captured_settings.update(settings)
        return FakeTranscriber()

    monkeypatch.setattr(runtime_module, "build_transcriber", fake_build_transcriber)

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        response = await runtime.handle_interrupt_probe(FakeRequest())
        return response

    response = asyncio.run(scenario())

    assert captured_settings["default_backend"] == "faster-whisper"
    assert captured_settings["language"] == "de"
    assert response.text == '{"ok": true, "matched": true, "action": "interrupt", "heard": "hey stopp", "usable_speech": true}'


def test_handle_interrupt_probe_returns_pause_action(monkeypatch):
    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hey pause"})()

    class FakeRequest:
        can_read_body = True

        async def json(self):
            return {
                "audio_b64": base64.b64encode(b"x" * 3200).decode("ascii"),
            }

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        response = await runtime.handle_interrupt_probe(FakeRequest())
        return response

    response = asyncio.run(scenario())

    assert response.text == '{"ok": true, "matched": false, "action": "pause", "heard": "hey pause", "usable_speech": true}'


def test_handle_interrupt_probe_returns_send_action_for_language_specific_manual_finish_phrase(monkeypatch):
    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "sag mir das wetter hey los"})()

    class FakeRequest:
        can_read_body = True

        async def json(self):
            return {
                "audio_b64": base64.b64encode(b"x" * 3200).decode("ascii"),
                "allow_send_phrase": True,
                "send_phrase": "hey go",
            }

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        response = await runtime.handle_interrupt_probe(FakeRequest())
        return response

    response = asyncio.run(scenario())

    assert response.text == '{"ok": true, "matched": false, "action": "send", "heard": "sag mir das wetter hey los", "usable_speech": true}'
