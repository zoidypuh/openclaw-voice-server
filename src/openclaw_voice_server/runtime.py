from __future__ import annotations

import asyncio
import contextlib
import logging

from aiohttp import WSMsgType, web

from .config_store import ConfigStore
from .errors import ValidationError
from .gateway import DirectGatewayClient, resolve_voice_session_key
from .providers import build_synthesizer, build_transcriber
from .text import strip_markdown


LOGGER = logging.getLogger(__name__)


class VoiceRuntime:
    def __init__(self, store: ConfigStore):
        self.store = store

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        settings = self.store.load_runtime_settings()
        voice_session_key = resolve_voice_session_key(settings["gateway"]["session_key"])
        ws = web.WebSocketResponse(max_msg_size=10_000_000)
        await ws.prepare(request)

        transcriber = build_transcriber(settings["stt"])
        synthesizer = build_synthesizer(settings["tts"], settings["secrets"])
        gateway = DirectGatewayClient(
            url=settings["gateway"]["url"],
            token=settings["secrets"]["gateway_token"],
            model=settings["gateway"]["model"],
            session_key=voice_session_key,
        )

        busy_lock = asyncio.Lock()
        active_task: asyncio.Task | None = None
        abort_event = asyncio.Event()

        async def process_audio(audio_bytes: bytes) -> None:
            loop = asyncio.get_running_loop()
            await ws.send_json({"status": "thinking"})
            result = await loop.run_in_executor(None, transcriber.transcribe, audio_bytes)
            text = result.text.strip()
            if abort_event.is_set():
                return
            if not text:
                await ws.send_json({"status": "idle"})
                return

            speaking_started = False
            async for chunk in gateway.stream_reply(text, abort_event):
                if abort_event.is_set():
                    return
                clean = strip_markdown(chunk)
                if not clean:
                    continue
                audio = await synthesizer.synthesize(clean)
                if not audio:
                    continue
                if not speaking_started:
                    speaking_started = True
                    await ws.send_json({"status": "speaking"})
                await ws.send_bytes(audio)
            if abort_event.is_set():
                return
            await ws.send_json({"status": "idle"})

        try:
            async for message in ws:
                if message.type == WSMsgType.ERROR:
                    LOGGER.warning("WebSocket error: %s", ws.exception())
                    break
                if message.type == WSMsgType.TEXT:
                    payload = message.json()
                    msg_type = payload.get("type")
                    if msg_type == "ping":
                        await ws.send_json({"type": "pong"})
                    elif msg_type == "interrupt":
                        abort_event.set()
                        if active_task is not None:
                            active_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await active_task
                        active_task = None
                        await ws.send_json({"status": "idle"})
                    continue
                if message.type != WSMsgType.BINARY:
                    continue
                if busy_lock.locked():
                    continue
                if len(message.data) < 1600:
                    continue
                abort_event = asyncio.Event()
                async with busy_lock:
                    active_task = asyncio.create_task(process_audio(message.data))
                    try:
                        await active_task
                    except ValidationError as exc:
                        await ws.send_json({"status": "idle", "error": str(exc)})
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # pragma: no cover - defensive runtime guard
                        LOGGER.exception("Voice processing failed")
                        await ws.send_json({"status": "idle", "error": str(exc)})
                    finally:
                        active_task = None
        finally:
            if active_task is not None:
                active_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await active_task
        return ws
