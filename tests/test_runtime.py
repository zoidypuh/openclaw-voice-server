import asyncio
import base64
import json
import logging
import time
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
        self.send_events = []
        self.auto_accept_playback = False
        self.close_payload = None
        self.closed = False
        FakeWebSocketResponse.created.append(self)

    async def prepare(self, request):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.messages.get()
        if message is self.STOP:
            self.closed = True
            raise StopAsyncIteration
        return message

    async def send_json(self, payload):
        if self.closed:
            raise ConnectionResetError("fake websocket is closed")
        self.json_messages.append(payload)
        self.send_events.append(("json", payload))
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
        if self.closed:
            raise ConnectionResetError("fake websocket is closed")
        self.binary_messages.append(payload)
        self.send_events.append(("bytes", payload))

    async def close(self, *, code=1000, message=b""):
        self.closed = True
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


def test_tts_settings_for_speaker_applies_xai_override():
    settings = {
        "tts": {
            "default_provider": "supertonic",
            "xai_voice_id": "Eve",
            "xai_language": "en",
            "xai_output_codec": "mp3",
            "xai_sample_rate": 44100,
            "xai_bit_rate": 128000,
            "speaker_overrides": {
                "speaker-b": {
                    "provider": "xai",
                    "voice_id": "ara",
                    "language": "fr",
                    "codec": "wav",
                    "sample_rate": 48000,
                    "bit_rate": None,
                }
            },
        }
    }

    resolved = VoiceRuntime._tts_settings_for_speaker(settings, "Speaker B")

    assert resolved["default_provider"] == "xai"
    assert resolved["xai_voice_id"] == "Ara"
    assert resolved["xai_language"] == "fr"
    assert resolved["xai_output_codec"] == "wav"
    assert resolved["xai_sample_rate"] == 48000
    assert resolved["xai_bit_rate"] is None


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


def test_handle_ws_voice_reachable_slash_off_skips_automatic_speech_but_manual_speak_works(monkeypatch):
    FakeWebSocketResponse.created.clear()
    synth_calls = []

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello there", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            synth_calls.append(text)
            return f"audio:{text}".encode("utf-8")

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            yield "Automatic reply."

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
        await ws.messages.put(FakeMessage(WSMsgType.TEXT, payload={"type": "text-input", "text": "/voice-off"}))
        while not any(message.get("type") == "voice-reachable" for message in ws.json_messages):
            await asyncio.sleep(0)
        await ws.messages.put(FakeMessage(WSMsgType.TEXT, payload={"type": "text-input", "text": "hello"}))
        while not any(message.get("text") == "Automatic reply." for message in ws.json_messages):
            await asyncio.sleep(0)

        manual = await runtime.speak_text("manual line")
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return manual, ws

    manual, ws = asyncio.run(scenario())

    assert synth_calls == ["manual line"]
    assert manual["ok"] is True
    assert any(message.get("voice_reachable", {}).get("enabled") is False for message in ws.json_messages)
    assert b"audio:Automatic reply." not in ws.binary_messages
    assert b"audio:manual line" in ws.binary_messages


def test_handle_ws_voice_reachable_skips_tiny_ack_audio(monkeypatch):
    FakeWebSocketResponse.created.clear()
    synth_calls = []

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "hello there", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            synth_calls.append(text)
            return b"audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            yield "OK."

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
        await ws.messages.put(FakeMessage(WSMsgType.TEXT, payload={"type": "text-input", "text": "hello"}))
        while not any(message.get("text") == "OK." for message in ws.json_messages):
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert synth_calls == []
    assert ws.binary_messages == []


def test_voice_reachable_spoken_text_summarizes_long_replies_and_drops_tiny_acks():
    long_reply = (
        "This is a longer operational update that should be spoken as a short summary. "
        "The full detail can stay visible in text while the headphones get the concise version. "
        "Extra diagnostic detail follows here but should not be read in full. "
        "More logs, caveats, and implementation notes can remain on screen without becoming audio spam."
    )

    assert runtime_module._spoken_voice_reachable_text("OK.") == ""
    spoken = runtime_module._spoken_voice_reachable_text(long_reply)

    assert spoken == "Summary: This is a longer operational update that should be spoken as a short summary."


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


