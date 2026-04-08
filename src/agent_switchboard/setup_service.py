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
    CHATTERBOX_DEFAULT_DEVICE,
    CHATTERBOX_DEFAULT_MODEL,
    DEFAULT_HERMES_ROOT,
    DEFAULT_LOCAL_GATEWAY_URL,
    DEFAULT_REMOTE_WHISPER_ENDPOINT_PATH,
    DEFAULT_REMOTE_WHISPER_HOST_ALIAS,
    DEFAULT_REMOTE_WHISPER_MODEL,
    DEFAULT_REMOTE_WHISPER_PORT,
    DEFAULT_VIBEVOICE_BASE_URL,
    DEFAULT_VOICE_SESSION_KEY,
    DEFAULT_WINDOWS_SHORTCUTS,
    ELEVENLABS_PRESETS,
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
    CHATTERBOX_SUPPORTED_DEVICES,
    CHATTERBOX_SUPPORTED_MODELS,
    NEUTTS_SUPPORTED_DEVICES,
    default_piper_config_path,
    list_local_chatterbox_voices,
    list_local_neutts_voices,
    list_edge_voices,
    list_elevenlabs_voices,
    list_vibevoice_voices,
    normalize_chatterbox_language,
    normalize_chatterbox_model,
    normalize_elevenlabs_preset,
    normalize_neutts_device,
    normalize_piper_model_path,
    normalize_piper_speaker,
    normalize_vibevoice_base_url,
    resolve_chatterbox_voice,
    resolve_neutts_voice,
    validate_chatterbox_voice as validate_chatterbox_voice_step,
    validate_edge_voice,
    validate_elevenlabs_api_key as validate_elevenlabs_api_key_step,
    validate_elevenlabs_voice as validate_elevenlabs_voice_step,
    validate_neutts_voice as validate_neutts_voice_step,
    validate_piper_voice as validate_piper_voice_step,
    validate_vibevoice_voice as validate_vibevoice_voice_step,
)


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
            os.environ.get("AGENT_SWITCHBOARD_REMOTE_WHISPER_ENDPOINT_URL")
            or os.environ.get("OPENCLAW_VOICE_REMOTE_WHISPER_ENDPOINT_URL")
            or os.environ.get("AGENT_SWITCHBOARD_MAC_WHISPER_ENDPOINT_URL")
            or os.environ.get("OPENCLAW_VOICE_MAC_WHISPER_ENDPOINT_URL")
            or ""
        ).strip()
        env_model = str(
            os.environ.get("AGENT_SWITCHBOARD_REMOTE_WHISPER_ENDPOINT_MODEL")
            or os.environ.get("OPENCLAW_VOICE_REMOTE_WHISPER_ENDPOINT_MODEL")
            or os.environ.get("AGENT_SWITCHBOARD_MAC_WHISPER_ENDPOINT_MODEL")
            or os.environ.get("OPENCLAW_VOICE_MAC_WHISPER_ENDPOINT_MODEL")
            or ""
        ).strip()
        host_alias = str(
            os.environ.get("AGENT_SWITCHBOARD_REMOTE_WHISPER_HOST_ALIAS")
            or os.environ.get("OPENCLAW_VOICE_REMOTE_WHISPER_HOST_ALIAS")
            or os.environ.get("AGENT_SWITCHBOARD_MAC_WHISPER_SSH_ALIAS")
            or os.environ.get("OPENCLAW_VOICE_MAC_WHISPER_SSH_ALIAS")
            or DEFAULT_REMOTE_WHISPER_HOST_ALIAS
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

    def _local_piper_voices(self, settings: dict[str, Any]) -> list[dict[str, str]]:
        candidate_dirs = [
            self.store.config_path.parent / "piper-voices",
            Path.cwd() / "piper-voices",
        ]
        seen_dirs: set[str] = set()
        voices: list[dict[str, str]] = []
        seen_models: set[str] = set()
        for directory in candidate_dirs:
            resolved_dir = str(directory.resolve())
            if resolved_dir in seen_dirs or not directory.is_dir():
                continue
            seen_dirs.add(resolved_dir)
            for model_path in sorted(directory.glob("*.onnx")):
                resolved_model_path = str(model_path.resolve())
                if resolved_model_path in seen_models:
                    continue
                seen_models.add(resolved_model_path)
                config_path = Path(default_piper_config_path(resolved_model_path))
                voices.append(
                    {
                        "voice_name": model_path.name,
                        "model_path": resolved_model_path,
                        "config_path": str(config_path.resolve()) if config_path.is_file() else "",
                        "source_dir": resolved_dir,
                    }
                )
        return voices

    @staticmethod
    def _default_local_piper_voice(
        settings: dict[str, Any],
        voices: list[dict[str, str]],
    ) -> dict[str, str] | None:
        if not voices:
            return None
        language = str((settings.get("stt") or {}).get("language") or "").strip().lower()
        if language and language != "auto":
            prefix = f"{language}_"
            for voice in voices:
                if Path(voice["model_path"]).name.lower().startswith(prefix):
                    return voice
        return voices[0]

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

    @staticmethod
    def _normalize_shortcut(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValidationError("Shortcut values cannot be empty.")

        modifier_aliases = {
            "ctrl": "Ctrl",
            "control": "Ctrl",
            "alt": "Alt",
            "option": "Alt",
            "shift": "Shift",
            "cmd": "Super",
            "command": "Super",
            "meta": "Super",
            "super": "Super",
            "win": "Super",
            "windows": "Super",
        }
        key_aliases = {
            "space": "Space",
            "enter": "Enter",
            "return": "Enter",
            "tab": "Tab",
            "esc": "Escape",
            "escape": "Escape",
            "backspace": "Backspace",
            "delete": "Delete",
            "del": "Delete",
            "insert": "Insert",
            "ins": "Insert",
            "home": "Home",
            "end": "End",
            "pageup": "PageUp",
            "pgup": "PageUp",
            "pagedown": "PageDown",
            "pgdown": "PageDown",
            "up": "ArrowUp",
            "arrowup": "ArrowUp",
            "down": "ArrowDown",
            "arrowdown": "ArrowDown",
            "left": "ArrowLeft",
            "arrowleft": "ArrowLeft",
            "right": "ArrowRight",
            "arrowright": "ArrowRight",
        }
        tokens = [part.strip() for part in text.split("+")]
        if not tokens or any(not token for token in tokens):
            raise ValidationError(
                "Shortcut values must look like Ctrl+Shift+Space or Ctrl+Alt+A."
            )

        modifiers: set[str] = set()
        key: str | None = None
        for index, token in enumerate(tokens):
            compact = token.replace(" ", "").replace("_", "").replace("-", "")
            lowered = compact.lower()
            if lowered in modifier_aliases:
                if key is not None or index == len(tokens) - 1:
                    raise ValidationError("Shortcut modifiers must come before the final key.")
                modifiers.add(modifier_aliases[lowered])
                continue

            if index != len(tokens) - 1:
                raise ValidationError("Shortcut values must end with exactly one key.")
            if lowered.startswith("key") and len(compact) == 4 and compact[3].isalpha():
                key = compact[3].upper()
            elif lowered.startswith("digit") and len(compact) == 6 and compact[5].isdigit():
                key = compact[5]
            elif len(compact) == 1 and compact.isalpha():
                key = compact.upper()
            elif len(compact) == 1 and compact.isdigit():
                key = compact
            elif lowered in key_aliases:
                key = key_aliases[lowered]
            elif lowered.startswith("f") and compact[1:].isdigit() and 1 <= int(compact[1:]) <= 24:
                key = f"F{int(compact[1:])}"
            else:
                raise ValidationError(
                    f"Unsupported shortcut key '{token}'. Use keys like A, P, Space, Enter, ArrowUp, or F5."
                )

        if not modifiers:
            raise ValidationError("Shortcut values must include at least one modifier key.")
        if key is None:
            raise ValidationError("Shortcut values must end with a key.")

        ordered_modifiers = [
            modifier for modifier in ("Ctrl", "Alt", "Shift", "Super") if modifier in modifiers
        ]
        return "+".join([*ordered_modifiers, key])

    def validate_windows_client(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.store.load_config()["windows_client"]
        current_shortcuts = dict(current.get("shortcuts") or {})
        shortcuts = {
            "toggle_window": self._normalize_shortcut(
                str(payload.get("toggle_window") or current_shortcuts.get("toggle_window") or "")
            ),
            "pause_resume": self._normalize_shortcut(
                str(payload.get("pause_resume") or current_shortcuts.get("pause_resume") or "")
            ),
            "interrupt": self._normalize_shortcut(
                str(payload.get("interrupt") or current_shortcuts.get("interrupt") or "")
            ),
        }
        if len(set(shortcuts.values())) != len(shortcuts):
            raise ValidationError("Windows client shortcuts must be unique.")

        self.store.update_config(
            {
                "windows_client": {
                    "shortcuts": shortcuts,
                },
                "validation": {
                    "windows_client": {
                        "config_hash": self._config_hash(shortcuts),
                    }
                },
            }
        )
        return {"ok": True, "shortcuts": shortcuts}

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
        if provider_id == "piper":
            return bool(
                str(tts.get("piper_model_path") or "").strip()
                and str(tts.get("piper_config_path") or "").strip()
            )
        if provider_id == "chatterbox":
            return bool(
                str(tts.get("chatterbox_model") or "").strip()
                and str(tts.get("chatterbox_device") or "").strip()
                and str(tts.get("chatterbox_language") or "").strip()
                and str(tts.get("chatterbox_voice") or "").strip()
            )
        if provider_id == "vibevoice":
            return bool(
                str(tts.get("vibevoice_base_url") or "").strip()
                and str(tts.get("vibevoice_voice") or "").strip()
            )
        if provider_id == "neutts":
            return bool(
                str(tts.get("neutts_backbone") or "").strip()
                and str(tts.get("neutts_codec") or "").strip()
                and str(tts.get("neutts_device") or "").strip()
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
        piper_snapshot = {
            "model_path": settings["tts"]["piper_model_path"],
            "config_path": settings["tts"]["piper_config_path"],
            "speaker": settings["tts"]["piper_speaker"],
        }
        piper_ready = "piper" not in settings["tts"]["enabled_providers"] or self._validated_config_matches(
            piper_snapshot,
            validation["piper"],
        )
        chatterbox_snapshot = {
            "model": settings["tts"]["chatterbox_model"],
            "device": settings["tts"]["chatterbox_device"],
            "language": settings["tts"]["chatterbox_language"],
            "voice": settings["tts"].get("chatterbox_voice") or "default",
        }
        chatterbox_ready = "chatterbox" not in settings["tts"]["enabled_providers"] or self._validated_config_matches(
            chatterbox_snapshot,
            validation["chatterbox"],
        )
        vibevoice_snapshot = {
            "base_url": settings["tts"]["vibevoice_base_url"],
            "voice": settings["tts"]["vibevoice_voice"],
        }
        vibevoice_ready = "vibevoice" not in settings["tts"]["enabled_providers"] or self._validated_config_matches(
            vibevoice_snapshot,
            validation["vibevoice"],
        )
        neutts_snapshot = {
            "backbone": settings["tts"].get("neutts_backbone", ""),
            "codec": settings["tts"].get("neutts_codec", ""),
            "device": settings["tts"].get("neutts_device", ""),
            "voice": settings["tts"].get("neutts_voice", ""),
        }
        neutts_ready = "neutts" not in settings["tts"]["enabled_providers"] or self._validated_config_matches(
            neutts_snapshot,
            validation.get("neutts", {}),
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
            "piper_ready": piper_ready,
            "chatterbox_ready": chatterbox_ready,
            "vibevoice_ready": vibevoice_ready,
            "neutts_ready": neutts_ready,
            "runtime_ready": runtime_ready,
        }

    def state(self) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        remote_whisper_hint = self._default_remote_whisper_hint(settings)
        local_piper_voices = self._local_piper_voices(settings)
        local_chatterbox_voices = list_local_chatterbox_voices()
        local_neutts_voices = list_local_neutts_voices()
        default_local_piper_voice = self._default_local_piper_voice(settings, local_piper_voices)
        default_local_piper_source_dir = (
            default_local_piper_voice["source_dir"] if default_local_piper_voice else ""
        )
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
                "chatterbox_models": [
                    {"id": model_id, "label": label}
                    for model_id, label in CHATTERBOX_SUPPORTED_MODELS.items()
                ],
                "chatterbox_devices": [
                    {"id": device_id, "label": device_id.upper() if device_id != "auto" else "Auto"}
                    for device_id in sorted(CHATTERBOX_SUPPORTED_DEVICES, key=lambda item: ("auto" != item, item))
                ],
                "chatterbox_voices": [{"id": "default", "label": "Built-In Default"}]
                + [{"id": item["id"], "label": item["label"]} for item in local_chatterbox_voices],
                "neutts_devices": [
                    {"id": device_id, "label": device_id.upper() if device_id != "auto" else "Auto"}
                    for device_id in sorted(NEUTTS_SUPPORTED_DEVICES, key=lambda item: ("auto" != item, item))
                ],
                "neutts_voices": [{"id": item["id"], "label": item["label"]} for item in local_neutts_voices],
                "elevenlabs_presets": [
                    {"id": preset_id, "label": preset["label"]}
                    for preset_id, preset in ELEVENLABS_PRESETS.items()
                ],
            },
            "hints": {
                "default_voice_session_key": DEFAULT_VOICE_SESSION_KEY,
                "default_windows_shortcuts": DEFAULT_WINDOWS_SHORTCUTS,
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
                "windows_shortcuts_note": (
                    "These shortcuts are used by the Windows tray client. "
                    "Changes take effect the next time the Windows client starts."
                ),
                "default_vibevoice_base_url": DEFAULT_VIBEVOICE_BASE_URL,
                "vibevoice_note": (
                    f"Run the VibeVoice demo server locally, usually at {DEFAULT_VIBEVOICE_BASE_URL}, "
                    "then choose one of the preset voices it exposes through /config."
                ),
                "piper_repo_url": "https://github.com/OHF-Voice/piper1-gpl",
                "piper_voices_url": "https://huggingface.co/rhasspy/piper-voices",
                "default_piper_model_path": (
                    default_local_piper_voice["model_path"] if default_local_piper_voice else ""
                ),
                "default_piper_config_path": (
                    default_local_piper_voice["config_path"] if default_local_piper_voice else ""
                ),
                "chatterbox_note": (
                    "Chatterbox runs fully local. "
                    "Use the multilingual model for German and other non-English languages, or the original model for English-only output. "
                    "When Language is left blank in the UI, the validated STT language is used and falls back to English if STT is set to auto. "
                    + (
                        f"Detected {len(local_chatterbox_voices)} local Chatterbox voice file(s) in the workspace."
                        if local_chatterbox_voices
                        else "No local Chatterbox voice files were detected yet."
                    )
                ),
                "default_chatterbox_model": CHATTERBOX_DEFAULT_MODEL,
                "default_chatterbox_device": CHATTERBOX_DEFAULT_DEVICE,
                "default_chatterbox_voice": "default",
                "default_neutts_backbone": "neuphonic/neutts-nano-german",
                "default_neutts_codec": "neuphonic/neucodec",
                "default_neutts_device": "auto",
                "local_neutts_voices": local_neutts_voices,
                "neutts_note": (
                    "NeuTTS runs fully local with voice cloning. "
                    "Place a subdirectory in neutts-voices/ with a .wav (3-15s) and .txt (transcript) file. "
                    + (
                        f"Detected {len(local_neutts_voices)} local NeuTTS voice(s)."
                        if local_neutts_voices
                        else "No local NeuTTS voice files were detected yet."
                    )
                ),
                "local_piper_voices": local_piper_voices,
                "piper_note": (
                    "Model Path must point to a Piper voice .onnx file, not the Piper install directory. "
                    + (
                        f"Detected local Piper voices in {default_local_piper_source_dir}. "
                        "Choose one below or paste another .onnx path manually. "
                        if default_local_piper_source_dir
                        else "No local Piper voices were auto-detected next to the current config. "
                    )
                    + "Leave Config Path blank only when the matching <model>.onnx.json file sits next to the model file."
                ),
            },
        }

    async def validate_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        agent_settings = settings.get("agent") or {}
        backend = normalize_agent_backend(payload.get("backend") or agent_settings.get("backend"))
        if backend == "hermes":
            hermes_root = str(payload.get("hermes_root") or agent_settings.get("hermes_root") or DEFAULT_HERMES_ROOT).strip()
            gateway_settings = settings.get("gateway") or {}
            gateway_secrets = settings.get("secrets") or {}
            gateway_url = str(gateway_settings.get("url") or "").strip()
            gateway_token = str(gateway_secrets.get("gateway_token") or "").strip()
            gateway_model = str(gateway_settings.get("model") or "").strip()
            result = await validate_hermes_connection(
                project_root=hermes_root,
                gateway_url=normalize_gateway_url(gateway_url) if gateway_url and gateway_token and gateway_model else None,
                gateway_token=gateway_token or None,
                gateway_model=gateway_model or None,
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
        self.store.update_secrets({"AGENT_SWITCHBOARD_GATEWAY_TOKEN": token})
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
        if default_provider not in enabled:
            raise ValidationError("Default TTS provider must be one of the selected providers.")
        if "disabled" in enabled and enabled != ["disabled"]:
            raise ValidationError("Disabled TTS must be selected on its own.")
        if "edge" in enabled:
            await list_edge_voices()
        if "piper" in enabled:
            normalize_piper_speaker(self.store.load_config()["tts"].get("piper_speaker", 0))
        if "chatterbox" in enabled:
            normalize_chatterbox_model(self.store.load_config()["tts"].get("chatterbox_model", CHATTERBOX_DEFAULT_MODEL))
            resolve_chatterbox_voice(self.store.load_config()["tts"].get("chatterbox_voice", "default"))
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
        self.store.update_secrets({"AGENT_SWITCHBOARD_ELEVENLABS_API_KEY": api_key})
        return {**result, "voices": voices}

    async def elevenlabs_voices(self) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        voices = await list_elevenlabs_voices(settings["secrets"]["elevenlabs_api_key"])
        return {"ok": True, "voices": voices}

    async def validate_piper(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        current_tts = settings["tts"]
        model_path = normalize_piper_model_path(
            str(payload.get("model_path") or current_tts.get("piper_model_path") or "").strip()
        )
        config_path = str(
            payload.get("config_path")
            if "config_path" in payload
            else current_tts.get("piper_config_path", "")
        ).strip()
        speaker = normalize_piper_speaker(
            payload.get("speaker")
            if "speaker" in payload
            else current_tts.get("piper_speaker", 0)
        )
        result = await validate_piper_voice_step(
            model_path=model_path,
            config_path=config_path,
            speaker=speaker,
        )
        saved_tts = {
            "piper_model_path": result["model_path"],
            "piper_config_path": result["config_path"] or default_piper_config_path(result["model_path"]),
            "piper_speaker": result["speaker"],
        }
        self.store.update_config(
            {
                "tts": saved_tts,
                "validation": {
                    "piper": {
                        "config_hash": self._config_hash(
                            {
                                "model_path": saved_tts["piper_model_path"],
                                "config_path": saved_tts["piper_config_path"],
                                "speaker": saved_tts["piper_speaker"],
                            }
                        ),
                    }
                },
            }
        )
        return result

    async def validate_chatterbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        current_tts = settings["tts"]
        stt_language = str((settings.get("stt") or {}).get("language") or "").strip().lower()
        model = normalize_chatterbox_model(
            str(payload.get("model") or current_tts.get("chatterbox_model") or CHATTERBOX_DEFAULT_MODEL).strip()
        )
        requested_language = str(
            payload.get("language")
            if "language" in payload
            else current_tts.get("chatterbox_language", "")
        ).strip()
        if not requested_language and model == "multilingual":
            requested_language = stt_language if stt_language and stt_language != "auto" else "en"
        device = str(payload.get("device") or current_tts.get("chatterbox_device") or CHATTERBOX_DEFAULT_DEVICE).strip()
        voice = resolve_chatterbox_voice(
            str(payload.get("voice") if "voice" in payload else current_tts.get("chatterbox_voice", "default")).strip()
        )
        resolved_language = normalize_chatterbox_language(requested_language, model=model)
        result = await validate_chatterbox_voice_step(
            model=model,
            device=device,
            language=resolved_language,
            voice=voice,
        )
        saved_tts = {
            "chatterbox_model": result["model"],
            "chatterbox_device": result["device"],
            "chatterbox_language": result["language"],
            "chatterbox_voice": result["voice"],
        }
        self.store.update_config(
            {
                "tts": saved_tts,
                "validation": {
                    "chatterbox": {
                        "config_hash": self._config_hash(
                            {
                                "model": saved_tts["chatterbox_model"],
                                "device": saved_tts["chatterbox_device"],
                                "language": saved_tts["chatterbox_language"],
                                "voice": saved_tts["chatterbox_voice"],
                            }
                        ),
                    }
                },
            }
        )
        return result

    async def vibevoice_voices(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        submitted = payload or {}
        base_url = normalize_vibevoice_base_url(
            str(submitted.get("base_url") or settings["tts"]["vibevoice_base_url"]).strip()
        )
        voices = await list_vibevoice_voices(base_url)
        return {"ok": True, "base_url": base_url, "voices": voices}

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

    async def validate_vibevoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        base_url = normalize_vibevoice_base_url(
            str(payload.get("base_url") or settings["tts"]["vibevoice_base_url"]).strip()
        )
        voice = str(payload.get("voice") or settings["tts"]["vibevoice_voice"]).strip()
        result = await validate_vibevoice_voice_step(base_url=base_url, voice=voice)
        self.store.update_config(
            {
                "tts": {
                    "vibevoice_base_url": base_url,
                    "vibevoice_voice": result["voice_id"],
                },
                "validation": {
                    "vibevoice": {
                        "config_hash": self._config_hash(
                            {"base_url": base_url, "voice": result["voice_id"]}
                        ),
                    }
                },
            }
        )
        return result

    async def validate_neutts(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.store.load_runtime_settings()
        current_tts = settings["tts"]
        backbone = str(payload.get("backbone") or current_tts.get("neutts_backbone") or "neuphonic/neutts-nano-german").strip()
        codec = str(payload.get("codec") or current_tts.get("neutts_codec") or "neuphonic/neucodec").strip()
        device = normalize_neutts_device(
            str(payload.get("device") or current_tts.get("neutts_device") or "auto").strip()
        )
        voice = str(payload.get("voice") or current_tts.get("neutts_voice") or "").strip()
        result = await validate_neutts_voice_step(
            backbone=backbone,
            codec=codec,
            device=device,
            voice=voice or None,
        )
        self.store.update_config(
            {
                "tts": {
                    "neutts_backbone": result["backbone"],
                    "neutts_codec": result["codec"],
                    "neutts_device": result["device"],
                    "neutts_voice": result["voice"] if result["voice"] != "(default)" else "",
                },
                "validation": {
                    "neutts": {
                        "config_hash": self._config_hash(
                            {
                                "backbone": result["backbone"],
                                "codec": result["codec"],
                                "device": result["device"],
                                "voice": result["voice"] if result["voice"] != "(default)" else "",
                            }
                        ),
                    }
                },
            }
        )
        return result
