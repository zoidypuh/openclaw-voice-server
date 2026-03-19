from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging

from aiohttp import WSMsgType, web

from .config_store import ConfigStore
from .errors import ValidationError
from .gateway import DirectGatewayClient, resolve_voice_session_key
from .providers import build_synthesizer, build_transcriber
from .text import (
    command_send_phrases,
    detect_voice_control_command,
    extract_voice_style_directive,
    has_probable_voice_transcript,
    should_drop_voice_transcript,
    split_send_phrase,
    strip_markdown,
)


LOGGER = logging.getLogger(__name__)


class VoiceRuntime:
    def __init__(self, store: ConfigStore):
        self.store = store
        self._interrupt_transcriber = None
        self._interrupt_transcriber_key: tuple | None = None
        self._interrupt_transcriber_lock = asyncio.Lock()
        self._active_ws: web.WebSocketResponse | None = None
        self._active_ws_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()

    @staticmethod
    def _interrupt_transcriber_config_key(stt_settings: dict) -> tuple:
        return (
            stt_settings.get("default_backend"),
            stt_settings.get("language"),
            stt_settings.get("device"),
            stt_settings.get("compute_type"),
            stt_settings.get("whisper_endpoint_url"),
            stt_settings.get("whisper_endpoint_model"),
            tuple(sorted((stt_settings.get("backend_models") or {}).items())),
        )

    @staticmethod
    def _interrupt_stt_settings(stt_settings: dict) -> dict:
        return dict(stt_settings)

    async def _get_interrupt_transcriber(self):
        settings = self._interrupt_stt_settings(self.store.load_runtime_settings()["stt"])
        config_key = self._interrupt_transcriber_config_key(settings)
        async with self._interrupt_transcriber_lock:
            if self._interrupt_transcriber is None or self._interrupt_transcriber_key != config_key:
                self._interrupt_transcriber = build_transcriber(settings)
                self._interrupt_transcriber_key = config_key
            return self._interrupt_transcriber

    async def handle_interrupt_probe(self, request: web.Request) -> web.Response:
        payload = await request.json() if request.can_read_body else {}
        audio_b64 = str(payload.get("audio_b64") or "").strip()
        allow_send_phrase = bool(payload.get("allow_send_phrase"))
        if not audio_b64:
            raise ValidationError("Missing interrupt probe audio.")
        try:
            audio_bytes = base64.b64decode(audio_b64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValidationError("Interrupt probe audio was invalid.") from exc
        if len(audio_bytes) < 1600:
            return web.json_response({"ok": True, "matched": False, "heard": ""})

        transcriber = await self._get_interrupt_transcriber()
        command_language = self.store.load_runtime_settings()["stt"].get("language", "")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, transcriber.transcribe, audio_bytes)
        text = result.text.strip()
        duration = float(getattr(result, "duration_seconds", 0.0) or 0.0)
        action = detect_voice_control_command(text, language=command_language)
        if not action and allow_send_phrase:
            for phrase in command_send_phrases(command_language):
                _, matched_send_phrase = split_send_phrase(text, phrase)
                if matched_send_phrase:
                    action = "send"
                    break
        usable_speech = bool(action) or has_probable_voice_transcript(text, duration, min_duration=0.2)
        return web.json_response(
            {
                "ok": True,
                "matched": action == "interrupt",
                "action": action or "",
                "heard": text,
                "usable_speech": usable_speech,
            }
        )

    async def _set_active_ws(self, ws: web.WebSocketResponse | None) -> None:
        async with self._active_ws_lock:
            self._active_ws = ws

    async def _clear_active_ws(self, ws: web.WebSocketResponse) -> None:
        async with self._active_ws_lock:
            if self._active_ws is ws:
                self._active_ws = None

    async def _get_active_ws(self) -> web.WebSocketResponse | None:
        async with self._active_ws_lock:
            return self._active_ws

    async def speak_text(self, text: str, *, preset_name: str | None = None) -> dict[str, object]:
        ws = await self._get_active_ws()
        if ws is None:
            raise ValidationError("No active voice client is connected.")

        raw_text = str(text).strip()
        if not raw_text:
            raise ValidationError("Missing text to speak.")

        reply_style = preset_name
        detected_style, remaining_text, waiting_for_more = extract_voice_style_directive(raw_text)
        if detected_style:
            reply_style = detected_style
            raw_text = remaining_text
        elif not waiting_for_more:
            raw_text = remaining_text
        spoken_text = strip_markdown(raw_text).strip()
        if not spoken_text:
            raise ValidationError("Text to speak was empty after normalization.")

        settings = self.store.load_runtime_settings()
        synthesizer = build_synthesizer(settings["tts"], settings["secrets"])
        async with self._turn_lock:
            audio = await synthesizer.synthesize(spoken_text, preset_name=reply_style)
            if not audio:
                raise ValidationError("Speech synthesis returned no audio.")
            try:
                await ws.send_json({"status": "speaking"})
                await ws.send_bytes(audio)
                await ws.send_json({"status": "idle"})
            except ConnectionResetError as exc:
                await self._clear_active_ws(ws)
                raise ValidationError("The active voice client disconnected before playback.") from exc
        return {
            "ok": True,
            "spoken_text": spoken_text,
            "preset_name": reply_style or "",
            "audio_bytes": len(audio),
        }

    async def handle_speak_request(self, request: web.Request) -> web.Response:
        payload = await request.json() if request.can_read_body else {}
        result = await self.speak_text(
            str(payload.get("text") or ""),
            preset_name=str(payload.get("preset_name") or "").strip() or None,
        )
        return web.json_response(result)

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        settings = self.store.load_runtime_settings()
        voice_session_key = resolve_voice_session_key(settings["gateway"]["session_key"])
        ws = web.WebSocketResponse(max_msg_size=10_000_000)
        await ws.prepare(request)
        await self._set_active_ws(ws)

        transcriber = build_transcriber(settings["stt"])
        synthesizer = build_synthesizer(settings["tts"], settings["secrets"])
        gateway = DirectGatewayClient(
            url=settings["gateway"]["url"],
            token=settings["secrets"]["gateway_token"],
            model=settings["gateway"]["model"],
            session_key=voice_session_key,
        )
        command_language = settings["stt"].get("language", "")

        active_task: asyncio.Task | None = None
        abort_event = asyncio.Event()
        manual_finish_enabled = True
        manual_finish_phrases = command_send_phrases(command_language)

        async def process_audio(audio_bytes: bytes, task_abort_event: asyncio.Event) -> None:
            nonlocal manual_finish_enabled, manual_finish_phrases
            loop = asyncio.get_running_loop()
            await ws.send_json({"status": "thinking"})
            result = await loop.run_in_executor(None, transcriber.transcribe, audio_bytes)
            text = result.text.strip()
            duration = float(getattr(result, "duration_seconds", 0.0) or 0.0)
            if task_abort_event.is_set():
                return
            if not text:
                await ws.send_json({"status": "idle"})
                return
            if manual_finish_enabled:
                for send_phrase in manual_finish_phrases:
                    next_text, matched_send_phrase = split_send_phrase(text, send_phrase)
                    if not matched_send_phrase:
                        continue
                    text = next_text.strip()
                    if not text:
                        await ws.send_json({"status": "idle"})
                        return
                    break
            action = detect_voice_control_command(text, language=command_language)
            if action:
                await ws.send_json({"type": "voice-command", "action": action, "heard": text})
                await ws.send_json({"status": "idle"})
                return
            audio_settings = settings.get("audio", {})
            min_duration = max(float(audio_settings.get("min_speech_ms", 500) or 500) / 1000.0, 0.0)
            if should_drop_voice_transcript(text, duration, min_duration=min_duration, command_language=command_language):
                LOGGER.info("Dropping short/noisy transcript: %r (duration=%.3fs)", text, duration)
                await ws.send_json({"status": "idle"})
                return

            speaking_started = False
            reply_style = settings["tts"].get("elevenlabs_preset", "natural")
            intro_buffer = ""
            style_resolved = False
            async for chunk in gateway.stream_reply(text, task_abort_event):
                if task_abort_event.is_set():
                    return
                clean = strip_markdown(chunk)
                if not clean:
                    continue
                if not style_resolved:
                    intro_buffer += clean
                    detected_style, remaining_text, waiting_for_more = extract_voice_style_directive(intro_buffer)
                    if waiting_for_more:
                        continue
                    if detected_style:
                        reply_style = detected_style
                    clean = remaining_text
                    intro_buffer = ""
                    style_resolved = True
                if not clean.strip():
                    continue
                audio = await synthesizer.synthesize(clean, preset_name=reply_style)
                if not audio:
                    continue
                if not speaking_started:
                    speaking_started = True
                    await ws.send_json({"status": "speaking"})
                await ws.send_bytes(audio)
            if intro_buffer and not task_abort_event.is_set():
                audio = await synthesizer.synthesize(intro_buffer, preset_name=reply_style)
                if audio:
                    if not speaking_started:
                        speaking_started = True
                        await ws.send_json({"status": "speaking"})
                    await ws.send_bytes(audio)
            if task_abort_event.is_set():
                return
            await ws.send_json({"status": "idle"})

        async def cancel_active_task(*, send_idle: bool) -> None:
            nonlocal active_task
            abort_event.set()
            if active_task is not None:
                active_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await active_task
                active_task = None
            if send_idle:
                await ws.send_json({"status": "idle"})

        async def run_audio_task(audio_bytes: bytes, task_abort_event: asyncio.Event) -> None:
            nonlocal active_task
            async with self._turn_lock:
                try:
                    await process_audio(audio_bytes, task_abort_event)
                except ValidationError as exc:
                    await ws.send_json({"status": "idle", "error": str(exc)})
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pragma: no cover - defensive runtime guard
                    LOGGER.exception("Voice processing failed")
                    await ws.send_json({"status": "idle", "error": str(exc)})
                finally:
                    if active_task is asyncio.current_task():
                        active_task = None

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
                        await cancel_active_task(send_idle=True)
                    elif msg_type == "set-capture-mode":
                        manual_finish_enabled = bool(payload.get("manual_finish"))
                        manual_finish_phrases = command_send_phrases(command_language)
                    continue
                if message.type != WSMsgType.BINARY:
                    continue
                if active_task is not None and not active_task.done():
                    continue
                if len(message.data) < 1600:
                    continue
                abort_event = asyncio.Event()
                active_task = asyncio.create_task(run_audio_task(message.data, abort_event))
        finally:
            await cancel_active_task(send_idle=False)
            await self._clear_active_ws(ws)
        return ws
