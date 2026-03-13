from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return float(value)


@dataclass(slots=True)
class VoiceServerConfig:
    http_host: str
    http_port: int
    ws_host: str
    ws_port: int
    static_dir: Path
    ui_title: str

    gateway_url: str
    gateway_token: str
    gateway_session_key: str | None
    gateway_message_channel: str | None
    gateway_model: str | None

    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    whisper_language: str

    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model: str
    tts_timeout_seconds: float

    require_send_phrase: bool
    send_phrase: str
    auto_silence_drop_seconds: float

    @classmethod
    def from_env(cls) -> "VoiceServerConfig":
        static_dir = Path(__file__).with_name("static")
        return cls(
            http_host=os.environ.get("OPENCLAW_VOICE_HTTP_HOST", "127.0.0.1"),
            http_port=_env_int("OPENCLAW_VOICE_HTTP_PORT", 8765),
            ws_host=os.environ.get("OPENCLAW_VOICE_WS_HOST", "127.0.0.1"),
            ws_port=_env_int("OPENCLAW_VOICE_WS_PORT", 8766),
            static_dir=static_dir,
            ui_title=os.environ.get("OPENCLAW_VOICE_UI_TITLE", "OpenClaw Voice"),
            gateway_url=os.environ.get(
                "OPENCLAW_VOICE_GATEWAY_URL",
                "http://127.0.0.1:18789/v1/chat/completions",
            ),
            gateway_token=os.environ.get("OPENCLAW_VOICE_GATEWAY_TOKEN", ""),
            gateway_session_key=os.environ.get("OPENCLAW_VOICE_GATEWAY_SESSION_KEY") or None,
            gateway_message_channel=os.environ.get("OPENCLAW_VOICE_GATEWAY_MESSAGE_CHANNEL") or None,
            gateway_model=os.environ.get("OPENCLAW_VOICE_GATEWAY_MODEL") or None,
            whisper_model=os.environ.get("OPENCLAW_VOICE_WHISPER_MODEL", "large-v3"),
            whisper_device=os.environ.get("OPENCLAW_VOICE_WHISPER_DEVICE", "cuda"),
            whisper_compute_type=os.environ.get(
                "OPENCLAW_VOICE_WHISPER_COMPUTE_TYPE",
                "float16",
            ),
            whisper_language=os.environ.get("OPENCLAW_VOICE_WHISPER_LANG", "de"),
            elevenlabs_api_key=os.environ.get("OPENCLAW_VOICE_ELEVENLABS_API_KEY", ""),
            elevenlabs_voice_id=os.environ.get("OPENCLAW_VOICE_ELEVENLABS_VOICE_ID", ""),
            elevenlabs_model=os.environ.get(
                "OPENCLAW_VOICE_ELEVENLABS_MODEL",
                "eleven_flash_v2_5",
            ),
            tts_timeout_seconds=_env_float(
                "OPENCLAW_VOICE_TTS_TIMEOUT_SECONDS",
                12.0,
            ),
            require_send_phrase=_env_bool(
                "OPENCLAW_VOICE_REQUIRE_SEND_PHRASE",
                True,
            ),
            send_phrase=os.environ.get("OPENCLAW_VOICE_SEND_PHRASE", "fertig").strip() or "fertig",
            auto_silence_drop_seconds=_env_float(
                "OPENCLAW_VOICE_AUTO_SILENCE_DROP_SECONDS",
                3.5,
            ),
        )

    def validate(self) -> None:
        missing = []
        if not self.gateway_token:
            missing.append("OPENCLAW_VOICE_GATEWAY_TOKEN")
        if not self.elevenlabs_api_key:
            missing.append("OPENCLAW_VOICE_ELEVENLABS_API_KEY")
        if not self.elevenlabs_voice_id:
            missing.append("OPENCLAW_VOICE_ELEVENLABS_VOICE_ID")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required environment variables: {joined}")

