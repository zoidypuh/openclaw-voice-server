from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import io
import logging
import os
import shlex
import subprocess
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
from .tts import build_synthesizer, normalize_elevenlabs_preset, normalize_xai_tts_voice
from .text import (
    extract_speech_directives,
    should_drop_voice_transcript,
    strip_markdown,
)


LOGGER = logging.getLogger(__name__)
DirectGatewayClient = OpenAIChatAgent
TMUX_ENTER_KEY = "C-m"
TMUX_USER_SOURCE_MARKER = "[G]"

# This covers TTS synthesis plus handing the audio off to the live client.
# Five seconds is too short on reconnect/unlock hiccups and causes false 504s.
SPEAK_REQUEST_TIMEOUT_SECONDS = 15.0
PLAYBACK_CLIENT_READY_STALE_SECONDS = 10.0
PLAYBACK_ACCEPT_TIMEOUT_STALE_SECONDS = 30.0
DEBATE_TURN_PAUSE_SECONDS = 2.0
SILENCE_SAMPLE_RATE = 24_000
DEFAULT_DEBATE_SPEAKERS = ("speaker-a", "speaker-b")
VOICE_REACHABLE_DEFAULT_ENABLED = True
VOICE_REACHABLE_SPOKEN_REPLY_LIMIT = 240
VOICE_REACHABLE_TINY_ACKS = {
    "ok",
    "okay",
    "sure",
    "yep",
    "yeah",
    "done",
    "got it",
    "roger",
    "thanks",
    "thank you",
}


def _format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    return f"{seconds:.3f}s"


def _format_wall_time(timestamp: float | None) -> str:
    if not timestamp:
        return "-"
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _summarize_text(text: str, *, limit: int = 180) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return "[empty]"
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _stt_summary(settings: dict) -> dict[str, str]:
    stt_settings = settings.get("stt", settings)
    backend = str(stt_settings.get("default_backend") or "").strip()
    backend_models = stt_settings.get("backend_models")
    model = ""
    if isinstance(backend_models, dict):
        model = str(backend_models.get(backend) or "").strip()
    return {
        "backend": backend or "-",
        "model": model or "-",
        "language": str(stt_settings.get("language") or "").strip() or "auto",
    }


