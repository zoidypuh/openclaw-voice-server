from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable

import websockets

from .config import VoiceServerConfig
from .gateway import OpenClawGatewayClient
from .stt import FasterWhisperTranscriber
from .text import (
    should_cancel_voice_input,
    should_drop_stt_false_positive,
    split_send_phrase,
    strip_markdown,
)
from .tts import ElevenLabsSynthesizer


LOGGER = logging.getLogger(__name__)


def _clear_sync_queue(work_queue: queue.Queue[Any]) -> None:
    while True:
        try:
            work_queue.get_nowait()
        except queue.Empty:
            return


def _close_stream_handle(stream_handle: dict[str, Any]) -> None:
    close_fn = None
    lock = stream_handle.get("lock")
    if lock is not None:
        with lock:
            close_fn = stream_handle.get("close")
    else:
        close_fn = stream_handle.get("close")

    if close_fn is None:
        return
    try:
        close_fn()
    except Exception:
        pass


class VoiceServer:
    def __init__(
        self,
        config: VoiceServerConfig,
        transcriber: FasterWhisperTranscriber,
        tts: ElevenLabsSynthesizer,
        gateway: OpenClawGatewayClient,
    ):
        self.config = config
        self.transcriber = transcriber
        self.tts = tts
        self.gateway = gateway
        self.proactive_queue: queue.Queue[str] = queue.Queue()
        self._interrupt_lock = threading.Lock()
        self._interrupt_handler: Callable[[], None] | None = None
        self._client_command_lock = threading.Lock()
        self._client_command_handler: Callable[[str], None] | None = None

    def register_interrupt_handler(self, fn: Callable[[], None] | None) -> None:
        with self._interrupt_lock:
            self._interrupt_handler = fn

    def trigger_interrupt(self) -> bool:
        with self._interrupt_lock:
            fn = self._interrupt_handler
        if fn is None:
            return False
        try:
            fn()
            return True
        except Exception as exc:
            LOGGER.warning("Interrupt handler failed: %s", exc)
            return False

    def register_client_command_handler(self, fn: Callable[[str], None] | None) -> None:
        with self._client_command_lock:
            self._client_command_handler = fn

    def trigger_client_command(self, command: str) -> bool:
        with self._client_command_lock:
            fn = self._client_command_handler
        if fn is None:
            return False
        try:
            fn(command)
            return True
        except Exception as exc:
            LOGGER.warning("Client command failed (%s): %s", command, exc)
            return False

    def current_session_target(self) -> str:
        return self.config.gateway_session_key or "(stateless)"

    async def generate_tts_async(self, text: str) -> bytes | None:
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self.tts.synthesize, text),
                timeout=self.config.tts_timeout_seconds,
            )
        except asyncio.TimeoutError:
            LOGGER.warning("TTS timeout after %.1fs", self.config.tts_timeout_seconds)
        except Exception as exc:
            LOGGER.warning("TTS failed: %s", exc)
        return None

    async def _handle_ws(self, websocket) -> None:
        LOGGER.info("Client connected")
        ws_loop = asyncio.get_running_loop()
        session_idle = asyncio.Event()
        session_idle.set()
        user_input_idle = asyncio.Event()
        user_input_idle.set()
        incoming_audio: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue()
        send_lock = asyncio.Lock()
        stream_handle = {"lock": threading.Lock(), "close": None}
        turn_state: dict[str, Any] = {"generation": 0, "abort_event": None}
        pending_user_text = ""
        voice_settings = {"require_send_phrase": self.config.require_send_phrase}

        async def send_json(payload: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send(json.dumps(payload))

        async def send_bytes(payload: bytes) -> None:
            async with send_lock:
                await websocket.send(payload)

        async def send_control(command: str) -> None:
            await send_json({"type": "control", "command": command})

        def request_interrupt(notify: bool = False) -> None:
            turn_state["generation"] += 1
            abort_event = turn_state.get("abort_event")
            if abort_event is not None:
                abort_event.set()
            _close_stream_handle(stream_handle)
            _clear_sync_queue(self.proactive_queue)
            while True:
                try:
                    incoming_audio.get_nowait()
                except asyncio.QueueEmpty:
                    break
            if notify:
                user_input_idle.set()
                asyncio.create_task(send_json({"status": "interrupted"}))

        def request_interrupt_threadsafe() -> None:
            ws_loop.call_soon_threadsafe(request_interrupt, True)

        self.register_interrupt_handler(request_interrupt_threadsafe)
        self.register_client_command_handler(
            lambda command: ws_loop.call_soon_threadsafe(
                asyncio.create_task,
                send_control(command),
            )
        )

        async def process_audio(message: bytes, turn_generation: int) -> None:
            nonlocal pending_user_text
            await session_idle.wait()
            if turn_generation != turn_state["generation"]:
                return

            session_idle.clear()
            abort_event = threading.Event()
            turn_state["abort_event"] = abort_event
            loop = asyncio.get_running_loop()
            started = time.time()

            try:
                await send_json({"status": "transcribing"})
                result = await loop.run_in_executor(None, self.transcriber.transcribe, message)
                stt_finished = time.time()

                if abort_event.is_set() or turn_generation != turn_state["generation"]:
                    return

                text = result.text
                if not text or len(text) < 2 or should_drop_stt_false_positive(
                    text,
                    result.duration_seconds,
                    self.config.auto_silence_drop_seconds,
                ):
                    LOGGER.info(
                        "Dropped likely false positive duration=%.1fs bytes=%s",
                        result.duration_seconds,
                        len(message),
                    )
                    await send_json({"status": "idle", "silent": True})
                    return

                if should_cancel_voice_input(text):
                    pending_user_text = ""
                    LOGGER.info("Cancelled held draft with phrase=%r", text)
                    await send_json({"status": "idle", "silent": True})
                    return

                if voice_settings["require_send_phrase"]:
                    final_segment, should_send = split_send_phrase(text, self.config.send_phrase)
                    if not should_send:
                        pending_user_text = " ".join(
                            part for part in (pending_user_text, text.strip()) if part
                        ).strip()
                        await send_json({"status": "held", "text": pending_user_text})
                        return
                    text = " ".join(
                        part for part in (pending_user_text, final_segment.strip()) if part
                    ).strip()
                else:
                    text = " ".join(
                        part for part in (pending_user_text, text.strip()) if part
                    ).strip()
                pending_user_text = ""

                if not text:
                    await send_json({"status": "idle", "silent": True})
                    return

                LOGGER.info("User text: %s", text)
                await send_json({"status": "heard", "text": text})
                await send_json({"status": "thinking"})

                sentence_queue: queue.Queue[dict[str, Any]] = queue.Queue()

                def run_stream() -> None:
                    self.gateway.stream_reply(
                        text,
                        sentence_queue,
                        abort_event=abort_event,
                        stream_handle=stream_handle,
                    )

                llm_thread = threading.Thread(target=run_stream, daemon=True)
                llm_thread.start()

                chunk_texts: list[str] = []
                full_response: str | None = None
                first_audio_at: float | None = None
                interrupted = False

                while True:
                    if abort_event.is_set() or turn_generation != turn_state["generation"]:
                        interrupted = True
                        break

                    try:
                        event = sentence_queue.get_nowait()
                    except queue.Empty:
                        if not llm_thread.is_alive() and sentence_queue.empty():
                            break
                        await asyncio.sleep(0.05)
                        continue

                    event_type = event.get("type")
                    if event_type == "done":
                        break
                    if event_type == "error":
                        LOGGER.error("Gateway error: %s", event["error"])
                        continue
                    if event_type == "diagnostic":
                        LOGGER.warning("Gateway diagnostic: %s", event["message"])
                        continue
                    if event_type == "phase":
                        continue
                    if event_type == "final_text":
                        full_response = event.get("text") or None
                        continue
                    if event_type != "chunk":
                        continue

                    sentence = event["text"]
                    chunk_texts.append(sentence)
                    await send_json({"status": "speaking", "text": sentence})

                    clean = strip_markdown(sentence)
                    if clean:
                        audio = await self.generate_tts_async(clean)
                        if audio is None:
                            continue
                        if abort_event.is_set() or turn_generation != turn_state["generation"]:
                            interrupted = True
                            break
                        await send_bytes(audio)
                        if first_audio_at is None:
                            first_audio_at = time.time()

                llm_thread.join(timeout=1)

                if interrupted:
                    LOGGER.info("Turn interrupted")
                    return

                joined_chunks = "".join(chunk_texts).strip() if chunk_texts else ""
                if joined_chunks:
                    full_response = joined_chunks
                elif not full_response:
                    full_response = "No reply."

                if full_response != "No reply." and not chunk_texts:
                    clean = strip_markdown(full_response)
                    if clean:
                        await send_json({"status": "speaking", "text": full_response})
                        audio = await self.generate_tts_async(clean)
                        if audio is not None:
                            if abort_event.is_set() or turn_generation != turn_state["generation"]:
                                LOGGER.info("Turn interrupted before final audio send")
                                return
                            await send_bytes(audio)
                            if first_audio_at is None:
                                first_audio_at = time.time()

                await send_json({"status": "speaking", "text": full_response})
                await send_json({"status": "idle"})
                LOGGER.info(
                    "Turn finished in %.2fs (stt %.2fs, first_audio=%s)",
                    time.time() - started,
                    stt_finished - started,
                    f"{first_audio_at - started:.2f}s" if first_audio_at is not None else "n/a",
                )
            finally:
                _close_stream_handle(stream_handle)
                if turn_state.get("abort_event") is abort_event:
                    turn_state["abort_event"] = None
                session_idle.set()

        async def audio_worker() -> None:
            while True:
                turn_generation, message = await incoming_audio.get()
                if turn_generation != turn_state["generation"]:
                    continue
                await process_audio(message, turn_generation)

        async def proactive_worker() -> None:
            loop = asyncio.get_running_loop()
            while True:
                text = await loop.run_in_executor(None, self.proactive_queue.get)
                turn_generation = turn_state["generation"]
                await session_idle.wait()
                await user_input_idle.wait()
                if turn_generation != turn_state["generation"]:
                    continue

                session_idle.clear()
                try:
                    if turn_generation != turn_state["generation"]:
                        continue
                    clean = strip_markdown(text)
                    if not clean:
                        continue
                    await send_json({"status": "thinking"})
                    await send_json({"status": "speaking", "text": text})
                    audio = await self.generate_tts_async(clean)
                    if audio is None:
                        await send_json({"status": "idle"})
                        continue
                    if turn_generation != turn_state["generation"]:
                        continue
                    await send_bytes(audio)
                    await send_json({"status": "idle"})
                finally:
                    session_idle.set()

        async def reader_worker() -> None:
            async for message in websocket:
                if isinstance(message, str):
                    data = json.loads(message)
                    msg_type = data.get("type")
                    if msg_type == "ping":
                        await send_json({"type": "pong"})
                    elif msg_type == "settings":
                        if "require_send_phrase" in data:
                            voice_settings["require_send_phrase"] = bool(data["require_send_phrase"])
                            await send_json(
                                {
                                    "status": "config",
                                    "require_send_phrase": voice_settings["require_send_phrase"],
                                }
                            )
                    elif msg_type == "voice_state":
                        if data.get("state") == "speaking":
                            user_input_idle.clear()
                        else:
                            user_input_idle.set()
                    elif msg_type == "interrupt":
                        request_interrupt()
                        user_input_idle.set()
                        await send_json({"status": "interrupted"})
                elif isinstance(message, bytes):
                    if len(message) < 1600:
                        continue
                    await incoming_audio.put((turn_state["generation"], message))

        audio_task = asyncio.create_task(audio_worker())
        proactive_task = asyncio.create_task(proactive_worker())
        reader_task = asyncio.create_task(reader_worker())

        try:
            await reader_task
        except websockets.exceptions.ConnectionClosed:
            LOGGER.info("Client disconnected")
        finally:
            self.register_interrupt_handler(None)
            self.register_client_command_handler(None)
            request_interrupt()
            for task in (audio_task, proactive_task, reader_task):
                task.cancel()
            await asyncio.gather(audio_task, proactive_task, reader_task, return_exceptions=True)

    def _make_http_handler(self):
        server = self
        static_dir = self.config.static_dir

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(static_dir), **kwargs)

            def log_message(self, format: str, *args) -> None:
                LOGGER.debug("HTTP " + format, *args)

            def do_GET(self) -> None:
                if self.path == "/health":
                    body = json.dumps(
                        {
                            "ok": True,
                            "http": {
                                "host": server.config.http_host,
                                "port": server.config.http_port,
                            },
                            "ws": {
                                "host": server.config.ws_host,
                                "port": server.config.ws_port,
                            },
                            "session": server.current_session_target(),
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path == "/":
                    self.path = "/index.html"
                return super().do_GET()

            def do_POST(self) -> None:
                if self.path == "/interrupt":
                    interrupted = server.trigger_interrupt()
                    body = json.dumps({"ok": interrupted, "interrupted": interrupted}).encode("utf-8")
                    self.send_response(200 if interrupted else 409)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path == "/toggle-listen":
                    toggled = server.trigger_client_command("toggle_listen")
                    body = json.dumps({"ok": toggled, "command": "toggle_listen"}).encode("utf-8")
                    self.send_response(200 if toggled else 409)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path != "/say":
                    self.send_error(404)
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    text = str(payload.get("text", "")).strip()
                except Exception:
                    self.send_error(400, "Invalid JSON payload")
                    return

                if not text:
                    self.send_error(400, "Missing text")
                    return

                server.proactive_queue.put(text)
                body = json.dumps({"ok": True, "queued": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def run_http_server(self) -> None:
        httpd = HTTPServer((self.config.http_host, self.config.http_port), self._make_http_handler())
        httpd.serve_forever()

    async def run(self) -> None:
        http_thread = threading.Thread(target=self.run_http_server, daemon=True)
        http_thread.start()

        LOGGER.info("HTTP UI:  http://%s:%s/", self.config.http_host, self.config.http_port)
        LOGGER.info("WebSocket: ws://%s:%s", self.config.ws_host, self.config.ws_port)
        LOGGER.info("Session:   %s", self.current_session_target())
        LOGGER.info("Model:     %s", self.config.gateway_model or "(gateway default)")
        LOGGER.info("STT:       %s on %s", self.config.whisper_model, self.config.whisper_device)
        LOGGER.info("TTS:       ElevenLabs %s", self.config.elevenlabs_model)

        handler = partial(self._handle_ws)
        try:
            async with websockets.serve(
                handler,
                self.config.ws_host,
                self.config.ws_port,
                max_size=10_000_000,
            ):
                await asyncio.Future()
        except asyncio.CancelledError:
            pass

