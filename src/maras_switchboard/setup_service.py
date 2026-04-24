from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
from typing import Any

from .agents import validate_hermes_connection
from .catalog import (
    APP_VERSION_LABEL,
    DEFAULT_HERMES_ROOT,
    DEFAULT_LOCAL_GATEWAY_URL,
    DEFAULT_REMOTE_WHISPER_ENDPOINT_PATH,
    DEFAULT_REMOTE_WHISPER_HOST_ALIAS,
    DEFAULT_REMOTE_WHISPER_MODEL,
    DEFAULT_REMOTE_WHISPER_PORT,
    DEFAULT_VOICE_SESSION_KEY,
    ELEVENLABS_PRESETS,
    HOLD_TO_TALK_SHORTCUT_LABEL,
    SUPPORTED_AGENT_BACKENDS,
    SUPPORTED_STT_BACKENDS,
    SUPPORTED_TTS_PROVIDERS,
    normalize_agent_backend,
)
from .config_store import ConfigStore
from .errors import ValidationError
from .gateway import normalize_gateway_url, validate_gateway_connection
from .installer import module_available
from .stt import normalize_stt_device, validate_stt_selection as validate_stt_selection_step
from .tts import (
    SUPERTONIC_DEFAULT_LANGUAGE,
    SUPERTONIC_DEFAULT_SPEED,
    SUPERTONIC_DEFAULT_TOTAL_STEPS,
    SUPERTONIC_DEFAULT_VOICE,
    SUPERTONIC_SUPPORTED_LANGUAGES,
    SUPERTONIC_SUPPORTED_VOICES,
    detect_supertonic_python_path,
    list_edge_voices,
    list_elevenlabs_voices,
    normalize_elevenlabs_preset,
    normalize_supertonic_language,
    normalize_supertonic_speed,
    normalize_supertonic_total_steps,
    normalize_supertonic_voice,
    resolve_supertonic_python_path,
    validate_edge_voice,
    validate_elevenlabs_api_key as validate_elevenlabs_api_key_step,
    validate_elevenlabs_voice as validate_elevenlabs_voice_step,
    validate_supertonic_voice as validate_supertonic_voice_step,
)


def _first_env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.environ.get(key)
        if value not in (None, ""):
            return str(value)
    return default


