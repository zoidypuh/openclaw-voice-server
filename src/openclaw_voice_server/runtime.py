from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import io
import logging
import time
import uuid
from dataclasses import dataclass, field
import wave

from aiohttp import WSMsgType, web

from .agents import HermesConversationAgent, OpenAIChatAgent, build_conversation_agent
from .config_store import ConfigStore
from .errors import ValidationError
from .stt import build_transcriber
from .tts import build_synthesizer, normalize_elevenlabs_preset
from .text import (
    command_send_phrases,
    detect_voice_control_command,
    extract_speech_directives,
    has_probable_voice_transcript,
    remaining_voice_text_after_command,
    should_drop_voice_transcript,
    split_send_phrase,
    strip_markdown,
)


LOGGER = logging.getLogger(__name__)
DirectGatewayClient = OpenAIChatAgent

# This covers TTS synthesis plus handing the audio off to the live client.
# Five seconds is too short on reconnect/unlock hiccups and causes false 504s.
SPEAK_REQUEST_TIMEOUT_SECONDS = 15.0
DEBATE_TURN_PAUSE_SECONDS = 2.0
SILENCE_SAMPLE_RATE = 24_000
DEFAULT_DEBATE_SPEAKERS = ("speaker-a", "speaker-b")


def _format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    return f"{seconds:.3f}s"


def _summarize_text(text: str, *, limit: int = 180) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return "[empty]"
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


@dataclass(slots=True)
class VoiceTurnMetrics:
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    started_at: float = field(default_factory=time.perf_counter)
    speech_duration_seconds: float = 0.0
    stt_seconds: float = 0.0
    ttft_seconds: float | None = None
    first_tts_seconds: float | None = None
    first_audio_seconds: float | None = None
    total_tts_seconds: float = 0.0
    transcript: str = ""
    reply_chunks: list[str] = field(default_factory=list)