def _should_skip_spoken_reply(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return True
    return normalized.upper() == "EMPTY"


def _voice_reachable_command(text: str) -> str | None:
    normalized = " ".join(str(text or "").strip().casefold().split())
    normalized = normalized.replace("_", "-")
    if not normalized.startswith("/voice"):
        return None
    if normalized in {"/voice-on", "/voice on", "/voice-reachable on", "/voice reachable on"}:
        return "on"
    if normalized in {"/voice-off", "/voice off", "/voice-reachable off", "/voice reachable off"}:
        return "off"
    if normalized in {"/voice-status", "/voice status", "/voice-reachable", "/voice reachable"}:
        return "status"
    if normalized in {"/voice-toggle", "/voice toggle"}:
        return "toggle"
    return None


def _format_voice_reachable_status(status: dict[str, object]) -> str:
    reachable = "ON" if status.get("enabled") else "OFF"
    client = "connected" if status.get("active_voice_client") else "disconnected"
    playback = "playback ready" if status.get("playback_accept") else str(status.get("client_status") or "not ready")
    if status.get("enabled"):
        return (
            f"Voice reachable {reachable}. Switchboard voice client is {client}; {playback}. "
            "With headphones on, press the talk key to address Mara and she will speak important updates."
        )
    return f"Voice reachable {reachable}. Automatic spoken replies are stopped; manual speak still works."


def _spoken_voice_reachable_text(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ""
    ack_key = normalized.rstrip(".!?,").casefold()
    if ack_key in VOICE_REACHABLE_TINY_ACKS:
        return ""
    if len(normalized) <= VOICE_REACHABLE_SPOKEN_REPLY_LIMIT:
        return normalized
    sentence_end = -1
    for marker in (". ", "! ", "? "):
        index = normalized.find(marker)
        if 39 <= index <= VOICE_REACHABLE_SPOKEN_REPLY_LIMIT - 1:
            sentence_end = index + 1
            break
    if sentence_end > 0:
        return f"Summary: {normalized[:sentence_end].strip()}"
    summary = normalized[: VOICE_REACHABLE_SPOKEN_REPLY_LIMIT - 12].rstrip(" ,;:")
    return f"Summary: {summary}..."


def _tmux_targets_from_settings(settings: dict) -> dict[str, dict[str, str]]:
    tmux_settings = settings.get("tmux")
    if not isinstance(tmux_settings, dict):
        return {}
    raw_targets = tmux_settings.get("targets")
    targets: dict[str, dict[str, str]] = {}
    if isinstance(raw_targets, dict):
        for key, raw_value in raw_targets.items():
            target_id = str(key or "").strip().lower()
            if not target_id:
                continue
            if isinstance(raw_value, dict):
                target = str(raw_value.get("target") or "").strip()
                label = str(raw_value.get("label") or target_id).strip()
                prefix = str(raw_value.get("prefix") or "").strip()
            else:
                target = str(raw_value or "").strip()
                label = target_id
                prefix = ""
            if target:
                targets[target_id] = {"label": label or target_id, "target": target, "prefix": prefix}
    legacy_target = str(tmux_settings.get("target") or "").strip()
    if legacy_target and "default" not in targets:
        targets["default"] = {
            "label": str(tmux_settings.get("label") or "Default").strip() or "Default",
            "target": legacy_target,
            "prefix": str(tmux_settings.get("prefix") or "").strip(),
        }
    env_target = os.environ.get("MARAS_SWITCHBOARD_TMUX_TARGET", "").strip()
    if env_target and "default" not in targets:
        targets["default"] = {"label": "Default", "target": env_target, "prefix": ""}
    return targets


def _tmux_selected_target_from_settings(settings: dict, requested_target: str | None = None) -> str:
    requested = str(requested_target or "").strip().lower()
    if requested:
        return requested
    tmux_settings = settings.get("tmux")
    if isinstance(tmux_settings, dict):
        selected = str(tmux_settings.get("selected_target") or "").strip().lower()
        if selected:
            return selected
    return "default"


def public_tmux_targets(settings: dict) -> dict[str, object]:
    targets = _tmux_targets_from_settings(settings)
    selected = _tmux_selected_target_from_settings(settings)
    if selected not in targets and targets:
        selected = next(iter(targets))
    return {
        "selected": selected,
        "choices": [
            {
                "id": target_id,
                "label": target["label"],
                "configured": bool(target["target"]),
            }
            for target_id, target in targets.items()
        ],
    }


def _tmux_mark_user_source(text: str, marker: str = TMUX_USER_SOURCE_MARKER) -> str:
    transcript = str(text or "").strip()
    marker = str(marker or "").strip()
    if not marker:
        return transcript
    if transcript == marker or transcript.startswith(f"{marker} "):
        return transcript
    return f"{marker} {transcript}".strip()


async def _send_transcript_to_tmux(text: str, settings: dict, *, target_id: str | None = None) -> dict[str, str]:
    transcript = str(text or "").strip()
    if not transcript:
        raise ValidationError("No transcript to send to tmux")
    targets = _tmux_targets_from_settings(settings)
    selected_target = _tmux_selected_target_from_settings(settings, target_id)
    if selected_target not in targets and selected_target == "default" and targets:
        selected_target = next(iter(targets))
    selected = targets.get(selected_target)
    if not selected:
        raise ValidationError(
            "Missing tmux target. Set tmux.targets in config.json or MARAS_SWITCHBOARD_TMUX_TARGET."
        )
    target = selected["target"]
    prefix = selected["prefix"]
    marked_transcript = _tmux_mark_user_source(transcript)
    payload = f"{prefix} {marked_transcript}".strip() if prefix else marked_transcript

    loop = asyncio.get_running_loop()

    def _run_tmux() -> str:
        subprocess.run(
            ["tmux", "display-message", "-p", "-t", target, "#{pane_id}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        buffer_name = f"maras-switchboard-{uuid.uuid4().hex[:8]}"
        try:
            subprocess.run(
                ["tmux", "set-buffer", "-b", buffer_name, payload],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            subprocess.run(
                ["tmux", "paste-buffer", "-t", target, "-b", buffer_name],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", target, TMUX_ENTER_KEY],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        finally:
            subprocess.run(
                ["tmux", "delete-buffer", "-b", buffer_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        tail = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p", "-S", "-20"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return tail.stdout.strip()

    try:
        pane_tail = await loop.run_in_executor(None, _run_tmux)
    except FileNotFoundError as exc:
        raise ValidationError("tmux command not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValidationError("tmux send timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ValidationError(f"tmux send failed for {target!r}: {detail}") from exc

    LOGGER.info(
        "[bold magenta]↪ tmux %s %s[/bold magenta]  [dim]%s[/dim]",
        selected_target,
        shlex.quote(target),
        _summarize_text(payload),
    )
    return {
        "target_id": selected_target,
        "target": target,
        "payload": payload,
        "pane_tail": pane_tail,
    }


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
    tmux_target: str = ""
    reply_chunks: list[str] = field(default_factory=list)


class VoiceRuntime:
    def __init__(self, store: ConfigStore):
        self.store = store
        self._active_ws: web.WebSocketResponse | None = None
        self._active_ws_lock = asyncio.Lock()
        self._active_ws_supports_playback_accept = False
        self._active_ws_connected_at: float | None = None
        self._active_ws_client_ready_at: float | None = None
        self._active_ws_client_last_seen_at: float | None = None
        self._active_ws_last_accept_timeout_at: float | None = None
        self._active_ws_last_accept_timeout_label: str = ""
        self._active_ws_client_features: dict[str, object] = {}
        self._turn_lock = asyncio.Lock()
        self._playback_push_lock = asyncio.Lock()
        self._pending_playback_accepts: dict[str, asyncio.Future[None]] = {}
        self._playback_request_labels: dict[str, str] = {}
        self._playback_request_clients: dict[str, web.WebSocketResponse] = {}
        self._pending_playback_accepts_lock = asyncio.Lock()
        self._voice_reachable_enabled = VOICE_REACHABLE_DEFAULT_ENABLED
        self._voice_reachable_lock = asyncio.Lock()

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
        elif provider == "xai":
            voice_id = str(
                override.get("voice_id")
                or override.get("xai_voice_id")
                or speaker_voice_ids.get(normalized_speaker)
                or base_tts_settings.get("xai_voice_id")
                or ""
            ).strip()
            if voice_id:
                base_tts_settings["xai_voice_id"] = normalize_xai_tts_voice(voice_id)
            language = str(override.get("language") or override.get("xai_language") or "").strip()
            if language:
                base_tts_settings["xai_language"] = language
            codec = str(override.get("codec") or override.get("xai_output_codec") or "").strip()
            if codec:
                base_tts_settings["xai_output_codec"] = codec
            if "sample_rate" in override or "xai_sample_rate" in override:
                base_tts_settings["xai_sample_rate"] = override.get(
                    "sample_rate",
                    override.get("xai_sample_rate"),
                )
            if "bit_rate" in override or "xai_bit_rate" in override:
                base_tts_settings["xai_bit_rate"] = override.get(
                    "bit_rate",
                    override.get("xai_bit_rate"),
                )
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
        connected_at = time.time() if ws is not None else None
        async with self._active_ws_lock:
            self._active_ws = ws
            self._active_ws_supports_playback_accept = False
            self._active_ws_connected_at = connected_at
            self._active_ws_client_ready_at = None
            self._active_ws_client_last_seen_at = connected_at
            self._active_ws_last_accept_timeout_at = None
            self._active_ws_last_accept_timeout_label = ""
            self._active_ws_client_features = {}
        if ws is not None:
            LOGGER.info("[client] voice websocket connected")

    async def _clear_active_ws(self, ws: web.WebSocketResponse) -> None:
        cleared = False
        async with self._active_ws_lock:
            if self._active_ws is ws:
                self._active_ws = None
                self._active_ws_supports_playback_accept = False
                self._active_ws_connected_at = None
                self._active_ws_client_ready_at = None
                self._active_ws_client_last_seen_at = None
                self._active_ws_last_accept_timeout_at = None
                self._active_ws_last_accept_timeout_label = ""
                self._active_ws_client_features = {}
                cleared = True
        if cleared:
            LOGGER.info("[client] voice websocket disconnected")

    async def _get_active_ws(self) -> web.WebSocketResponse | None:
        async with self._active_ws_lock:
            if self._active_ws is not None and bool(getattr(self._active_ws, "closed", False)):
                return None
            return self._active_ws

    async def _set_active_ws_playback_accept_support(
        self,
        ws: web.WebSocketResponse,
        supports_playback_accept: bool,
        features: dict[str, object] | None = None,
    ) -> None:
        logged = False
        ready_features = dict(features or {})
        ready_features["playback_accept"] = supports_playback_accept
        async with self._active_ws_lock:
            if self._active_ws is ws:
                self._active_ws_supports_playback_accept = supports_playback_accept
                self._active_ws_client_ready_at = time.time()
                self._active_ws_client_last_seen_at = self._active_ws_client_ready_at
                self._active_ws_last_accept_timeout_at = None
                self._active_ws_last_accept_timeout_label = ""
                self._active_ws_client_features = ready_features
                logged = True
        if logged:
            LOGGER.info("[client] ready playback_accept=%s features=%s", supports_playback_accept, ready_features)

    async def _active_ws_requires_playback_accept(self, ws: web.WebSocketResponse) -> bool:
        async with self._active_ws_lock:
            return self._active_ws is ws and self._active_ws_supports_playback_accept

    @staticmethod
    def _playback_features_audio_locked(features: dict[str, object]) -> bool:
        return features.get("playback_unlocked") is False or features.get("paused") is True

    async def _mark_playback_accept_timeout(self) -> None:
        async with self._pending_playback_accepts_lock:
            label = next(iter(self._playback_request_labels.values()), "")
        async with self._active_ws_lock:
            if self._active_ws is not None:
                self._active_ws_supports_playback_accept = False
                self._active_ws_last_accept_timeout_at = time.time()
                self._active_ws_last_accept_timeout_label = label

    async def _require_active_playback_client(self) -> web.WebSocketResponse:
        now = time.time()
        async with self._active_ws_lock:
            ws = self._active_ws
            supports_playback_accept = self._active_ws_supports_playback_accept
            ready_at = self._active_ws_client_ready_at
            features = dict(self._active_ws_client_features)
        if ws is None or bool(getattr(ws, "closed", False)):
            raise ValidationError("No active voice client is connected.")
        if not supports_playback_accept or not ready_at:
            raise ValidationError("Active voice client has not registered playback acceptance.")
        if now - ready_at > PLAYBACK_CLIENT_READY_STALE_SECONDS:
            raise ValidationError("Active voice client is stale; focus or refresh /voice to re-register playback.")
        if self._playback_features_audio_locked(features):
            raise ValidationError("Active voice client is connected but browser audio is locked.")
        return ws

    async def _register_playback_accept(
        self,
        request_id: str,
        ws: web.WebSocketResponse,
    ) -> asyncio.Future[None]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        async with self._pending_playback_accepts_lock:
            self._pending_playback_accepts[request_id] = future
            self._playback_request_clients[request_id] = ws
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
            self._playback_request_clients.pop(request_id, None)
        if future is not None and not future.done():
            future.set_result(None)
        if label:
            LOGGER.info("[client] playback accepted: %s", label)

    async def _reject_playback_accept(self, request_id: str, message: str) -> None:
        async with self._pending_playback_accepts_lock:
            future = self._pending_playback_accepts.pop(request_id, None)
            label = self._playback_request_labels.pop(request_id, "")
            self._playback_request_clients.pop(request_id, None)
        if future is not None and not future.done():
            future.set_exception(ValidationError(message))
        if label:
            LOGGER.warning("[client] playback rejected: %s (%s)", label, message)

    async def _clear_playback_accept(self, request_id: str) -> None:
        async with self._pending_playback_accepts_lock:
            future = self._pending_playback_accepts.pop(request_id, None)
            self._playback_request_labels.pop(request_id, None)
            self._playback_request_clients.pop(request_id, None)
        if future is not None and not future.done():
            future.cancel()

    async def _reject_playback_accepts_for_ws(
        self,
        ws: web.WebSocketResponse,
        message: str,
    ) -> None:
        async with self._pending_playback_accepts_lock:
            request_ids = [
                request_id
                for request_id, request_ws in self._playback_request_clients.items()
                if request_ws is ws
            ]
            pending = [
                (
                    request_id,
                    self._pending_playback_accepts.pop(request_id, None),
                    self._playback_request_labels.pop(request_id, ""),
                )
                for request_id in request_ids
            ]
            for request_id in request_ids:
                self._playback_request_clients.pop(request_id, None)
        for _request_id, future, label in pending:
            if future is not None and not future.done():
                future.set_exception(ValidationError(message))
            if label:
                LOGGER.warning("[client] playback rejected after websocket close: %s (%s)", label, message)

    async def _reject_all_playback_accepts(self, message: str) -> None:
        async with self._pending_playback_accepts_lock:
            pending = [
                (
                    request_id,
                    future,
                    self._playback_request_labels.get(request_id, ""),
                )
                for request_id, future in self._pending_playback_accepts.items()
            ]
            self._pending_playback_accepts.clear()
            self._playback_request_labels.clear()
            self._playback_request_clients.clear()
        for _request_id, future, label in pending:
            if not future.done():
                future.set_exception(ValidationError(message))
            if label:
                LOGGER.warning("[client] playback rejected: %s (%s)", label, message)

    async def playback_status(self) -> dict[str, object]:
        now = time.time()
        async with self._active_ws_lock:
            websocket_connected = self._active_ws is not None and not bool(getattr(self._active_ws, "closed", False))
            connected_at = self._active_ws_connected_at
            ready_at = self._active_ws_client_ready_at
            last_seen_at = self._active_ws_client_last_seen_at
            timeout_at = self._active_ws_last_accept_timeout_at
            timeout_label = self._active_ws_last_accept_timeout_label
            supports_playback_accept = self._active_ws_supports_playback_accept
            features = dict(self._active_ws_client_features)
        async with self._pending_playback_accepts_lock:
            pending_labels = dict(self._playback_request_labels)
            pending_accepts = len(self._pending_playback_accepts)
        stale = bool(
            websocket_connected
            and ready_at is not None
            and now - ready_at > PLAYBACK_CLIENT_READY_STALE_SECONDS
        )
        timeout_recent = bool(
            websocket_connected
            and timeout_at is not None
            and (ready_at is None or ready_at <= timeout_at)
            and now - timeout_at <= PLAYBACK_ACCEPT_TIMEOUT_STALE_SECONDS
        )
        audio_locked = bool(websocket_connected and self._playback_features_audio_locked(features))
        playback_accept = bool(
            websocket_connected
            and supports_playback_accept
            and not stale
            and not audio_locked
            and not timeout_recent
        )
        active_client = bool(websocket_connected and not stale)
        if not websocket_connected:
            client_status = "no_websocket"
            websocket_status = "no_websocket"
        elif stale:
            client_status = "stale_websocket"
            websocket_status = "stale"
        elif pending_accepts:
            client_status = "pending_accept_registered"
            websocket_status = "connected"
        elif timeout_recent:
            client_status = "accept_timed_out"
            websocket_status = "connected"
        elif audio_locked:
            client_status = "audio_locked"
            websocket_status = "connected"
        elif playback_accept:
            client_status = "ready"
            websocket_status = "connected"
        else:
            client_status = "connected_not_ready"
            websocket_status = "connected"
        return {
            "active_voice_client": active_client,
            "playback_accept": playback_accept,
            "client_status": client_status,
            "websocket_status": websocket_status,
            "websocket_connected": websocket_connected,
            "connected_at": _format_wall_time(connected_at),
            "connected_seconds": round(now - connected_at, 3) if connected_at else None,
            "client_ready_at": _format_wall_time(ready_at),
            "client_ready_seconds": round(now - ready_at, 3) if ready_at else None,
            "client_last_seen_at": _format_wall_time(last_seen_at),
            "client_last_seen_seconds": round(now - last_seen_at, 3) if last_seen_at else None,
            "features": features,
            "pending_playback_accepts": pending_accepts,
            "pending_playback_labels": list(pending_labels.values()),
            "last_playback_accept_timeout_at": _format_wall_time(timeout_at),
            "last_playback_accept_timeout_seconds": round(now - timeout_at, 3) if timeout_recent and timeout_at else None,
            "last_playback_accept_timeout_label": timeout_label if timeout_recent else "",
        }

    async def voice_reachable_status(self) -> dict[str, object]:
        async with self._voice_reachable_lock:
            enabled = self._voice_reachable_enabled
        playback = await self.playback_status()
        return {
            "enabled": enabled,
            "mode": "on" if enabled else "off",
            "active_voice_client": playback["active_voice_client"],
            "playback_accept": playback["playback_accept"],
            "client_status": playback["client_status"],
            "websocket_status": playback["websocket_status"],
            "websocket_connected": playback["websocket_connected"],
        }

    async def set_voice_reachable(self, enabled: bool) -> dict[str, object]:
        async with self._voice_reachable_lock:
            self._voice_reachable_enabled = bool(enabled)
        if not enabled:
            await self._reject_all_playback_accepts("Voice reachable mode was turned off.")
        return await self.voice_reachable_status()

    async def voice_reachable_enabled(self) -> bool:
        async with self._voice_reachable_lock:
            return self._voice_reachable_enabled

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
        async with self._playback_push_lock:
            await self._push_audio_to_active_ws_locked(
                ws,
                audio,
                audio_mime_type=audio_mime_type,
            )

    async def _push_audio_to_active_ws_locked(
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
            accept_future = await self._register_playback_accept(request_id, ws)
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
                LOGGER.info("[client] waiting for playback acceptance: %s", request_id)
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

        await self._require_active_playback_client()
        synthesizer, audio_mime_type = self._resolve_synthesizer(
            settings,
            speaker_name=resolved_speaker,
        )
        async with self._turn_lock:
            audio = await synthesizer.synthesize(spoken_text, preset_name=reply_style)
            if not audio:
                raise ValidationError("Speech synthesis returned no audio.")
        ws = await self._require_active_playback_client()
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
        await self._require_active_playback_client()

        silence_duration = max(float(duration_seconds), 0.0)
        if silence_duration <= 0:
            return {"ok": True, "audio_bytes": 0, "duration_seconds": 0.0}

        audio = self._build_silence_wav(silence_duration)
        ws = await self._require_active_playback_client()
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
            await self._mark_playback_accept_timeout()
            LOGGER.warning(
                "Speak request timed out waiting for playback acceptance: %s",
                await self.playback_status(),
            )
            return web.json_response(
                {
                    "ok": False,
                    "error": (
                        "Timed out waiting for the active voice client to accept playback."
                    ),
                    "timeout_seconds": timeout_seconds,
                    "voice_client": await self.playback_status(),
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
            stt_info = _stt_summary(turn_stt_settings)
            LOGGER.info(
                "STT runtime backend=%s model=%s language=%s",
                stt_info["backend"],
                stt_info["model"],
                stt_info["language"],
            )
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
        pending_turn_commit_meta: dict[str, object] | None = None
        audio_turn_queue: asyncio.Queue[tuple[bytes, asyncio.Event, dict[str, object] | None]] = asyncio.Queue()
        active_abort_events: set[asyncio.Event] = set()

        def track_abort_event(event: asyncio.Event) -> None:
            active_abort_events.add(event)

        def untrack_abort_event(event: asyncio.Event) -> None:
            active_abort_events.discard(event)

        async def process_text(
            text: str,
            task_abort_event: asyncio.Event,
            *,
            input_source: str,
            turn: VoiceTurnMetrics | None = None,
            send_thinking: bool = True,
        ) -> None:
            turn = turn or VoiceTurnMetrics()
            if send_thinking:
                await ws.send_json({"status": "thinking"})
            turn.transcript = str(text or "").strip()
            if task_abort_event.is_set():
                return
            if not turn.transcript:
                await ws.send_json({"status": "idle"})
                return

            if input_source == "typed":
                LOGGER.info("[bold cyan]⌨ %s[/bold cyan]", _summarize_text(turn.transcript))
            else:
                LOGGER.info(
                    "[bold cyan]🎤 %s[/bold cyan]  [dim]stt=%s  audio=%s[/dim]",
                    _summarize_text(turn.transcript),
                    _format_elapsed(turn.stt_seconds),
                    _format_elapsed(turn.speech_duration_seconds),
                )
            await ws.send_json({"type": "transcript", "text": turn.transcript})
            await ws.send_json({"type": "reply-text", "text": "", "replace": True})

            voice_reachable_command = _voice_reachable_command(turn.transcript)
            if voice_reachable_command:
                if voice_reachable_command == "on":
                    voice_reachable = await self.set_voice_reachable(True)
                elif voice_reachable_command == "off":
                    voice_reachable = await self.set_voice_reachable(False)
                elif voice_reachable_command == "toggle":
                    voice_reachable = await self.set_voice_reachable(not await self.voice_reachable_enabled())
                else:
                    voice_reachable = await self.voice_reachable_status()
                reply = _format_voice_reachable_status(voice_reachable)
                await ws.send_json({"type": "voice-reachable", "voice_reachable": voice_reachable})
                await ws.send_json({"type": "reply-text", "text": reply, "replace": True})
                await ws.send_json({"status": "idle"})
                return

            if input_source == "tmux":
                sent = await _send_transcript_to_tmux(
                    turn.transcript,
                    settings,
                    target_id=turn.tmux_target,
                )
                await ws.send_json({"type": "tmux-sent", "text": sent["payload"], **sent})
                await ws.send_json({"status": "idle"})
                return

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
                nonlocal speaking_started, buffered_reply_text
                chunk_text = clean_text.strip()
                if _should_skip_spoken_reply(chunk_text):
                    LOGGER.info(
                        "[dim]skipping empty spoken reply chunk: %s[/dim]",
                        _summarize_text(chunk_text),
                    )
                    return
                if tts_disabled:
                    await ws.send_json({"type": "reply-text", "text": chunk_text, "append": True})
                    if turn.ttft_seconds is None:
                        turn.ttft_seconds = time.perf_counter() - reply_started_at
                    turn.reply_chunks.append(_summarize_text(chunk_text))
                    LOGGER.info(
                        "[dim]tts disabled, reply not spoken: %s[/dim]",
                        _summarize_text(chunk_text),
                    )
                    return
                if not await self.voice_reachable_enabled():
                    await ws.send_json({"type": "reply-text", "text": chunk_text, "append": True})
                    if turn.ttft_seconds is None:
                        turn.ttft_seconds = time.perf_counter() - reply_started_at
                    turn.reply_chunks.append(_summarize_text(chunk_text))
                    LOGGER.info(
                        "[dim]voice reachable off, automatic speech skipped: %s[/dim]",
                        _summarize_text(chunk_text),
                    )
                    return
                spoken_chunk_text = _spoken_voice_reachable_text(chunk_text)
                if not spoken_chunk_text:
                    await ws.send_json({"type": "reply-text", "text": chunk_text, "append": True})
                    if turn.ttft_seconds is None:
                        turn.ttft_seconds = time.perf_counter() - reply_started_at
                    turn.reply_chunks.append(_summarize_text(chunk_text))
                    LOGGER.info(
                        "[dim]tiny automatic speech skipped: %s[/dim]",
                        _summarize_text(chunk_text),
                    )
                    return
                if self._tts_requires_buffered_reply(settings, speaker_name=reply_speaker):
                    if turn.ttft_seconds is None:
                        turn.ttft_seconds = time.perf_counter() - reply_started_at
                    buffered_reply_text = (
                        f"{buffered_reply_text} {spoken_chunk_text}".strip()
                        if buffered_reply_text
                        else spoken_chunk_text
                    )
                    await ws.send_json({"type": "reply-text", "text": chunk_text, "append": True})
                    return
                current_synthesizer, current_audio_mime_type = resolve_chunk_synthesizer(reply_speaker)
                if turn.ttft_seconds is None:
                    turn.ttft_seconds = time.perf_counter() - reply_started_at
                tts_started_at = time.perf_counter()
                audio = await current_synthesizer.synthesize(spoken_chunk_text, preset_name=reply_style)
                tts_elapsed = time.perf_counter() - tts_started_at
                turn.total_tts_seconds += tts_elapsed
                if not audio:
                    return
                turn.reply_chunks.append(_summarize_text(spoken_chunk_text))
                if turn.first_tts_seconds is None:
                    turn.first_tts_seconds = tts_elapsed
                if not speaking_started:
                    speaking_started = True
                    request_id = uuid.uuid4().hex
                    await self._remember_playback_request(request_id, spoken_chunk_text)
                    speaking_payload = {"status": "speaking"}
                    speaking_payload["source"] = "voice_reply"
                    speaking_payload["request_id"] = request_id
                    if current_audio_mime_type != "audio/mpeg":
                        speaking_payload["audio_mime_type"] = current_audio_mime_type
                    await ws.send_json(speaking_payload)
                await ws.send_json({"type": "reply-text", "text": chunk_text, "append": True})
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

            async for chunk in conversation_agent.stream_reply(turn.transcript, task_abort_event):
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
                    await ws.send_json({"type": "reply-text", "text": buffered_reply_text, "append": True})
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

        async def process_audio(
            audio_bytes: bytes,
            task_abort_event: asyncio.Event,
            *,
            turn_commit_meta: dict[str, object] | None = None,
        ) -> None:
            loop = asyncio.get_running_loop()
            turn = VoiceTurnMetrics()
            started_at = time.time()
            committed_at = (
                float(turn_commit_meta.get("committed_at"))
                if turn_commit_meta and turn_commit_meta.get("committed_at")
                else started_at
            )
            queued_at = (
                float(turn_commit_meta.get("queued_at"))
                if turn_commit_meta and turn_commit_meta.get("queued_at")
                else committed_at
            )
            tmux_target = str(turn_commit_meta.get("tmux_target") or "").strip() if turn_commit_meta else ""
            LOGGER.info(
                "[%s] turn started committed_at=%s queued_at=%s started_at=%s queue_wait=%s target=%s",
                turn.turn_id,
                _format_wall_time(committed_at),
                _format_wall_time(queued_at),
                _format_wall_time(started_at),
                _format_elapsed(max(started_at - queued_at, 0.0)),
                tmux_target or "-",
            )
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
            transcribed_at = time.time()
            text = result.text.strip()
            duration = float(getattr(result, "duration_seconds", 0.0) or 0.0)
            turn.speech_duration_seconds = duration
            stt_info = _stt_summary(turn_stt_settings)
            LOGGER.info(
                "[%s] STT transcript backend=%s model=%s language=%s committed_at=%s transcribed_at=%s target=%s text=%r",
                turn.turn_id,
                stt_info["backend"],
                stt_info["model"],
                stt_info["language"],
                _format_wall_time(committed_at),
                _format_wall_time(transcribed_at),
                tmux_target or "-",
                _summarize_text(text, limit=240),
            )
            if task_abort_event.is_set():
                return
            if not text:
                LOGGER.info(
                    "[%s] turn dropped state=empty_transcript committed_at=%s transcribed_at=%s target=%s speech=%s stt=%s",
                    turn.turn_id,
                    _format_wall_time(committed_at),
                    _format_wall_time(transcribed_at),
                    tmux_target or "-",
                    _format_elapsed(duration),
                    _format_elapsed(turn.stt_seconds),
                )
                await ws.send_json({"status": "idle"})
                return
            audio_settings = settings.get("audio", {})
            min_duration = max(float(audio_settings.get("min_speech_ms", 350) or 350) / 1000.0, 0.0)
            try:
                min_words = int(audio_settings.get("min_transcript_words", 1) or 1)
            except (TypeError, ValueError):
                min_words = 1
            min_words = max(min_words, 1)
            if should_drop_voice_transcript(
                text,
                duration,
                min_duration=min_duration,
                min_words=min_words,
            ):
                LOGGER.debug(
                    "[%s] dropped: %s turn dropped state=filtered committed_at=%s transcribed_at=%s target=%s speech=%s min_words=%s",
                    turn.turn_id,
                    _summarize_text(text),
                    _format_wall_time(committed_at),
                    _format_wall_time(transcribed_at),
                    tmux_target or "-",
                    _format_elapsed(duration),
                    min_words,
                )
                await ws.send_json({"status": "idle"})
                return

            turn.transcript = text
            input_source = "tmux" if bool(turn_commit_meta and turn_commit_meta.get("tmux_only")) else "voice"
            if turn_commit_meta:
                turn.tmux_target = str(turn_commit_meta.get("tmux_target") or "").strip()
            await process_text(
                turn.transcript,
                task_abort_event,
                input_source=input_source,
                turn=turn,
                send_thinking=False,
            )
            delivered_at = time.time()
            LOGGER.info(
                "[%s] turn delivered input_source=%s target=%s committed_at=%s transcribed_at=%s delivered_at=%s",
                turn.turn_id,
                input_source,
                turn.tmux_target or "-",
                _format_wall_time(committed_at),
                _format_wall_time(transcribed_at),
                _format_wall_time(delivered_at),
            )

        async def cancel_active_task(*, send_idle: bool) -> None:
            nonlocal active_task
            for event in tuple(active_abort_events):
                event.set()
            while not audio_turn_queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    audio_turn_queue.get_nowait()
                    audio_turn_queue.task_done()
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
            manage_active_task: bool = True,
        ) -> None:
            nonlocal active_task
            track_abort_event(task_abort_event)
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
                    untrack_abort_event(task_abort_event)
                    if manage_active_task and active_task is asyncio.current_task():
                        active_task = None

        async def run_audio_turn_queue() -> None:
            nonlocal active_task
            try:
                while True:
                    audio_bytes, task_abort_event, turn_commit_meta = await audio_turn_queue.get()
                    try:
                        await run_audio_task(
                            audio_bytes,
                            task_abort_event,
                            turn_commit_meta=turn_commit_meta,
                            manage_active_task=False,
                        )
                    finally:
                        audio_turn_queue.task_done()
            except asyncio.CancelledError:
                raise
            finally:
                if active_task is asyncio.current_task():
                    active_task = None

        def ensure_audio_turn_worker() -> None:
            nonlocal active_task
            if active_task is None or active_task.done():
                active_task = asyncio.create_task(run_audio_turn_queue())

        async def run_text_task(text: str, task_abort_event: asyncio.Event, *, tmux_target: str = "") -> None:
            nonlocal active_task
            track_abort_event(task_abort_event)
            async with self._turn_lock:
                try:
                    turn = VoiceTurnMetrics(tmux_target=tmux_target)
                    await process_text(text, task_abort_event, input_source="tmux" if tmux_target else "typed", turn=turn)
                except ValidationError as exc:
                    await ws.send_json({"status": "idle", "error": str(exc)})
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pragma: no cover - defensive runtime guard
                    LOGGER.exception("Typed voice processing failed")
                    await ws.send_json({"status": "idle", "error": str(exc)})
                finally:
                    untrack_abort_event(task_abort_event)
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
                        if not isinstance(features, dict):
                            features = {}
                        await self._set_active_ws_playback_accept_support(
                            ws,
                            bool(features.get("playback_accept")),
                            features,
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
                    elif msg_type == "text-input":
                        text = str(payload.get("text") or "").strip()
                        if not text:
                            continue
                        tmux_target = str(payload.get("tmux_target") or "").strip()
                        await cancel_active_task(send_idle=False)
                        text_abort_event = asyncio.Event()
                        active_task = asyncio.create_task(run_text_task(text, text_abort_event, tmux_target=tmux_target))
                    elif msg_type == "turn-commit":
                        pending_turn_commit_meta = {
                            "reason": str(payload.get("reason") or "").strip(),
                            "committed_at": time.time(),
                            "speech_ms": int(payload.get("speech_ms") or 0),
                            "silence_ms": int(payload.get("silence_ms") or 0),
                            "threshold_db": payload.get("threshold_db"),
                            "level_db": payload.get("level_db"),
                            "wait_after_speak_ms": int(payload.get("wait_after_speak_ms") or 0),
                            "tmux_only": bool(payload.get("tmux_only")),
                            "tmux_target": str(payload.get("tmux_target") or "").strip(),
                        }
                    continue
                if message.type != WSMsgType.BINARY:
                    continue
                if len(message.data) < 1600:
                    continue
                audio_abort_event = asyncio.Event()
                turn_commit_meta = pending_turn_commit_meta
                pending_turn_commit_meta = None
                if turn_commit_meta is None:
                    turn_commit_meta = {}
                turn_commit_meta["queued_at"] = time.time()
                await audio_turn_queue.put(
                    (
                        message.data,
                        audio_abort_event,
                        turn_commit_meta,
                    )
                )
                LOGGER.info(
                    "[client] audio turn queued pending=%s reason=%s target=%s",
                    audio_turn_queue.qsize(),
                    str(turn_commit_meta.get("reason") or "-"),
                    str(turn_commit_meta.get("tmux_target") or "").strip() or "-",
                )
                ensure_audio_turn_worker()
        finally:
            await cancel_active_task(send_idle=False)
            await self._reject_playback_accepts_for_ws(
                ws,
                "The active voice client disconnected before playback."
            )
            await self._clear_active_ws(ws)
        return ws