def test_speak_text_playback_wait_does_not_block_user_turn_processing(monkeypatch):
    FakeWebSocketResponse.created.clear()
    delivered = []

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "send this tmux turn", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"server-audio"

    class FakeGateway:
        def __init__(self, **kwargs):
            pass

        async def stream_reply(self, text, abort_event):
            raise AssertionError("tmux-only turn should bypass the agent")
            yield ""

    async def fake_send_transcript_to_tmux(text, settings, *, target_id=None):
        delivered.append((text, target_id))
        return {
            "target_id": target_id or "mara",
            "target": "mara:0.0",
            "payload": f"/queue [G] {text}",
            "pane_tail": "",
        }

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "DirectGatewayClient", lambda **kwargs: FakeGateway())
    monkeypatch.setattr(runtime_module, "_send_transcript_to_tmux", fake_send_transcript_to_tmux)
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

        speak_task = asyncio.create_task(runtime.speak_text("terminal says hello"))
        while not ws.binary_messages:
            await asyncio.sleep(0)

        await ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={
                    "type": "turn-commit",
                    "reason": "tmux-release",
                    "speech_ms": 1000,
                    "tmux_only": True,
                    "tmux_target": "mara",
                },
            )
        )
        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"x" * 3200))

        async def wait_for_delivery():
            while len(delivered) < 1:
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_delivery(), timeout=0.5)

        request_id = ws.json_messages[0]["request_id"]
        await ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={"type": "playback-accepted", "request_id": request_id},
            )
        )
        result = await speak_task
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return result, ws

    result, ws = asyncio.run(scenario())

    assert delivered == [("send this tmux turn", "mara")]
    assert result == {
        "ok": True,
        "speaker_name": "",
        "spoken_text": "terminal says hello",
        "preset_name": "",
        "audio_bytes": 12,
    }
    assert ws.binary_messages == [b"server-audio"]


def test_speak_text_uses_reconnected_voice_client_after_tts_synthesis(monkeypatch):
    FakeWebSocketResponse.created.clear()
    release_synthesis = asyncio.Event()

    class SlowSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            await release_synthesis.wait()
            return b"fresh-audio"

    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: SlowSynthesizer())
    monkeypatch.setattr(runtime_module.web, "WebSocketResponse", FakeWebSocketResponse)

    async def start_client(runtime):
        handler_task = asyncio.create_task(runtime.handle_ws(object()))
        while len(FakeWebSocketResponse.created) < 1:
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
        return ws, handler_task

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        stale_ws, stale_handler = await start_client(runtime)
        speak_task = asyncio.create_task(runtime.speak_text("hello after reconnect"))
        await asyncio.sleep(0)

        await stale_ws.messages.put(FakeWebSocketResponse.STOP)
        await stale_handler

        fresh_handler = asyncio.create_task(runtime.handle_ws(object()))
        while len(FakeWebSocketResponse.created) < 2:
            await asyncio.sleep(0)
        fresh_ws = FakeWebSocketResponse.created[-1]
        fresh_ws.auto_accept_playback = True
        await fresh_ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={"type": "client-ready", "features": {"playback_accept": True}},
            )
        )
        await asyncio.sleep(0)

        release_synthesis.set()
        result = await speak_task

        await fresh_ws.messages.put(FakeWebSocketResponse.STOP)
        await fresh_handler
        return result, stale_ws, fresh_ws

    result, stale_ws, fresh_ws = asyncio.run(scenario())

    assert result["ok"] is True
    assert stale_ws.binary_messages == []
    assert fresh_ws.binary_messages == [b"fresh-audio"]


def test_speak_text_serializes_concurrent_playback_pushes(monkeypatch):
    FakeWebSocketResponse.created.clear()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            await asyncio.sleep(0)
            return f"audio:{text}".encode("utf-8")

    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
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

        first, second = await asyncio.gather(
            runtime.speak_text("one"),
            runtime.speak_text("two"),
        )
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return first, second, ws

    first, second, ws = asyncio.run(scenario())

    assert first["ok"] is True
    assert second["ok"] is True
    assert ws.binary_messages == [b"audio:one", b"audio:two"]
    events = [
        event
        for event in ws.send_events
        if event[0] == "bytes" or (event[0] == "json" and event[1].get("status") in {"speaking", "idle"})
    ]
    assert [event[0] for event in events] == ["json", "bytes", "json", "json", "bytes", "json"]
    assert events[0][1]["status"] == "speaking"
    assert events[1] == ("bytes", b"audio:one")
    assert events[2][1]["status"] == "idle"
    assert events[3][1]["status"] == "speaking"
    assert events[4] == ("bytes", b"audio:two")
    assert events[5][1]["status"] == "idle"