class VoiceRuntime:
    def __init__(self, store: ConfigStore):
        self.store = store
        self._interrupt_transcriber = None
        self._interrupt_transcriber_key: tuple | None = None
        self._interrupt_transcriber_lock = asyncio.Lock()
        self._active_ws: web.WebSocketResponse | None = None
        self._active_ws_lock = asyncio.Lock()
        self._active_ws_supports_playback_accept = False
        self._turn_lock = asyncio.Lock()
        self._pending_playback_accepts: dict[str, asyncio.Future[None]] = {}
        self._pending_playback_accepts_lock = asyncio.Lock()

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
    def _disable_faster_whisper_vad(stt_settings: dict) -> dict:
        settings = dict(stt_settings)
        if settings.get("default_backend") == "faster-whisper":
            # This app already segments turns on the client. Letting
            # faster-whisper run its own VAD on top of that tends to trim live
            # turns too aggressively, especially short commands and speech with
            # pauses.
            settings["vad_filter"] = False
        return settings

    @staticmethod
    def _interrupt_stt_settings(stt_settings: dict) -> dict:
        return VoiceRuntime._disable_faster_whisper_vad(stt_settings)

    @staticmethod
    def _turn_stt_settings(stt_settings: dict) -> dict:
        return VoiceRuntime._disable_faster_whisper_vad(stt_settings)

    @staticmethod
    def _normalize_speaker_name(speaker_name: str | None) -> str | None:
        normalized = "-".join(str(speaker_name or "").strip().lower().replace("_", " ").split())
        return normalized or None

    @classmethod
    def _speaker_voice_ids(cls, settings: dict) -> dict[str, str]:
        raw_mapping = (settings.get("tts") or {}).get("speaker_voice_ids") or {}
        if not isinstance(raw_mapping, dict):
            return {}
        mapping: dict[str, str] = {}
        for key, value in raw_mapping.items():
            speaker_name = cls._normalize_speaker_name(str(key or ""))
            voice_id = str(value or "").strip()
            if speaker_name and voice_id:
                mapping[speaker_name] = voice_id
        return mapping

    @classmethod
    def _speaker_overrides(cls, settings: dict) -> dict[str, dict]:
        raw_mapping = (settings.get("tts") or {}).get("speaker_overrides") or {}
        if not isinstance(raw_mapping, dict):
            return {}
        mapping: dict[str, dict] = {}
        for key, value in raw_mapping.items():
            speaker_name = cls._normalize_speaker_name(str(key or ""))
            if speaker_name and isinstance(value, dict):
                mapping[speaker_name] = dict(value)
        return mapping

    @classmethod
    def _allowed_speakers(cls, settings: dict) -> set[str]:
        return set(cls._speaker_voice_ids(settings)) | set(cls._speaker_overrides(settings))

    @classmethod
    def _tts_settings_for_speaker(cls, settings: dict, speaker_name: str | None) -> dict:
        base_tts_settings = dict(settings.get("tts") or {})
        normalized_speaker = cls._normalize_speaker_name(speaker_name)
        if normalized_speaker is None:
            return base_tts_settings

        speaker_voice_ids = cls._speaker_voice_ids(settings)
        speaker_overrides = cls._speaker_overrides(settings)
        override = dict(speaker_overrides.get(normalized_speaker) or {})
        provider = str(override.get("provider") or base_tts_settings.get("default_provider") or "").strip().lower()
        if provider:
            base_tts_settings["default_provider"] = provider

        provider = str(base_tts_settings.get("default_provider") or "").strip().lower()
        if provider == "elevenlabs":
            voice_id = str(
                override.get("voice_id")
                or override.get("elevenlabs_voice_id")
                or speaker_voice_ids.get(normalized_speaker)
                or base_tts_settings.get("elevenlabs_voice_id")
                or ""
            ).strip()
            if voice_id:
                base_tts_settings["elevenlabs_voice_id"] = voice_id

            model_id = str(override.get("model_id") or override.get("elevenlabs_model") or "").strip()
            if model_id:
                base_tts_settings["elevenlabs_model"] = model_id

            preset_name = str(
                override.get("preset_name")
                or override.get("elevenlabs_preset")
                or base_tts_settings.get("elevenlabs_preset")
                or ""
            ).strip()
            if preset_name:
                base_tts_settings["elevenlabs_preset"] = normalize_elevenlabs_preset(preset_name)
        elif provider == "edge":
            voice = str(override.get("voice") or override.get("edge_voice") or "").strip()
            if voice:
                base_tts_settings["edge_voice"] = voice
            rate = str(override.get("rate") or override.get("edge_rate") or "").strip()
            if rate:
                base_tts_settings["edge_rate"] = rate
        elif provider == "vibevoice":
            voice = str(override.get("voice") or override.get("vibevoice_voice") or "").strip()
            if voice:
                base_tts_settings["vibevoice_voice"] = voice
            base_url = str(override.get("base_url") or override.get("vibevoice_base_url") or "").strip()
            if base_url:
                base_tts_settings["vibevoice_base_url"] = base_url
        elif provider == "piper":
            model_path = str(override.get("model_path") or override.get("piper_model_path") or "").strip()
            if model_path:
                base_tts_settings["piper_model_path"] = model_path
            config_path = str(override.get("config_path") or override.get("piper_config_path") or "").strip()
            if config_path:
                base_tts_settings["piper_config_path"] = config_path
            if "speaker" in override or "piper_speaker" in override:
                base_tts_settings["piper_speaker"] = override.get(
                    "speaker",
                    override.get("piper_speaker"),
                )

        return base_tts_settings

    @classmethod
    def _resolve_synthesizer(
        cls,
        settings: dict,
        *,
        speaker_name: str | None = None,
        default_synthesizer=None,
    ):
        tts_settings = cls._tts_settings_for_speaker(settings, speaker_name)
        if default_synthesizer is not None and tts_settings == dict(settings.get("tts") or {}):
            synthesizer = default_synthesizer
        else:
            synthesizer = build_synthesizer(tts_settings, settings["secrets"])
        audio_mime_type = getattr(synthesizer, "audio_mime_type", "audio/mpeg")
        return synthesizer, audio_mime_type

    @staticmethod
    def _conversation_backend(settings: dict) -> str:
        return str((settings.get("agent") or {}).get("backend") or "openclaw").strip().lower()

    @classmethod
    def _build_conversation_agent(cls, settings: dict):
        return build_conversation_agent(
            settings,
            hermes_agent_cls=HermesConversationAgent,
            direct_agent_cls=DirectGatewayClient,
        )

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

        # Fast Silero VAD pre-check: skip full Whisper if no speech detected.
        from .stt.silero_vad import audio_contains_speech

        loop = asyncio.get_running_loop()
        has_speech = await loop.run_in_executor(
            None, audio_contains_speech, audio_bytes,
        )
        if not has_speech:
            return web.json_response(
                {"ok": True, "matched": False, "action": "", "heard": "", "content": "", "usable_speech": False}
            )

        transcriber = await self._get_interrupt_transcriber()
        command_language = self.store.load_runtime_settings()["stt"].get("language", "")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, transcriber.transcribe, audio_bytes)
        text = result.text.strip()
        duration = float(getattr(result, "duration_seconds", 0.0) or 0.0)
        action = detect_voice_control_command(text, language=command_language)
        content = text
        if not action and allow_send_phrase:
            for phrase in command_send_phrases(command_language):
                _, matched_send_phrase = split_send_phrase(text, phrase)
                if matched_send_phrase:
                    action = "send"
                    break
        if action in {"interrupt", "pause", "hold"}:
            content = remaining_voice_text_after_command(
                text,
                action,
                language=command_language,
            )
        usable_speech = bool(action) or has_probable_voice_transcript(text, duration, min_duration=0.2)
        return web.json_response(
            {
                "ok": True,
                "matched": action == "interrupt",
                "action": action or "",
                "heard": text,
                "content": content,
                "usable_speech": usable_speech,
            }
        )

    async def _set_active_ws(self, ws: web.WebSocketResponse | None) -> None:
        async with self._active_ws_lock:
            self._active_ws = ws
            self._active_ws_supports_playback_accept = False

    async def _clear_active_ws(self, ws: web.WebSocketResponse) -> None:
        async with self._active_ws_lock:
            if self._active_ws is ws:
                self._active_ws = None
                self._active_ws_supports_playback_accept = False

    async def _get_active_ws(self) -> web.WebSocketResponse | None:
        async with self._active_ws_lock:
            return self._active_ws

    async def _set_active_ws_playback_accept_support(
        self,
        ws: web.WebSocketResponse,
        supports_playback_accept: bool,
    ) -> None:
        async with self._active_ws_lock:
            if self._active_ws is ws:
                self._active_ws_supports_playback_accept = supports_playback_accept

    async def _active_ws_requires_playback_accept(self, ws: web.WebSocketResponse) -> bool:
        async with self._active_ws_lock:
            return self._active_ws is ws and self._active_ws_supports_playback_accept

    async def _register_playback_accept(self, request_id: str) -> asyncio.Future[None]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        async with self._pending_playback_accepts_lock:
            self._pending_playback_accepts[request_id] = future
        return future

    async def _resolve_playback_accept(self, request_id: str) -> None:
        async with self._pending_playback_accepts_lock:
            future = self._pending_playback_accepts.pop(request_id, None)
        if future is not None and not future.done():
            future.set_result(None)

    async def _reject_playback_accept(self, request_id: str, message: str) -> None:
        async with self._pending_playback_accepts_lock:
            future = self._pending_playback_accepts.pop(request_id, None)
        if future is not None and not future.done():
            future.set_exception(ValidationError(message))

    async def _clear_playback_accept(self, request_id: str) -> None:
        async with self._pending_playback_accepts_lock:
            future = self._pending_playback_accepts.pop(request_id, None)
        if future is not None and not future.done():
            future.cancel()

    async def _reject_all_playback_accepts(self, message: str) -> None:
        async with self._pending_playback_accepts_lock:
            futures = list(self._pending_playback_accepts.values())
            self._pending_playback_accepts.clear()
        for future in futures:
            if not future.done():
                future.set_exception(ValidationError(message))

    @staticmethod
    def _build_silence_wav(duration_seconds: float, *, sample_rate: int = SILENCE_SAMPLE_RATE) -> bytes:
        frame_count = max(int(round(max(duration_seconds, 0.0) * sample_rate)), 1)
        pcm_audio = b"\x00\x00" * frame_count
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(pcm_audio)
            return buffer.getvalue()

    async def _push_audio_to_active_ws(
        self,
        ws: web.WebSocketResponse,
        audio: bytes,
        *,
        audio_mime_type: str,
    ) -> None:
        request_id = uuid.uuid4().hex
        wait_for_playback_accept = await self._active_ws_requires_playback_accept(ws)
        accept_future: asyncio.Future[None] | None = None
        if wait_for_playback_accept:
            accept_future = await self._register_playback_accept(request_id)
        try:
            speaking_payload = {
                "status": "speaking",
                "source": "server_speak",
                "request_id": request_id,
            }
            if audio_mime_type != "audio/mpeg":
                speaking_payload["audio_mime_type"] = audio_mime_type
            await ws.send_json(speaking_payload)
            await ws.send_bytes(audio)
            if accept_future is not None:
                await accept_future
            await ws.send_json(
                {
                    "status": "idle",
                    "source": "server_speak",
                    "request_id": request_id,
                }
            )
        except ConnectionResetError as exc:
            await self._clear_active_ws(ws)
            if accept_future is not None:
                await self._clear_playback_accept(request_id)
            raise ValidationError("The active voice client disconnected before playback.") from exc
        finally:
            if accept_future is not None:
                await self._clear_playback_accept(request_id)

    async def speak_text(
        self,
        text: str,
        *,
        preset_name: str | None = None,
        speaker_name: str | None = None,
    ) -> dict[str, object]:
        ws = await self._get_active_ws()
        if ws is None:
            raise ValidationError("No active voice client is connected.")

        settings = self.store.load_runtime_settings()
        raw_text = str(text).strip()
        if not raw_text:
            raise ValidationError("Missing text to speak.")

        resolved_speaker = self._normalize_speaker_name(speaker_name)
        detected_speaker, detected_style, remaining_text, waiting_for_more = extract_speech_directives(
            raw_text,
            allowed_speakers=self._allowed_speakers(settings),
        )
        if detected_speaker is not None and resolved_speaker is None:
            resolved_speaker = detected_speaker

        reply_style = preset_name or detected_style
        if not waiting_for_more:
            raw_text = remaining_text
        spoken_text = strip_markdown(raw_text).strip()
        if not spoken_text:
            raise ValidationError("Text to speak was empty after normalization.")

        synthesizer, audio_mime_type = self._resolve_synthesizer(
            settings,
            speaker_name=resolved_speaker,
        )
        async with self._turn_lock:
            audio = await synthesizer.synthesize(spoken_text, preset_name=reply_style)
            if not audio:
                raise ValidationError("Speech synthesis returned no audio.")
            await self._push_audio_to_active_ws(
                ws,
                audio,
                audio_mime_type=audio_mime_type,
            )
        return {
            "ok": True,
            "speaker_name": resolved_speaker or "",
            "spoken_text": spoken_text,
            "preset_name": reply_style or "",
            "audio_bytes": len(audio),
        }

    async def play_silence(self, duration_seconds: float) -> dict[str, object]:
        ws = await self._get_active_ws()
        if ws is None:
            raise ValidationError("No active voice client is connected.")

        silence_duration = max(float(duration_seconds), 0.0)
        if silence_duration <= 0:
            return {"ok": True, "audio_bytes": 0, "duration_seconds": 0.0}

        audio = self._build_silence_wav(silence_duration)
        async with self._turn_lock:
            await self._push_audio_to_active_ws(
                ws,
                audio,
                audio_mime_type="audio/wav",
            )
        return {
            "ok": True,
            "audio_bytes": len(audio),
            "duration_seconds": silence_duration,
        }

    async def handle_speak_request(self, request: web.Request) -> web.Response:
        payload = await request.json() if request.can_read_body else {}
        timeout_value = payload.get("timeout_seconds", SPEAK_REQUEST_TIMEOUT_SECONDS)
        try:
            timeout_seconds = float(timeout_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("timeout_seconds must be a positive number.") from exc
        if timeout_seconds <= 0:
            raise ValidationError("timeout_seconds must be a positive number.")

        try:
            result = await asyncio.wait_for(
                self.speak_text(
                    str(payload.get("text") or ""),
                    preset_name=str(payload.get("preset_name") or "").strip() or None,
                    speaker_name=str(payload.get("speaker_name") or "").strip() or None,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return web.json_response(
                {
                    "ok": False,
                    "error": (
                        "Timed out waiting for the active voice client to accept playback."
                    ),
                    "timeout_seconds": timeout_seconds,
                },
                status=504,
            )
        return web.json_response(result)

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        settings = self.store.load_runtime_settings()
        turn_stt_settings = self._turn_stt_settings(settings["stt"])
        ws = web.WebSocketResponse(max_msg_size=10_000_000)
        await ws.prepare(request)
        await self._set_active_ws(ws)

        transcriber = build_transcriber(turn_stt_settings)
        synthesizer = build_synthesizer(settings["tts"], settings["secrets"])
        conversation_agent = self._build_conversation_agent(settings)
        command_language = settings["stt"].get("language", "")

        active_task: asyncio.Task | None = None
        abort_event = asyncio.Event()
        manual_finish_enabled = True
        manual_finish_phrases = command_send_phrases(command_language)
        pending_transcript_prefix = ""

        async def process_audio(
            audio_bytes: bytes,
            task_abort_event: asyncio.Event,
            *,
            transcript_prefix: str = "",
        ) -> None:
            nonlocal manual_finish_enabled, manual_finish_phrases
            loop = asyncio.get_running_loop()
            turn = VoiceTurnMetrics()
            await ws.send_json({"status": "thinking"})
            stt_started_at = time.perf_counter()
            result = await loop.run_in_executor(None, transcriber.transcribe, audio_bytes)
            turn.stt_seconds = time.perf_counter() - stt_started_at
            text = result.text.strip()
            duration = float(getattr(result, "duration_seconds", 0.0) or 0.0)
            turn.speech_duration_seconds = duration
            if task_abort_event.is_set():
                return
            if not text:
                LOGGER.info(
                    "[%s] speech input detected (%s) but STT returned no transcript after %s",
                    turn.turn_id,
                    _format_elapsed(duration),
                    _format_elapsed(turn.stt_seconds),
                )
                await ws.send_json({"status": "idle"})
                return
            if manual_finish_enabled:
                for send_phrase in manual_finish_phrases:
                    next_text, matched_send_phrase = split_send_phrase(text, send_phrase)
                    if not matched_send_phrase:
                        continue
                    text = next_text.strip()
                    if not text:
                        LOGGER.info(
                            "[%s] speech input detected (%s) but only the send phrase remained after cleanup",
                            turn.turn_id,
                            _format_elapsed(duration),
                        )
                        await ws.send_json({"status": "idle"})
                        return
                    break
            prefix = str(transcript_prefix or "").strip()
            if prefix:
                text = f"{prefix} {text}".strip()
            action = detect_voice_control_command(text, language=command_language)
            if action:
                command_content = text
                if action == "hold":
                    command_content = remaining_voice_text_after_command(
                        text,
                        action,
                        language=command_language,
                    )
                LOGGER.info(
                    "[%s] voice command detected (%s): %s",
                    turn.turn_id,
                    action,
                    _summarize_text(command_content or text),
                )
                payload = {"type": "voice-command", "action": action, "heard": text}
                if action == "hold":
                    payload["content"] = command_content
                await ws.send_json(payload)
                await ws.send_json({"status": "idle"})
                return
            audio_settings = settings.get("audio", {})
            min_duration = max(float(audio_settings.get("min_speech_ms", 500) or 500) / 1000.0, 0.0)
            if should_drop_voice_transcript(text, duration, min_duration=min_duration, command_language=command_language):
                LOGGER.info(
                    "[%s] VAD ignored noise/too-short input (%s, stt=%s): %s",
                    turn.turn_id,
                    _format_elapsed(duration),
                    _format_elapsed(turn.stt_seconds),
                    _summarize_text(text),
                )
                await ws.send_json({"status": "idle"})
                return

            turn.transcript = text
            LOGGER.info(
                "[%s] speech input detected (%s)",
                turn.turn_id,
                _format_elapsed(turn.speech_duration_seconds),
            )
            LOGGER.info("[%s] transcript: %s", turn.turn_id, _summarize_text(turn.transcript))
            LOGGER.info("[%s] stt took %s", turn.turn_id, _format_elapsed(turn.stt_seconds))

            speaking_started = False
            reply_style: str | None = None
            reply_speaker: str | None = None
            intro_buffer = ""
            directives_resolved = False
            reply_started_at = time.perf_counter()
            synth_cache: dict[str, tuple[object, str]] = {
                "": (synthesizer, getattr(synthesizer, "audio_mime_type", "audio/mpeg"))
            }

            def resolve_chunk_synthesizer(current_speaker: str | None):
                normalized_speaker = self._normalize_speaker_name(current_speaker)
                cache_key = normalized_speaker or ""
                if cache_key not in synth_cache:
                    synth_cache[cache_key] = self._resolve_synthesizer(
                        settings,
                        speaker_name=normalized_speaker,
                    )
                return synth_cache[cache_key]

            async def send_reply_chunk(clean_text: str) -> None:
                nonlocal speaking_started
                chunk_text = clean_text.strip()
                if not chunk_text:
                    return
                current_synthesizer, current_audio_mime_type = resolve_chunk_synthesizer(reply_speaker)
                if turn.ttft_seconds is None:
                    turn.ttft_seconds = time.perf_counter() - reply_started_at
                tts_started_at = time.perf_counter()
                audio = await current_synthesizer.synthesize(chunk_text, preset_name=reply_style)
                tts_elapsed = time.perf_counter() - tts_started_at
                turn.total_tts_seconds += tts_elapsed
                if not audio:
                    return
                turn.reply_chunks.append(_summarize_text(chunk_text))
                if turn.first_tts_seconds is None:
                    turn.first_tts_seconds = tts_elapsed
                if not speaking_started:
                    speaking_started = True
                    speaking_payload = {"status": "speaking"}
                    if current_audio_mime_type != "audio/mpeg":
                        speaking_payload["audio_mime_type"] = current_audio_mime_type
                    await ws.send_json(speaking_payload)
                await ws.send_bytes(audio)
                if turn.first_audio_seconds is None:
                    turn.first_audio_seconds = time.perf_counter() - turn.started_at
                    LOGGER.info(
                        "[%s] ttft was %s | tts first chunk %s | first chunk arrived in %s",
                        turn.turn_id,
                        _format_elapsed(turn.ttft_seconds),
                        _format_elapsed(turn.first_tts_seconds),
                        _format_elapsed(turn.first_audio_seconds),
                    )
                    LOGGER.info("[%s] first chunk: %s", turn.turn_id, turn.reply_chunks[0])

            async for chunk in conversation_agent.stream_reply(text, task_abort_event):
                if task_abort_event.is_set():
                    return
                clean = strip_markdown(chunk)
                if not clean:
                    continue
                if not directives_resolved:
                    intro_buffer += clean
                    detected_speaker, detected_style, remaining_text, waiting_for_more = extract_speech_directives(
                        intro_buffer,
                        allowed_speakers=self._allowed_speakers(settings),
                    )
                    if waiting_for_more:
                        continue
                    if detected_speaker is not None:
                        reply_speaker = detected_speaker
                    if detected_style:
                        reply_style = detected_style
                    clean = remaining_text
                    intro_buffer = ""
                    directives_resolved = True
                if not clean.strip():
                    continue
                await send_reply_chunk(clean)
            if intro_buffer and not task_abort_event.is_set():
                if not directives_resolved:
                    detected_speaker, detected_style, remaining_text, waiting_for_more = extract_speech_directives(
                        intro_buffer,
                        allowed_speakers=self._allowed_speakers(settings),
                    )
                    if not waiting_for_more:
                        if detected_speaker is not None:
                            reply_speaker = detected_speaker
                        if detected_style:
                            reply_style = detected_style
                        intro_buffer = remaining_text
                await send_reply_chunk(intro_buffer)
            if task_abort_event.is_set():
                return
            if turn.reply_chunks:
                LOGGER.info("[%s] reply || %s", turn.turn_id, " || ".join(turn.reply_chunks))
            else:
                LOGGER.info("[%s] reply was empty", turn.turn_id)
            LOGGER.info(
                "[%s] total roundtrip %s | tts total %s",
                turn.turn_id,
                _format_elapsed(time.perf_counter() - turn.started_at),
                _format_elapsed(turn.total_tts_seconds),
            )
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

        async def run_audio_task(
            audio_bytes: bytes,
            task_abort_event: asyncio.Event,
            *,
            transcript_prefix: str = "",
        ) -> None:
            nonlocal active_task
            async with self._turn_lock:
                try:
                    await process_audio(
                        audio_bytes,
                        task_abort_event,
                        transcript_prefix=transcript_prefix,
                    )
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
                    elif msg_type == "client-ready":
                        features = payload.get("features") or {}
                        await self._set_active_ws_playback_accept_support(
                            ws,
                            bool(features.get("playback_accept")),
                        )
                    elif msg_type == "playback-accepted":
                        await self._resolve_playback_accept(str(payload.get("request_id") or ""))
                    elif msg_type == "playback-rejected":
                        reason = str(payload.get("error") or "").strip() or "The active voice client rejected playback."
                        await self._reject_playback_accept(
                            str(payload.get("request_id") or ""),
                            reason,
                        )
                    elif msg_type == "interrupt":
                        await cancel_active_task(send_idle=True)
                        pending_transcript_prefix = ""
                    elif msg_type == "set-transcript-prefix":
                        pending_transcript_prefix = str(payload.get("prefix_text") or "").strip()
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
                transcript_prefix = pending_transcript_prefix
                pending_transcript_prefix = ""
                active_task = asyncio.create_task(
                    run_audio_task(
                        message.data,
                        abort_event,
                        transcript_prefix=transcript_prefix,
                    )
                )
        finally:
            await cancel_active_task(send_idle=False)
            await self._reject_all_playback_accepts(
                "The active voice client disconnected before playback."
            )
            await self._clear_active_ws(ws)
        return ws
