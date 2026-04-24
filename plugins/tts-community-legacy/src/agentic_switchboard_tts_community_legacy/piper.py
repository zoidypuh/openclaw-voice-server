from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from agentic_switchboard.errors import ValidationError
from agentic_switchboard.installer import ensure_python_package
from agentic_switchboard.tts.base import BaseSynthesizer

from .catalog import DEFAULT_SAMPLE_TEXT, SUPPORTED_TTS_PROVIDERS


def _ensure_piper_runtime() -> None:
    descriptor = SUPPORTED_TTS_PROVIDERS["piper"]
    ensure_python_package(descriptor["package"], descriptor["import_name"])
    ensure_python_package("pathvalidate>=3.2.0", "pathvalidate")


def normalize_piper_model_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError("Enter the Piper model path.")
    path = Path(text).expanduser()
    if not path.is_file():
        raise ValidationError(f"Piper model file was not found: {path}")
    if path.suffix.lower() != ".onnx":
        raise ValidationError("Piper model path must point to a .onnx file.")
    return str(path.resolve())


def default_piper_config_path(model_path: str) -> str:
    return f"{model_path}.json"


def resolve_piper_config_path(value: str | None, *, model_path: str) -> str:
    text = str(value or "").strip()
    path = Path(text).expanduser() if text else Path(default_piper_config_path(model_path))
    if not path.is_file():
        if text:
            raise ValidationError(f"Piper config file was not found: {path}")
        raise ValidationError(
            f"Piper config file was not found: {path}. Leave it blank only when {Path(model_path).name}.json exists next to the model."
        )
    return str(path.resolve())


def normalize_piper_speaker(value: int | str | None) -> int:
    text = str(0 if value in (None, "") else value).strip()
    try:
        speaker = int(text)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Piper speaker must be a whole number.") from exc
    if speaker < 0:
        raise ValidationError("Piper speaker must be zero or greater.")
    return speaker


def _piper_command() -> list[str]:
    candidates = [
        Path(sys.executable).expanduser().with_name("piper"),
        Path(sys.prefix).expanduser() / "bin" / "piper",
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return [str(candidate)]
    resolved = shutil.which("piper")
    if resolved:
        return [resolved]
    raise ValidationError("The Piper CLI is not installed in the current environment.")


def _run_piper_cli(
    text: str,
    *,
    model_path: str,
    config_path: str,
    speaker: int,
) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        output_path = Path(temp_file.name)

    command = [
        *_piper_command(),
        "-m",
        model_path,
        "-c",
        config_path,
        "-f",
        str(output_path),
        "-s",
        str(speaker),
    ]
    try:
        completed = subprocess.run(
            command,
            input=text,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Piper synthesis failed.").strip()
            raise ValidationError(detail.splitlines()[-1] if detail else "Piper synthesis failed.")
        audio = output_path.read_bytes() if output_path.exists() else b""
        if not audio:
            raise ValidationError("Piper voice test returned no audio.")
        return audio
    finally:
        with contextlib.suppress(FileNotFoundError):
            output_path.unlink()


class PiperSynthesizer(BaseSynthesizer):
    audio_mime_type = "audio/wav"

    def __init__(self, *, model_path: str, config_path: str, speaker: int):
        self.model_path = normalize_piper_model_path(model_path)
        self.config_path = resolve_piper_config_path(config_path, model_path=self.model_path)
        self.speaker = normalize_piper_speaker(speaker)

    async def synthesize(
        self,
        text: str,
        *,
        preset_name: str | None = None,
        voice_id: str | None = None,
    ) -> bytes:
        if not text.strip():
            return b""
        return await asyncio.to_thread(
            _run_piper_cli,
            text,
            model_path=self.model_path,
            config_path=self.config_path,
            speaker=self.speaker,
        )


async def validate_piper_voice(
    *,
    model_path: str,
    config_path: str | None = None,
    speaker: int | str | None = None,
) -> dict:
    _ensure_piper_runtime()
    resolved_model_path = normalize_piper_model_path(model_path)
    resolved_config_path = resolve_piper_config_path(config_path, model_path=resolved_model_path)
    resolved_speaker = normalize_piper_speaker(speaker)
    synthesizer = PiperSynthesizer(
        model_path=resolved_model_path,
        config_path=resolved_config_path,
        speaker=resolved_speaker,
    )
    audio = await synthesizer.synthesize(DEFAULT_SAMPLE_TEXT)
    if not audio:
        raise ValidationError("Piper voice test returned no audio.")
    return {
        "ok": True,
        "model_path": resolved_model_path,
        "config_path": resolved_config_path,
        "speaker": resolved_speaker,
        "voice_name": Path(resolved_model_path).name,
    }