def test_speak_text_ignores_stale_client_disconnect_during_new_playback(monkeypatch):
    FakeWebSocketResponse.created.clear()

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            return type("Result", (), {"text": "", "duration_seconds": 0.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            return b"new-client-audio"

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

    async def start_client(runtime):
        handler_task = asyncio.create_task(runtime.handle_ws(object()))
        expected_count = len(FakeWebSocketResponse.created) + 1
        while len(FakeWebSocketResponse.created) < expected_count:
            await asyncio.sleep(0)
        ws = FakeWebSocketResponse.created[-1]
        await ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={"type": "client-ready", "features": {"playback_accept": True}},
            )
        )
        await asyncio.sleep(0)
        return ws, handler_task

    async def scenario():
        runtime = VoiceRuntime(FakeStore())
        old_ws, old_handler_task = await start_client(runtime)
        new_ws, new_handler_task = await start_client(runtime)

        speak_task = asyncio.create_task(runtime.speak_text("hello new client"))
        while not new_ws.binary_messages:
            await asyncio.sleep(0)

        await old_ws.messages.put(FakeWebSocketResponse.STOP)
        await old_handler_task

        assert not speak_task.done()
        request_id = new_ws.json_messages[0]["request_id"]
        await new_ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={"type": "playback-accepted", "request_id": request_id},
            )
        )
        result = await speak_task
        await new_ws.messages.put(FakeWebSocketResponse.STOP)
        await new_handler_task
        return result, old_ws, new_ws

    result, old_ws, new_ws = asyncio.run(scenario())

    assert result["ok"] is True
    assert old_ws.binary_messages == []
    assert new_ws.binary_messages == [b"new-client-audio"]


def test_speak_text_rejects_stale_active_voice_client(monkeypatch):
    FakeWebSocketResponse.created.clear()
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: object())
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
        async with runtime._active_ws_lock:
            runtime._active_ws_client_ready_at = time.time() - runtime_module.PLAYBACK_CLIENT_READY_STALE_SECONDS - 1
            runtime._active_ws_client_last_seen_at = runtime._active_ws_client_ready_at

        status = await runtime.playback_status()
        with pytest.raises(ValidationError, match="Active voice client is stale"):
            await runtime.speak_text("do not synthesize")

        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return status, ws

    status, ws = asyncio.run(scenario())

    assert status["active_voice_client"] is False
    assert status["playback_accept"] is False
    assert status["client_status"] == "stale_websocket"
    assert status["websocket_status"] == "stale"
    assert ws.binary_messages == []


def test_playback_status_reports_audio_locked_client(monkeypatch):
    FakeWebSocketResponse.created.clear()
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: object())
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
                payload={
                    "type": "client-ready",
                    "features": {"playback_accept": True, "playback_unlocked": False},
                },
            )
        )
        await asyncio.sleep(0)
        status = await runtime.playback_status()
        with pytest.raises(ValidationError, match="browser audio is locked"):
            await runtime.speak_text("audio locked")

        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return status, ws

    status, ws = asyncio.run(scenario())

    assert status["active_voice_client"] is True
    assert status["playback_accept"] is False
    assert status["client_status"] == "audio_locked"
    assert status["features"]["playback_unlocked"] is False
    assert ws.binary_messages == []


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
            api_url=None,
            api_key=None,
            api_model=None,
            profile=None,
            use_context_files=True,
            use_memory=True,
            enabled_toolsets=None,
            reply_sanity_check=True,
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


