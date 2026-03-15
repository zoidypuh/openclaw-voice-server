from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .catalog import LEGACY_ENV_TO_CONFIG, SECRET_ENV_KEYS, default_config


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if text.isdigit():
        return int(text)
    try:
        return float(text)
    except ValueError:
        return text


def _deep_merge(target: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def _get_nested(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _set_nested(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = data
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[path[-1]] = value


def _split_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        value = value[1:-1]
    return key, value


def _quote_env_value(value: str) -> str:
    if value == "":
        return '""'
    if any(ch.isspace() for ch in value) or "#" in value or value.startswith(("'", '"')):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


class ConfigStore:
    def __init__(self, config_path: Path | None = None, env_path: Path | None = None):
        cwd = Path.cwd()
        self.config_path = Path(
            os.environ.get("OPENCLAW_VOICE_CONFIG_FILE", config_path or cwd / "config.json")
        )
        self.env_path = Path(os.environ.get("OPENCLAW_VOICE_ENV_FILE", env_path or cwd / ".env"))

    def load_env_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        if self.env_path.exists():
            for line in self.env_path.read_text(encoding="utf-8").splitlines():
                parsed = _split_env_line(line)
                if parsed is None:
                    continue
                key, value = parsed
                values[key] = value
        for key in SECRET_ENV_KEYS | set(LEGACY_ENV_TO_CONFIG):
            env_value = os.environ.get(key)
            if env_value is not None:
                values[key] = env_value
        return values

    def load_config(self) -> dict[str, Any]:
        config = default_config()
        if self.config_path.exists():
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _deep_merge(config, raw)

        env_values = self.load_env_values()
        for env_key, path in LEGACY_ENV_TO_CONFIG.items():
            env_value = env_values.get(env_key)
            if env_value is None:
                continue
            existing = _get_nested(config, path)
            if existing not in (None, "", []):
                continue
            _set_nested(config, path, _parse_scalar(env_value))

        return config

    def load_runtime_settings(self) -> dict[str, Any]:
        config = self.load_config()
        env_values = self.load_env_values()
        config["secrets"] = {
            "gateway_token": env_values.get("OPENCLAW_VOICE_GATEWAY_TOKEN", ""),
            "elevenlabs_api_key": env_values.get("OPENCLAW_VOICE_ELEVENLABS_API_KEY", ""),
        }
        return config

    def save_config(self, config: dict[str, Any]) -> None:
        self.config_path.write_text(
            json.dumps(config, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        config = self.load_config()
        _deep_merge(config, updates)
        if isinstance(updates.get("validation"), dict) and isinstance(config.get("validation"), dict):
            for key, value in updates["validation"].items():
                config["validation"][key] = value
        self.save_config(config)
        return config

    def update_secrets(self, updates: dict[str, str | None]) -> None:
        existing_lines = []
        if self.env_path.exists():
            existing_lines = self.env_path.read_text(encoding="utf-8").splitlines()

        seen: set[str] = set()
        rendered: list[str] = []
        for line in existing_lines:
            parsed = _split_env_line(line)
            if parsed is None:
                rendered.append(line)
                continue
            key, _ = parsed
            if key in updates:
                seen.add(key)
                value = updates[key]
                if value in (None, ""):
                    continue
                rendered.append(f"{key}={_quote_env_value(value)}")
                continue
            rendered.append(line)

        for key, value in updates.items():
            if key in seen or value in (None, ""):
                continue
            rendered.append(f"{key}={_quote_env_value(value)}")

        final_text = "\n".join(rendered).rstrip()
        if final_text:
            final_text += "\n"
        self.env_path.write_text(final_text, encoding="utf-8")

    def public_setup_state(self) -> dict[str, Any]:
        settings = self.load_runtime_settings()
        return {
            "config_path": str(self.config_path),
            "env_path": str(self.env_path),
            "gateway": {
                "url": settings["gateway"]["url"],
                "model": settings["gateway"]["model"],
                "session_key": settings["gateway"]["session_key"],
                "token_present": bool(settings["secrets"]["gateway_token"]),
            },
            "stt": settings["stt"],
            "tts": {
                **settings["tts"],
                "elevenlabs_api_key_present": bool(settings["secrets"]["elevenlabs_api_key"]),
            },
            "audio": settings["audio"],
        }
