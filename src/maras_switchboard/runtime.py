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
from .catalog import normalize_agent_backend
from .config_store import ConfigStore
from .errors import ValidationError
from .stt import build_transcriber
from .tts import build_synthesizer, normalize_elevenlabs_preset
from .text import (
    extract_speech_directives,
    should_drop_voice_transcript,
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


def _should_skip_spoken_reply(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return True
    return normalized.upper() == "EMPTY"


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
        self._active_ws: web.WebSocketResponse | None = None
        self._active_ws_lock = asyncio.Lock()
        self._active_ws_supports_playback_accept = False
        self._turn_lock = asyncio.Lock()
        self._pending_playback_accepts: dict[str, asyncio.Future[None]] = {}
        self._playback_request_labels: dict[str, str] = {}
        self._pending_playback_accepts_lock = asyncio.Lock()

    @staticmethod
    def _disable_faster_whisper_vad(stt_settings: dict) -> dict:
        settings = dict(stt_settings)
        if settings.get("default_backend") == "faster-whisper":
            # This app already segments turns on the client. Letting
            # faster-whisper run its own VAD on top of that tends to trim live
            # turns too aggressively, especially speech with pauses.
            settings["vad_filter"] = False
            # The fast Silero pre-check is useful for short probes, but on full
            # live turns it can produce false negatives and skip Whisper entirely.
            settings["speech_precheck"] = False
        return settings

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

    @staticmethod
    def _tts_disabled(settings: dict) -> bool:
        provider = str((settings.get("tts") or {}).get("default_provider") or "").strip().lower()
        return provider == "disabled"

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
        elif provider == "supertonic":
            python_path = str(
                override.get("python_path") or override.get("supertonic_python_path") or ""
            ).strip()
            if python_path:
                base_tts_settings["supertonic_python_path"] = python_path
            voice = str(override.get("voice") or override.get("supertonic_voice") or "").strip()
            if voice:
                base_tts_settings["supertonic_voice"] = voice
            language = str(
                override.get("language") or override.get("supertonic_language") or ""
            ).strip()
            if language:
                base_tts_settings["supertonic_language"] = language
            if "total_steps" in override or "supertonic_total_steps" in override:
                base_tts_settings["supertonic_total_steps"] = override.get(
                    "total_steps",
                    override.get("supertonic_total_steps"),
                )
            if "speed" in override or "supertonic_speed" in override:
                base_tts_settings["supertonic_speed"] = override.get(
                    "speed",
                    override.get("supertonic_speed"),
                )
        elif provider == "chatterbox-turbo":
            python_path = str(
                override.get("python_path") or override.get("chatterbox_python_path") or ""
            ).strip()
            if python_path:
                base_tts_settings["chatterbox_python_path"] = python_path
            voice_prompt_path = str(
                override.get("voice_prompt_path")
                or override.get("audio_prompt_path")
                or override.get("chatterbox_voice_prompt_path")
                or ""
            ).strip()
            if voice_prompt_path:
                base_tts_settings["chatterbox_voice_prompt_path"] = voice_prompt_path
            device = str(override.get("device") or override.get("chatterbox_device") or "").strip()
            if device:
                base_tts_settings["chatterbox_device"] = device
            if "exaggeration" in override or "chatterbox_exaggeration" in override:
                base_tts_settings["chatterbox_exaggeration"] = override.get(
                    "exaggeration",
                    override.get("chatterbox_exaggeration"),
                )
            if "temperature" in override or "chatterbox_temperature" in override:
                base_tts_settings["chatterbox_temperature"] = override.get(
                    "temperature",
                    override.get("chatterbox_temperature"),
                )
            if "top_p" in override or "chatterbox_top_p" in override:
                base_tts_settings["chatterbox_top_p"] = override.get(
                    "top_p",
                    override.get("chatterbox_top_p"),
                )
            if "top_k" in override or "chatterbox_top_k" in override:
                base_tts_settings["chatterbox_top_k"] = override.get(
                    "top_k",
                    override.get("chatterbox_top_k"),
                )
            if "repetition_penalty" in override or "chatterbox_repetition_penalty" in override:
                base_tts_settings["chatterbox_repetition_penalty"] = override.get(
                    "repetition_penalty",
                    override.get("chatterbox_repetition_penalty"),
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
        if cls._tts_disabled(settings):
            raise ValidationError("TTS is disabled for this runtime.")
        tts_settings = cls._tts_settings_for_speaker(settings, speaker_name)
        if default_synthesizer is not None and tts_settings == dict(settings.get("tts") or {}):
            synthesizer = default_synthesizer
        else:
            synthesizer = build_synthesizer(tts_settings, settings["secrets"])
        audio_mime_type = getattr(synthesizer, "audio_mime_type", "audio/mpeg")
        return synthesizer, audio_mime_type

    @classmethod
    def _tts_requires_buffered_reply(
        cls,
        settings: dict,
        *,
        speaker_name: str | None = None,
    ) -> bool:
        return False

    @staticmethod
    def _conversation_backend(settings: dict) -> str:
        return normalize_agent_backend((settings.get("agent") or {}).get("backend"))

    @classmethod
    def _build_conversation_agent(cls, settings: dict):
        return build_conversation_agent(
            settings,
            hermes_agent_cls=HermesConversationAgent,
            direct_agent_cls=DirectGatewayClient,
        )

    async def handle_speech_probe(self, request: web.Request) -> web.Response:
        payload = await request.json() if request.can_read_body else {}
        audio_b64 = str(payload.get("audio_b64") or "").strip()
        if not audio_b64:
            raise ValidationError("Missing speech probe audio.")
        try:
            audio_bytes = base64.b64decode(audio_b64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValidationError("Speech probe audio was invalid.") from exc
        if len(audio_bytes) < 1600:
            return web.json_response({"ok": True, "usable_speech": False})

        from .stt.silero_vad import audio_contains_speech

        loop = asyncio.get_running_loop()
        usable_speech = await loop.run_in_executor(None, audio_contains_speech, audio_bytes)
        return web.json_response({"ok": True, "usable_speech": bool(usable_speech)})

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

    async def _remember_playback_request(self, request_id: str, label: str) -> None:
        if not request_id:
            return
        async with self._pending_playback_accepts_lock:
            self._playback_request_labels[request_id] = _summarize_text(label)

    async def _resolve_playback_accept(self, request_id: str) -> None:
        async with self._pending_playback_accepts_lock:
            future = self._pending_playback_accepts.pop(request_id, None)
            label = self._playback_request_labels.pop(request_id, "")
        if future is not None and not future.done():
            future.set_result(None)
        if label:
            LOGGER.info("[client] playback accepted: %s", label)

    async def _reject_playback_accept(self, request_id: str, message: str) -> None:
        async with self._pending_playback_accepts_lock:
            future = self._pending_playback_accepts.pop(request_id, None)
            label = self._playback_request_labels.pop(request_id, "")
        if future is not None and not future.done():
            future.set_exception(ValidationError(message))
        if label:
            LOGGER.warning("[client] playback rejected: %s (%s)", label, message)

    async def _clear_playback_accept(self, request_id: str) -> None:
        async with self._pending_playback_accepts_lock:
            future = self._pending_playback_accepts.pop(request_id, None)
            self._playback_request_labels.pop(request_id, None)
        if future is not None and not future.done():
            future.cancel()

    async def _reject_all_playback_accepts(self, message: str) -> None:
        async with self._pending_playback_accepts_lock:
            futures = list(self._pending_playback_accepts.values())
            self._pending_playback_accepts.clear()
            self._playback_request_labels.clear()
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
        speaking_sent = False
        if wait_for_playback_accept:
            accept_future = await self._register_playback_accept(request_id)
        await self._remember_playback_request(request_id, f"server_speak: {len(audio)} bytes")
        try:
            speaking_payload = {
                "status": "speaking",
                "source": "server_speak",
                "request_id": request_id,
            }
            if audio_mime_type != "audio/mpeg":
                speaking_payload["audio_mime_type"] = audio_mime_type
            await ws.send_json(speaking_payload)
            speaking_sent = True
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
        except asyncio.CancelledError:
            if speaking_sent:
                try:
                    await ws.send_json(
                        {
                            "status": "idle",
                            "source": "server_speak",
                            "request_id": request_id,
                        }
                    )
                except ConnectionResetError:
                    await self._clear_active_ws(ws)
            raise
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
        if self._tts_disabled(settings):
            raise ValidationError("TTS is disabled for this runtime.")

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
        if turn_stt_settings.get("default_backend") == "xai":
            turn_stt_settings = {
                **turn_stt_settings,
                "xai_api_key": str(settings["secrets"].get("xai_api_key") or "").strip(),
            }
        ws = web.WebSocketResponse(max_msg_size=10_000_000)
        await ws.prepare(request)
        await self._set_active_ws(ws)

        try:
            transcriber = build_transcriber(turn_stt_settings)
            tts_disabled = self._tts_disabled(settings)
            synthesizer = None if tts_disabled else build_synthesizer(settings["tts"], settings["secrets"])
            conversation_agent = self._build_conversation_agent(settings)
        except Exception as exc:
            LOGGER.exception("Voice runtime initialization failed")
            with contextlib.suppress(ConnectionResetError):
                await ws.send_json({"status": "idle", "error": str(exc)})
            with contextlib.suppress(ConnectionResetError):
                await ws.close(code=1011, message=str(exc).encode("utf-8")[:120])
            await self._clear_active_ws(ws)
            return ws
        active_task: asyncio.Task | None = None
        abort_event = asyncio.Event()
        pending_turn_commit_meta: dict[str, object] | None = None

        async def process_audio(
            audio_bytes: bytes,
            task_abort_event: asyncio.Event,
            *,
            turn_commit_meta: dict[str, object] | None = None,
        ) -> None:
            loop = asyncio.get_running_loop()
            turn = VoiceTurnMetrics()
            if turn_commit_meta:
                LOGGER.info(
                    "[client] turn commit reason=%s speech=%sms silence=%sms threshold=%s level=%s wait=%sms",
                    str(turn_commit_meta.get("reason") or "-"),
                    int(turn_commit_meta.get("speech_ms") or 0),
                    int(turn_commit_meta.get("silence_ms") or 0),
                    turn_commit_meta.get("threshold_db"),
                    turn_commit_meta.get("level_db"),
                    int(turn_commit_meta.get("wait_after_speak_ms") or 0),
                )
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
            audio_settings = settings.get("audio", {})
            min_duration = max(float(audio_settings.get("min_speech_ms", 350) or 350) / 1000.0, 0.0)
            if should_drop_voice_transcript(text, duration, min_duration=min_duration):
                LOGGER.debug(
                    "[dim]dropped: %s (%s)[/dim]",
                    _summarize_text(text),
                    _format_elapsed(duration),
                )
                await ws.send_json({"status": "idle"})
                return

            turn.transcript = text
            LOGGER.info(
                "[bold cyan]🎤 %s[/bold cyan]  [dim]stt=%s  audio=%s[/dim]",
                _summarize_text(turn.transcript),
                _format_elapsed(turn.stt_seconds),
                _format_elapsed(turn.speech_duration_seconds),
            )
            await ws.send_json({"type": "transcript", "text": turn.transcript})
            await ws.send_json({"type": "reply-text", "text": "", "replace": True})

            speaking_started = False
            reply_style: str | None = None
            reply_speaker: str | None = None
            intro_buffer = ""
            directives_resolved = False
            reply_started_at = time.perf_counter()
            buffered_reply_text = ""
            synth_cache: dict[str, tuple[object, str]] = {
                "": (synthesizer, getattr(synthesizer, "audio_mime_type", "audio/mpeg"))
            }

            def resolve_chunk_synthesizer(current_speaker: str | None):
                if tts_disabled:
                    return None, "audio/mpeg"
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
                if _should_skip_spoken_reply(chunk_text):
                    LOGGER.info(
                        "[dim]skipping empty spoken reply chunk: %s[/dim]",
                        _summarize_text(chunk_text),
                    )
                    return
                await ws.send_json({"type": "reply-text", "text": chunk_text, "append": True})
                if tts_disabled:
                    if turn.ttft_seconds is None:
                        turn.ttft_seconds = time.perf_counter() - reply_started_at
                    turn.reply_chunks.append(_summarize_text(chunk_text))
                    LOGGER.info(
                        "[dim]tts disabled, reply not spoken: %s[/dim]",
                        _summarize_text(chunk_text),
                    )
                    return
                if self._tts_requires_buffered_reply(settings, speaker_name=reply_speaker):
                    if turn.ttft_seconds is None:
                        turn.ttft_seconds = time.perf_counter() - reply_started_at
                    nonlocal buffered_reply_text
                    buffered_reply_text = (
                        f"{buffered_reply_text} {chunk_text}".strip()
                        if buffered_reply_text
                        else chunk_text
                    )
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
                    request_id = uuid.uuid4().hex
                    await self._remember_playback_request(request_id, chunk_text)
                    speaking_payload = {"status": "speaking"}
                    speaking_payload["source"] = "voice_reply"
                    speaking_payload["request_id"] = request_id
                    if current_audio_mime_type != "audio/mpeg":
                        speaking_payload["audio_mime_type"] = current_audio_mime_type
                    await ws.send_json(speaking_payload)
                await ws.send_bytes(audio)
                if turn.first_audio_seconds is None:
                    turn.first_audio_seconds = time.perf_counter() - turn.started_at
                    LOGGER.info(
                        "[bold green]🔊 %s[/bold green]  [dim]llm=%s  tts=%s  total=%s[/dim]",
                        _summarize_text(turn.reply_chunks[0]),
                        _format_elapsed(turn.ttft_seconds),
                        _format_elapsed(turn.first_tts_seconds),
                        _format_elapsed(turn.first_audio_seconds),
                    )

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
            if buffered_reply_text and not task_abort_event.is_set():
                current_synthesizer, current_audio_mime_type = resolve_chunk_synthesizer(reply_speaker)
                tts_started_at = time.perf_counter()
                audio = await current_synthesizer.synthesize(buffered_reply_text, preset_name=reply_style)
                tts_elapsed = time.perf_counter() - tts_started_at
                turn.total_tts_seconds += tts_elapsed
                if audio:
                    turn.reply_chunks.append(_summarize_text(buffered_reply_text))
                    if turn.first_tts_seconds is None:
                        turn.first_tts_seconds = tts_elapsed
                    if not speaking_started:
                        speaking_started = True
                        request_id = uuid.uuid4().hex
                        await self._remember_playback_request(request_id, buffered_reply_text)
                        speaking_payload = {"status": "speaking"}
                        speaking_payload["source"] = "voice_reply"
                        speaking_payload["request_id"] = request_id
                        if current_audio_mime_type != "audio/mpeg":
                            speaking_payload["audio_mime_type"] = current_audio_mime_type
                        await ws.send_json(speaking_payload)
                    await ws.send_bytes(audio)
                    if turn.first_audio_seconds is None:
                        turn.first_audio_seconds = time.perf_counter() - turn.started_at
                        LOGGER.info(
                            "[bold green]🔊 %s[/bold green]  [dim]llm=%s  tts=%s  total=%s[/dim]",
                            _summarize_text(turn.reply_chunks[0]),
                            _format_elapsed(turn.ttft_seconds),
                            _format_elapsed(turn.first_tts_seconds),
                            _format_elapsed(turn.first_audio_seconds),
                        )
            if task_abort_event.is_set():
                return
            total_elapsed = time.perf_counter() - turn.started_at
            if turn.reply_chunks:
                LOGGER.info(
                    "[dim]── roundtrip %s  tts_total=%s ──[/dim]",
                    _format_elapsed(total_elapsed),
                    _format_elapsed(turn.total_tts_seconds),
                )
            else:
                LOGGER.info("[yellow]⚠ empty reply[/yellow]  [dim]roundtrip %s[/dim]", _format_elapsed(total_elapsed))
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
            turn_commit_meta: dict[str, object] | None = None,
        ) -> None:
            nonlocal active_task
            async with self._turn_lock:
                try:
                    await process_audio(
                        audio_bytes,
                        task_abort_event,
                        turn_commit_meta=turn_commit_meta,
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
                    elif msg_type == "turn-commit":
                        pending_turn_commit_meta = {
                            "reason": str(payload.get("reason") or "").strip(),
                            "speech_ms": int(payload.get("speech_ms") or 0),
                            "silence_ms": int(payload.get("silence_ms") or 0),
                            "threshold_db": payload.get("threshold_db"),
                            "level_db": payload.get("level_db"),
                            "wait_after_speak_ms": int(payload.get("wait_after_speak_ms") or 0),
                        }
                    continue
                if message.type != WSMsgType.BINARY:
                    continue
                if active_task is not None and not active_task.done():
                    continue
                if len(message.data) < 1600:
                    continue
                abort_event = asyncio.Event()
                turn_commit_meta = pending_turn_commit_meta
                pending_turn_commit_meta = None
                active_task = asyncio.create_task(
                    run_audio_task(
                        message.data,
                        abort_event,
                        turn_commit_meta=turn_commit_meta,
                    )
                )
        finally:
            await cancel_active_task(send_idle=False)
            await self._reject_all_playback_accepts(
                "The active voice client disconnected before playback."
            )
            await self._clear_active_ws(ws)
        return ws