def test_handle_ws_routes_typed_text_without_stt(monkeypatch):
    FakeWebSocketResponse.created.clear()
    agent_calls = []

    class FakeTranscriber:
        def transcribe(self, audio_bytes):
            raise AssertionError("typed text should bypass STT")

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            assert text == "Use Comfy."
            return b"typed-audio"

    class FakeConversationAgent:
        async def stream_reply(self, text, abort_event):
            agent_calls.append(text)
            yield "Use Comfy."

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: FakeTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "build_conversation_agent", lambda settings, **kwargs: FakeConversationAgent())
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
                payload={"type": "text-input", "text": "I mean Comfy, not coffee."},
            )
        )
        while ws.json_messages[-1:] != [{"status": "idle"}]:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert agent_calls == ["I mean Comfy, not coffee."]
    assert {"type": "transcript", "text": "I mean Comfy, not coffee."} in ws.json_messages
    assert {"type": "reply-text", "text": "Use Comfy.", "append": True} in ws.json_messages
    assert ws.binary_messages == [b"typed-audio"]


def test_handle_ws_queues_back_to_back_tmux_audio_turns_without_dropping_slow_first(monkeypatch):
    FakeWebSocketResponse.created.clear()
    delivered = []

    class SlowFirstTranscriber:
        def transcribe(self, audio_bytes):
            if audio_bytes.startswith(b"1"):
                time.sleep(0.05)
                return type(
                    "Result",
                    (),
                    {"text": "long first transcript with task details", "duration_seconds": 3.0},
                )()
            return type("Result", (), {"text": "short second transcript", "duration_seconds": 1.0})()

    class FakeSynthesizer:
        async def synthesize(self, text, *, preset_name=None):
            raise AssertionError("tmux-only turns should bypass TTS")

    class FakeConversationAgent:
        async def stream_reply(self, text, abort_event):
            raise AssertionError("tmux-only turns should bypass agent replies")
            yield ""

    async def fake_send_transcript_to_tmux(text, settings, *, target_id=None):
        delivered.append((text, target_id))
        return {
            "target_id": target_id or "mara",
            "target": "mara:0.0",
            "payload": f"/queue [G] {text}",
            "pane_tail": "",
        }

    monkeypatch.setattr(runtime_module, "build_transcriber", lambda settings: SlowFirstTranscriber())
    monkeypatch.setattr(runtime_module, "build_synthesizer", lambda tts, secrets: FakeSynthesizer())
    monkeypatch.setattr(runtime_module, "build_conversation_agent", lambda settings, **kwargs: FakeConversationAgent())
    monkeypatch.setattr(runtime_module, "_send_transcript_to_tmux", fake_send_transcript_to_tmux)
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
                payload={
                    "type": "turn-commit",
                    "reason": "tmux-release",
                    "speech_ms": 3000,
                    "tmux_only": True,
                    "tmux_target": "mara",
                },
            )
        )
        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"1" * 3200))
        await ws.messages.put(
            FakeMessage(
                WSMsgType.TEXT,
                payload={
                    "type": "turn-commit",
                    "reason": "tmux-release",
                    "speech_ms": 1000,
                    "tmux_only": True,
                    "tmux_target": "mara",
                },
            )
        )
        await ws.messages.put(FakeMessage(WSMsgType.BINARY, data=b"2" * 3200))

        while len(delivered) < 2:
            await asyncio.sleep(0)
        await ws.messages.put(FakeWebSocketResponse.STOP)
        await handler_task
        return ws

    ws = asyncio.run(scenario())

    assert delivered == [
        ("long first transcript with task details", "mara"),
        ("short second transcript", "mara"),
    ]
    assert [
        message
        for message in ws.json_messages
        if isinstance(message, dict) and message.get("type") == "tmux-sent"
    ] == [
        {
            "type": "tmux-sent",
            "text": "/queue [G] long first transcript with task details",
            "target_id": "mara",
            "target": "mara:0.0",
            "payload": "/queue [G] long first transcript with task details",
            "pane_tail": "",
        },
        {
            "type": "tmux-sent",
            "text": "/queue [G] short second transcript",
            "target_id": "mara",
            "target": "mara:0.0",
            "payload": "/queue [G] short second transcript",
            "pane_tail": "",
        },
    ]


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
        assert payload["ok"] is False
        assert payload["error"] == "Timed out waiting for the active voice client to accept playback."
        assert payload["timeout_seconds"] == 0.01
        assert payload["voice_client"]["client_status"] == "no_websocket"

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
    assert payload["ok"] is False
    assert payload["error"] == "Timed out waiting for the active voice client to accept playback."
    assert payload["timeout_seconds"] == 0.01
    assert payload["voice_client"]["client_status"] == "accept_timed_out"
    assert payload["voice_client"]["playback_accept"] is False
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