class SetupService:
    def __init__(self, store: ConfigStore):
        self.store = store

    @staticmethod
    def _resolve_ssh_hostname(alias: str) -> str:
        text = str(alias or "").strip()
        if not text:
            return ""
        try:
            completed = subprocess.run(
                ["ssh", "-G", text],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return ""
        if completed.returncode != 0:
            return ""
        for line in completed.stdout.splitlines():
            key, _, value = line.partition(" ")
            if key.lower() != "hostname":
                continue
            return value.strip()
        return ""

    @staticmethod
    def _host_is_resolvable(host: str) -> bool:
        text = str(host or "").strip()
        if not text:
            return False
        try:
            socket.getaddrinfo(text, None)
        except socket.gaierror:
            return False
        return True

    def _default_remote_whisper_hint(self, settings: dict[str, Any]) -> dict[str, str]:
        env_url = str(
            _first_env(
                "MARAS_SWITCHBOARD_REMOTE_WHISPER_ENDPOINT_URL",
                "AGENTIC_SWITCHBOARD_REMOTE_WHISPER_ENDPOINT_URL",
                "MARAS_SWITCHBOARD_MAC_WHISPER_ENDPOINT_URL",
                "AGENTIC_SWITCHBOARD_MAC_WHISPER_ENDPOINT_URL",
            )
        ).strip()
        env_model = str(
            _first_env(
                "MARAS_SWITCHBOARD_REMOTE_WHISPER_ENDPOINT_MODEL",
                "AGENTIC_SWITCHBOARD_REMOTE_WHISPER_ENDPOINT_MODEL",
                "MARAS_SWITCHBOARD_MAC_WHISPER_ENDPOINT_MODEL",
                "AGENTIC_SWITCHBOARD_MAC_WHISPER_ENDPOINT_MODEL",
            )
        ).strip()
        host_alias = str(
            _first_env(
                "MARAS_SWITCHBOARD_REMOTE_WHISPER_HOST_ALIAS",
                "AGENTIC_SWITCHBOARD_REMOTE_WHISPER_HOST_ALIAS",
                "MARAS_SWITCHBOARD_MAC_WHISPER_SSH_ALIAS",
                "AGENTIC_SWITCHBOARD_MAC_WHISPER_SSH_ALIAS",
                default=DEFAULT_REMOTE_WHISPER_HOST_ALIAS,
            )
        ).strip()
        resolved_host = self._resolve_ssh_hostname(host_alias) if host_alias else ""
        if resolved_host == host_alias and not self._host_is_resolvable(resolved_host):
            resolved_host = ""
        resolved_url = (
            f"http://{resolved_host}:{DEFAULT_REMOTE_WHISPER_PORT}{DEFAULT_REMOTE_WHISPER_ENDPOINT_PATH}"
            if resolved_host
            else ""
        )
        saved_url = str(settings["stt"].get("whisper_endpoint_url") or "").strip()
        saved_model = str(settings["stt"].get("whisper_endpoint_model") or "").strip()
        return {
            "url": env_url or resolved_url or saved_url,
            "model": env_model or saved_model or DEFAULT_REMOTE_WHISPER_MODEL,
            "host_alias": host_alias,
        }

    @staticmethod
    def _fingerprint_secret(value: str) -> str:
        text = value.strip()
        if not text:
            return ""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _snapshot_matches(current: dict[str, Any], expected: dict[str, Any]) -> bool:
        return bool(expected) and current == expected

    @staticmethod
    def _config_hash(value: dict[str, Any]) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _validated_config_matches(self, current: dict[str, Any], section_state: dict[str, Any]) -> bool:
        config_hash = str(section_state.get("config_hash") or "").strip()
        if config_hash:
            return config_hash == self._config_hash(current)
        legacy_snapshot = section_state.get("snapshot")
        if isinstance(legacy_snapshot, dict):
            return self._snapshot_matches(current, legacy_snapshot)
        return False

    def validate_windows_client(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.store.update_config(
            {
                "windows_client": {},
                "validation": {
                    "windows_client": {
                        "config_hash": self._config_hash({}),
                    }
                },
            }
        )
        return {"ok": True}

    def _stt_runtime_ready(self, settings: dict[str, Any]) -> bool:
        stt = settings["stt"]
        backend_id = str(stt.get("default_backend") or "").strip()
        enabled_backends = stt.get("enabled_backends") or []
        if not backend_id or backend_id not in enabled_backends:
            return False
        backend = SUPPORTED_STT_BACKENDS.get(backend_id)
        if backend is None:
            return False
        if backend_id == "whisper" and str(stt.get("whisper_endpoint_url") or "").strip():
            return True
        return module_available(backend["import_name"])

    def _tts_runtime_ready(self, settings: dict[str, Any]) -> bool:
        tts = settings["tts"]
        provider_id = str(tts.get("default_provider") or "").strip()
        enabled_providers = tts.get("enabled_providers") or []
        if not provider_id or provider_id not in enabled_providers:
            return False
        provider = SUPPORTED_TTS_PROVIDERS.get(provider_id)
        if provider is None:
            return False
        if provider_id == "disabled":
            return True
        if provider["import_name"] and not module_available(provider["import_name"]):
            return False
        if provider_id == "edge":
            return bool(str(tts.get("edge_voice") or "").strip())
        if provider_id == "elevenlabs":
            return bool(
                str(settings["secrets"].get("elevenlabs_api_key") or "").strip()
                and str(tts.get("elevenlabs_voice_id") or "").strip()
                and str(tts.get("elevenlabs_model") or "").strip()
            )
        if provider_id == "supertonic":
            return bool(
                str(tts.get("supertonic_python_path") or "").strip()
                and str(tts.get("supertonic_voice") or "").strip()
                and str(tts.get("supertonic_language") or "").strip()
            )
        return False

    def _gateway_runtime_ready(self, settings: dict[str, Any]) -> bool:
        gateway = settings["gateway"]
        secrets = settings["secrets"]
        return bool(
            str(gateway.get("url") or "").strip()
            and str(gateway.get("model") or "").strip()
            and str(secrets.get("gateway_token") or "").strip()
        )

    def _hermes_runtime_ready(self, settings: dict[str, Any]) -> bool:
        agent = settings.get("agent") or {}
        hermes_root = Path(
            str(agent.get("hermes_root") or DEFAULT_HERMES_ROOT).strip() or DEFAULT_HERMES_ROOT
        ).expanduser()
        if not hermes_root.exists():
            return False
        repo_marker_exists = (hermes_root / "run_agent.py").exists()
        python_candidates = [
            hermes_root / "venv" / "bin" / "python",
            hermes_root / "venv" / "bin" / "python3",
            hermes_root.parent / ".hermes" / "venv" / "bin" / "python",
            hermes_root.parent / ".hermes" / "venv" / "bin" / "python3",
            Path.home() / ".hermes" / "venv" / "bin" / "python",
            Path.home() / ".hermes" / "venv" / "bin" / "python3",
        ]
        python_exists = any(candidate.exists() for candidate in python_candidates)
        local_venv_exists = any(candidate.exists() for candidate in python_candidates[:2])
        return python_exists and (repo_marker_exists or local_venv_exists)

    def _conversation_runtime_ready(self, settings: dict[str, Any]) -> bool:
        backend = normalize_agent_backend((settings.get("agent") or {}).get("backend"))
        if backend == "hermes":
            return self._hermes_runtime_ready(settings)
        return self._gateway_runtime_ready(settings)

    def _status(self, settings: dict[str, Any]) -> dict[str, bool]:
        validation = settings["validation"]
        stt_modules_ready = all(
            (
                backend_id == "whisper" and bool(str(settings["stt"].get("whisper_endpoint_url") or "").strip())
            )
            or module_available(SUPPORTED_STT_BACKENDS[backend_id]["import_name"])
            for backend_id in settings["stt"]["enabled_backends"]
            if backend_id in SUPPORTED_STT_BACKENDS
        )
        stt_snapshot = {
            "enabled_backends": settings["stt"]["enabled_backends"],
            "default_backend": settings["stt"]["default_backend"],
            "language": settings["stt"]["language"],
            "device": settings["stt"]["device"],
            "compute_type": settings["stt"]["compute_type"],
            "whisper_endpoint_url": settings["stt"].get("whisper_endpoint_url", ""),
            "whisper_endpoint_model": settings["stt"].get("whisper_endpoint_model", ""),
            "backend_models": settings["stt"]["backend_models"],
        }
        stt_ready = bool(
            settings["stt"]["enabled_backends"]
            and settings["stt"]["default_backend"] in settings["stt"]["enabled_backends"]
            and stt_modules_ready
            and self._validated_config_matches(stt_snapshot, validation["stt"])
        )
        tts_modules_ready = all(
            module_available(SUPPORTED_TTS_PROVIDERS[provider_id]["import_name"])
            for provider_id in settings["tts"]["enabled_providers"]
            if provider_id in SUPPORTED_TTS_PROVIDERS
        )
        tts_snapshot = {
            "enabled_providers": settings["tts"]["enabled_providers"],
            "default_provider": settings["tts"]["default_provider"],
        }
        tts_selection_ready = bool(
            settings["tts"]["enabled_providers"]
            and settings["tts"]["default_provider"] in settings["tts"]["enabled_providers"]
            and tts_modules_ready
            and self._validated_config_matches(tts_snapshot, validation["tts"])
        )
        edge_snapshot = {
            "voice": settings["tts"]["edge_voice"],
            "rate": settings["tts"]["edge_rate"],
        }
        edge_ready = "edge" not in settings["tts"]["enabled_providers"] or self._validated_config_matches(
            edge_snapshot,
            validation["edge"],
        )

        api_key_fingerprint = self._fingerprint_secret(settings["secrets"]["elevenlabs_api_key"])
        eleven_key_ready = "elevenlabs" not in settings["tts"]["enabled_providers"] or bool(
            api_key_fingerprint
            and api_key_fingerprint == validation["eleven_key"]["api_key_fingerprint"]
        )
        eleven_voice_snapshot = {
            "voice_id": settings["tts"]["elevenlabs_voice_id"],
            "model_id": settings["tts"]["elevenlabs_model"],
            "preset": settings["tts"]["elevenlabs_preset"],
        }
        eleven_voice_ready = "elevenlabs" not in settings["tts"]["enabled_providers"] or bool(
            api_key_fingerprint
            and api_key_fingerprint == validation["eleven_voice"]["api_key_fingerprint"]
            and self._validated_config_matches(eleven_voice_snapshot, validation["eleven_voice"])
        )
        supertonic_snapshot = {
            "python_path": settings["tts"].get("supertonic_python_path", ""),
            "voice": settings["tts"].get("supertonic_voice", ""),
            "language": settings["tts"].get("supertonic_language", ""),
            "total_steps": settings["tts"].get("supertonic_total_steps", SUPERTONIC_DEFAULT_TOTAL_STEPS),
            "speed": settings["tts"].get("supertonic_speed", SUPERTONIC_DEFAULT_SPEED),
        }
        supertonic_ready = "supertonic" not in settings["tts"]["enabled_providers"] or self._validated_config_matches(
            supertonic_snapshot,
            validation.get("supertonic", {}),
        )

        gateway_token_fingerprint = self._fingerprint_secret(settings["secrets"]["gateway_token"])
        gateway_snapshot = {
            "url": settings["gateway"]["url"],
            "model": settings["gateway"]["model"],
            "session_key": settings["gateway"]["session_key"],
        }
        gateway_ready = bool(
            settings["gateway"]["url"]
            and gateway_token_fingerprint
            and gateway_token_fingerprint == validation["gateway"]["token_fingerprint"]
            and self._validated_config_matches(gateway_snapshot, validation["gateway"])
        )
        hermes_snapshot = {
            "hermes_root": str(
                (settings.get("agent") or {}).get("hermes_root") or DEFAULT_HERMES_ROOT
            ).strip()
            or DEFAULT_HERMES_ROOT,
        }
        hermes_ready = self._validated_config_matches(hermes_snapshot, validation["hermes"])

        runtime_ready = all(
            [
                self._conversation_runtime_ready(settings),
                self._stt_runtime_ready(settings),
                self._tts_runtime_ready(settings),
            ]
        )
        return {
            "gateway_ready": gateway_ready,
            "hermes_ready": hermes_ready,
            "stt_ready": stt_ready,
            "tts_selection_ready": tts_selection_ready,
            "edge_ready": edge_ready,
            "eleven_key_ready": eleven_key_ready,
            "eleven_voice_ready": eleven_voice_ready,
            "supertonic_ready": supertonic_ready,
            "runtime_ready": runtime_ready,
        }

    def state(self) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        remote_whisper_hint = self._default_remote_whisper_hint(settings)
        return {
            "version_label": APP_VERSION_LABEL,
            "message": (
                "Each setup step is validated immediately before it is saved. "
                "The app only reports success after the selected providers, keys, "
                "models, and voices have passed validation."
            ),
            "saved": self.store.public_setup_state(),
            "status": self._status(settings),
            "catalog": {
                "agent_backends": list(SUPPORTED_AGENT_BACKENDS.values()),
                "stt_backends": list(SUPPORTED_STT_BACKENDS.values()),
                "tts_providers": list(SUPPORTED_TTS_PROVIDERS.values()),
                "supertonic_languages": [
                    {"id": language_id, "label": label}
                    for language_id, label in SUPERTONIC_SUPPORTED_LANGUAGES.items()
                ],
                "supertonic_voices": [
                    {"id": voice_id, "label": label}
                    for voice_id, label in SUPERTONIC_SUPPORTED_VOICES.items()
                ],
                "elevenlabs_presets": [
                    {"id": preset_id, "label": preset["label"]}
                    for preset_id, preset in ELEVENLABS_PRESETS.items()
                ],
            },
            "hints": {
                "default_voice_session_key": DEFAULT_VOICE_SESSION_KEY,
                "hold_to_talk_shortcut": HOLD_TO_TALK_SHORTCUT_LABEL,
                "default_hermes_root": DEFAULT_HERMES_ROOT,
                "gpu_note": (
                    "GPU mode currently targets NVIDIA CUDA. "
                    "Use it only when the CUDA runtime and model dependencies are already working, "
                    "then validate before saving."
                ),
                "default_local_gateway_url": DEFAULT_LOCAL_GATEWAY_URL,
                "default_remote_whisper_endpoint_url": remote_whisper_hint["url"],
                "default_remote_whisper_endpoint_model": remote_whisper_hint["model"],
                "remote_whisper_host_alias": remote_whisper_hint["host_alias"],
                "gateway_note": (
                    f"On this machine the direct gateway usually runs at {DEFAULT_LOCAL_GATEWAY_URL}. "
                    "Use the public .ts.net URL to open the app in a browser, but use the local gateway URL here "
                    "because validation and voice turns run server-side."
                ),
                "hermes_note": (
                    f"Hermes Agent is expected at {DEFAULT_HERMES_ROOT} by default. "
                    "Point this field at the Hermes checkout root that contains run_agent.py. "
                    "The runtime can use either a repo-local venv or ~/.hermes/venv."
                ),
                "windows_client_note": f"The Windows tray client uses one fixed hold-to-talk shortcut: {HOLD_TO_TALK_SHORTCUT_LABEL}.",
                "default_supertonic_python_path": detect_supertonic_python_path(),
                "default_supertonic_voice": SUPERTONIC_DEFAULT_VOICE,
                "default_supertonic_language": SUPERTONIC_DEFAULT_LANGUAGE,
                "default_supertonic_total_steps": SUPERTONIC_DEFAULT_TOTAL_STEPS,
                "default_supertonic_speed": SUPERTONIC_DEFAULT_SPEED,
                "supertonic_note": (
                    "Supertonic is a very fast local TTS engine, but it currently works best from a dedicated Python 3.12/3.13 environment. "
                    "Point Python Executable at a venv that already has the supertonic package installed. "
                    "Lower Total Steps reduces latency further; 3 is the current realtime default here."
                ),
            },
        }

    async def validate_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        agent_settings = settings.get("agent") or {}
        backend = normalize_agent_backend(payload.get("backend") or agent_settings.get("backend"))
        if backend == "hermes":
            hermes_root = str(payload.get("hermes_root") or agent_settings.get("hermes_root") or DEFAULT_HERMES_ROOT).strip()
            result = await validate_hermes_connection(
                project_root=hermes_root,
            )
            resolved_root = str(result["project_root"])
            self.store.update_config(
                {
                    "agent": {"backend": "hermes", "hermes_root": resolved_root},
                    "validation": {
                        "hermes": {
                            "config_hash": self._config_hash({"hermes_root": resolved_root}),
                        }
                    },
                }
            )
            return {"ok": True, "backend": "hermes", **result}

        if backend != "gateway":
            raise ValidationError("Unsupported conversation backend.")

        url = str(payload.get("url") or settings["gateway"]["url"]).strip()
        token = str(payload.get("token") or settings["secrets"]["gateway_token"]).strip()
        model = str(payload.get("model") or settings["gateway"]["model"]).strip()
        session_key = str(payload.get("session_key") or settings["gateway"]["session_key"]).strip()
        if not session_key:
            session_key = DEFAULT_VOICE_SESSION_KEY
        normalized_url = normalize_gateway_url(url)
        if not normalized_url:
            raise ValidationError("Enter the gateway URL.")
        if not token:
            raise ValidationError("Enter a gateway token.")
        if not model:
            raise ValidationError("Enter a gateway model.")

        summary = await validate_gateway_connection(
            url=normalized_url,
            token=token,
            model=model,
            session_key=session_key,
        )
        self.store.update_config(
            {
                "agent": {"backend": "gateway"},
                "gateway": {"url": normalized_url, "model": model, "session_key": session_key},
                "validation": {
                    "gateway": {
                        "config_hash": self._config_hash(
                            {"url": normalized_url, "model": model, "session_key": session_key}
                        ),
                        "token_fingerprint": self._fingerprint_secret(token),
                    }
                },
            }
        )
        self.store.update_secrets({"MARAS_SWITCHBOARD_GATEWAY_TOKEN": token})
        return {"ok": True, "backend": "gateway", **summary}

    async def validate_gateway(self, payload: dict[str, Any]) -> dict[str, Any]:
        gateway_payload = dict(payload)
        gateway_payload["backend"] = "gateway"
        return await self.validate_agent(gateway_payload)

    def validate_stt(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.store.load_config()["stt"]
        enabled_backends = [str(item) for item in payload.get("enabled_backends") or []]
        backend_models = dict(current.get("backend_models") or {})
        backend_models.update({str(key): str(value) for key, value in (payload.get("backend_models") or {}).items()})
        settings = {
            "enabled_backends": enabled_backends,
            "default_backend": str(payload.get("default_backend") or ""),
            "language": str(payload.get("language") or current["language"]).strip(),
            "device": normalize_stt_device(str(payload.get("device") or current["device"]).strip()),
            "compute_type": str(payload.get("compute_type") or current["compute_type"]).strip(),
            "whisper_endpoint_url": str(
                payload.get("whisper_endpoint_url")
                if "whisper_endpoint_url" in payload
                else current.get("whisper_endpoint_url", "")
            ).strip(),
            "whisper_endpoint_model": str(
                payload.get("whisper_endpoint_model")
                if "whisper_endpoint_model" in payload
                else current.get("whisper_endpoint_model", "")
            ).strip(),
            "backend_models": backend_models,
        }
        result = validate_stt_selection_step(settings)
        self.store.update_config(
            {
                "stt": settings,
                "validation": {
                    "stt": {
                        "config_hash": self._config_hash(settings),
                    }
                },
            }
        )
        return result

    async def validate_tts_selection(self, payload: dict[str, Any]) -> dict[str, Any]:
        enabled = [str(item) for item in payload.get("enabled_providers") or []]
        default_provider = str(payload.get("default_provider") or "").strip()
        if not enabled:
            raise ValidationError("Select at least one TTS provider.")
        unsupported = [provider for provider in enabled if provider not in SUPPORTED_TTS_PROVIDERS]
        if unsupported:
            raise ValidationError(f"Unsupported TTS provider: {unsupported[0]}")
        if default_provider not in enabled:
            raise ValidationError("Default TTS provider must be one of the selected providers.")
        if "disabled" in enabled and enabled != ["disabled"]:
            raise ValidationError("Disabled TTS must be selected on its own.")
        if "edge" in enabled:
            await list_edge_voices()
        self.store.update_config(
            {
                "tts": {"enabled_providers": enabled, "default_provider": default_provider},
                "validation": {
                    "tts": {
                        "config_hash": self._config_hash(
                            {
                                "enabled_providers": enabled,
                                "default_provider": default_provider,
                            }
                        ),
                    }
                },
            }
        )
        return {"ok": True, "enabled_providers": enabled, "default_provider": default_provider}

    async def edge_voices(self) -> dict[str, Any]:
        voices = await list_edge_voices()
        return {"ok": True, "voices": voices}

    async def validate_edge(self, payload: dict[str, Any]) -> dict[str, Any]:
        voice = str(payload.get("voice") or "").strip()
        rate = str(payload.get("rate") or "+0%").strip() or "+0%"
        result = await validate_edge_voice(voice=voice, rate=rate)
        self.store.update_config(
            {
                "tts": {"edge_voice": voice, "edge_rate": rate},
                "validation": {
                    "edge": {
                        "config_hash": self._config_hash({"voice": voice, "rate": rate}),
                    }
                },
            }
        )
        return result

    async def validate_elevenlabs_key(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        api_key = str(payload.get("api_key") or settings["secrets"]["elevenlabs_api_key"]).strip()
        result = await validate_elevenlabs_api_key_step(api_key)
        voices = await list_elevenlabs_voices(api_key)
        self.store.update_config(
            {
                "validation": {
                    "eleven_key": {
                        "api_key_fingerprint": self._fingerprint_secret(api_key),
                    }
                }
            }
        )
        self.store.update_secrets({"MARAS_SWITCHBOARD_ELEVENLABS_API_KEY": api_key})
        return {**result, "voices": voices}

    async def elevenlabs_voices(self) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        voices = await list_elevenlabs_voices(settings["secrets"]["elevenlabs_api_key"])
        return {"ok": True, "voices": voices}

    async def validate_supertonic(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        current_tts = settings["tts"]
        stt_language = str((settings.get("stt") or {}).get("language") or "").strip().lower()
        resolved_language_hint = (
            stt_language if stt_language in SUPERTONIC_SUPPORTED_LANGUAGES else SUPERTONIC_DEFAULT_LANGUAGE
        )
        python_path = resolve_supertonic_python_path(
            str(
                payload.get("python_path")
                if "python_path" in payload
                else current_tts.get("supertonic_python_path") or ""
            ).strip()
        )
        voice = normalize_supertonic_voice(
            str(payload.get("voice") or current_tts.get("supertonic_voice") or SUPERTONIC_DEFAULT_VOICE).strip()
        )
        language = normalize_supertonic_language(
            str(
                payload.get("language")
                if "language" in payload
                else current_tts.get("supertonic_language") or resolved_language_hint
            ).strip()
        )
        total_steps = normalize_supertonic_total_steps(
            payload.get("total_steps")
            if "total_steps" in payload
            else current_tts.get("supertonic_total_steps", SUPERTONIC_DEFAULT_TOTAL_STEPS)
        )
        speed = normalize_supertonic_speed(
            payload.get("speed")
            if "speed" in payload
            else current_tts.get("supertonic_speed", SUPERTONIC_DEFAULT_SPEED)
        )
        result = await validate_supertonic_voice_step(
            python_path=python_path,
            voice=voice,
            language=language,
            total_steps=total_steps,
            speed=speed,
        )
        saved_tts = {
            "supertonic_python_path": result["python_path"],
            "supertonic_voice": result["voice"],
            "supertonic_language": result["language"],
            "supertonic_total_steps": result["total_steps"],
            "supertonic_speed": result["speed"],
        }
        self.store.update_config(
            {
                "tts": saved_tts,
                "validation": {
                    "supertonic": {
                        "config_hash": self._config_hash(
                            {
                                "python_path": saved_tts["supertonic_python_path"],
                                "voice": saved_tts["supertonic_voice"],
                                "language": saved_tts["supertonic_language"],
                                "total_steps": saved_tts["supertonic_total_steps"],
                                "speed": saved_tts["supertonic_speed"],
                            }
                        ),
                    }
                },
            }
        )
        return result

    async def validate_elevenlabs_voice(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        api_key = settings["secrets"]["elevenlabs_api_key"]
        voice_id = str(payload.get("voice_id") or "").strip()
        model_id = str(payload.get("model_id") or settings["tts"]["elevenlabs_model"]).strip()
        preset_name = normalize_elevenlabs_preset(
            str(payload.get("preset_name") or settings["tts"]["elevenlabs_preset"]).strip()
        )
        result = await validate_elevenlabs_voice_step(
            api_key=api_key,
            voice_id=voice_id,
            model_id=model_id,
            preset_name=preset_name,
        )
        self.store.update_config(
            {
                "tts": {
                    "elevenlabs_voice_id": voice_id,
                    "elevenlabs_voice_name": result["voice_name"],
                    "elevenlabs_model": model_id,
                    "elevenlabs_preset": preset_name,
                },
                "validation": {
                    "eleven_voice": {
                        "config_hash": self._config_hash(
                            {"voice_id": voice_id, "model_id": model_id, "preset": preset_name}
                        ),
                        "api_key_fingerprint": self._fingerprint_secret(api_key),
                    }
                },
            }
        )
        return result
