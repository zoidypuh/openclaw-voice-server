from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from ..catalog import DEFAULT_SAMPLE_TEXT
from ..errors import ValidationError
from ..installer import module_available
from .base import BaseSynthesizer


SUPERTONIC_SUPPORTED_VOICES = {
    "F1": "Female 1",
    "F2": "Female 2",
    "F3": "Female 3",
    "F4": "Female 4",
    "F5": "Female 5",
    "M1": "Male 1",
    "M2": "Male 2",
    "M3": "Male 3",
    "M4": "Male 4",
    "M5": "Male 5",
}
SUPERTONIC_SUPPORTED_LANGUAGES = {
    "en": "English",
    "ko": "Korean",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
}
SUPERTONIC_DEFAULT_VOICE = "M4"
SUPERTONIC_DEFAULT_LANGUAGE = "en"
SUPERTONIC_DEFAULT_TOTAL_STEPS = 1
SUPERTONIC_DEFAULT_SPEED = 1.2
_WORKER_CACHE: dict[str, "_SupertonicWorkerClient"] = {}
_WORKER_CACHE_LOCK = threading.Lock()


def detect_supertonic_python_path() -> str:
    candidates: list[Path] = []
    current_python = Path(sys.executable).expanduser()
    if module_available("supertonic") and current_python.is_file():
        candidates.append(current_python)

    sibling_root = Path.cwd().resolve().parent / "supertonic"
    for env_dir in (".venv312", ".venv", "venv"):
        candidates.extend(
            [
                sibling_root / env_dir / "bin" / "python",
                sibling_root / env_dir / "bin" / "python3",
            ]
        )

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return os.path.abspath(str(candidate))
    return ""


def resolve_supertonic_python_path(value: str | None) -> str:
    text = str(value or "").strip()
    if text:
        candidate = Path(text).expanduser()
    else:
        detected = detect_supertonic_python_path()
        candidate = Path(detected) if detected else Path()

    if not str(candidate):
        raise ValidationError(
            "Enter a Python executable that has the supertonic package installed."
        )
    if not candidate.is_file():
        raise ValidationError(f"Supertonic Python executable was not found: {candidate}")
    if not os.access(candidate, os.X_OK):
        raise ValidationError(f"Supertonic Python executable is not runnable: {candidate}")
    return os.path.abspath(str(candidate))


def normalize_supertonic_voice(value: str | None) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return SUPERTONIC_DEFAULT_VOICE
    if normalized not in SUPERTONIC_SUPPORTED_VOICES:
        raise ValidationError(
            f"Unsupported Supertonic voice '{value}'. Choose one of: {', '.join(SUPERTONIC_SUPPORTED_VOICES)}."
        )
    return normalized


def normalize_supertonic_language(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return SUPERTONIC_DEFAULT_LANGUAGE
    if normalized not in SUPERTONIC_SUPPORTED_LANGUAGES:
        raise ValidationError(
            f"Unsupported Supertonic language '{value}'. Choose one of: {', '.join(SUPERTONIC_SUPPORTED_LANGUAGES)}."
        )
    return normalized


def normalize_supertonic_total_steps(value: int | str | None) -> int:
    text = str(SUPERTONIC_DEFAULT_TOTAL_STEPS if value in (None, "") else value).strip()
    try:
        steps = int(text)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Supertonic total steps must be a whole number.") from exc
    if steps < 1:
        raise ValidationError("Supertonic total steps must be at least 1.")
    return steps


def normalize_supertonic_speed(value: float | str | None) -> float:
    text = str(SUPERTONIC_DEFAULT_SPEED if value in (None, "") else value).strip()
    try:
        speed = float(text)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Supertonic speed must be a number.") from exc
    if speed <= 0:
        raise ValidationError("Supertonic speed must be greater than 0.")
    return speed


def _worker_script_path() -> str:
    path = Path(__file__).with_name("supertonic_worker.py")
    if not path.is_file():
        raise ValidationError(f"Supertonic worker script was not found: {path}")
    return str(path.resolve())


class _SupertonicWorkerClient:
    def __init__(self, python_path: str):
        self.python_path = python_path
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._stderr_lines: list[str] = []
        self._stderr_thread: threading.Thread | None = None

    def _drain_stderr(self, stream) -> None:
        try:
            for line in stream:
                text = line.rstrip()
                if not text:
                    continue
                self._stderr_lines.append(text)
                if len(self._stderr_lines) > 40:
                    self._stderr_lines[:] = self._stderr_lines[-40:]
        finally:
            with contextlib.suppress(Exception):
                stream.close()

    def _stderr_detail(self) -> str:
        if not self._stderr_lines:
            return ""
        return " ".join(self._stderr_lines[-3:])

    def _terminate(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        with contextlib.suppress(Exception):
            if process.stdin:
                process.stdin.close()
        with contextlib.suppress(Exception):
            process.terminate()
        with contextlib.suppress(Exception):
            process.wait(timeout=1)

    def _start(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            return

        self._terminate()
        env = dict(os.environ)
        for key in list(env):
            if key.startswith("PYTHON") or key == "VIRTUAL_ENV":
                env.pop(key, None)
        env["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            [self.python_path, _worker_script_path()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._process = process
        self._stderr_lines.clear()
        if process.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(process.stderr,),
                daemon=True,
            )
            self._stderr_thread.start()

    def _request(self, payload: dict[str, object]) -> dict[str, object]:
        last_error = ""
        for attempt in range(2):
            with self._lock:
                self._start()
                process = self._process
                if process is None or process.stdin is None or process.stdout is None:
                    raise ValidationError("Supertonic worker failed to start.")
                try:
                    process.stdin.write(json.dumps(payload) + "\n")
                    process.stdin.flush()
                    line = process.stdout.readline()
                except (BrokenPipeError, OSError) as exc:
                    last_error = str(exc)
                    self._terminate()
                    continue

                if not line:
                    last_error = self._stderr_detail() or "Supertonic worker exited unexpectedly."
                    self._terminate()
                    continue

                try:
                    response = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValidationError(f"Supertonic worker returned invalid JSON: {exc}") from exc
                if isinstance(response, dict):
                    return response
                raise ValidationError("Supertonic worker returned an unexpected response.")

        detail = last_error or self._stderr_detail() or "Supertonic worker exited unexpectedly."
        raise ValidationError(detail)

    def synthesize(
        self,
        *,
        text: str,
        voice: str,
        language: str,
        total_steps: int,
        speed: float,
    ) -> bytes:
        response = self._request(
            {
                "text": text,
                "voice": voice,
                "language": language,
                "total_steps": total_steps,
                "speed": speed,
            }
        )
        if not response.get("ok"):
            raise ValidationError(str(response.get("error") or "Supertonic synthesis failed."))

        audio = str(response.get("audio") or "")
        if not audio:
            raise ValidationError("Supertonic returned no audio.")
        try:
            return base64.b64decode(audio)
        except (ValueError, TypeError) as exc:
            raise ValidationError("Supertonic returned invalid audio data.") from exc


def _worker_client(python_path: str) -> _SupertonicWorkerClient:
    with _WORKER_CACHE_LOCK:
        client = _WORKER_CACHE.get(python_path)
        if client is None:
            client = _SupertonicWorkerClient(python_path)
            _WORKER_CACHE[python_path] = client
        return client


def _run_supertonic_synthesis(
    text: str,
    *,
    python_path: str,
    voice: str,
    language: str,
    total_steps: int,
    speed: float,
) -> bytes:
    if not text.strip():
        return b""
    client = _worker_client(python_path)
    return client.synthesize(
        text=text,
        voice=voice,
        language=language,
        total_steps=total_steps,
        speed=speed,
    )


class SupertonicSynthesizer(BaseSynthesizer):
    audio_mime_type = "audio/wav"

    def __init__(
        self,
        *,
        python_path: str,
        voice: str,
        language: str,
        total_steps: int,
        speed: float,
    ):
        self.python_path = resolve_supertonic_python_path(python_path)
        self.voice = normalize_supertonic_voice(voice)
        self.language = normalize_supertonic_language(language)
        self.total_steps = normalize_supertonic_total_steps(total_steps)
        self.speed = normalize_supertonic_speed(speed)

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
            _run_supertonic_synthesis,
            text,
            python_path=self.python_path,
            voice=self.voice,
            language=self.language,
            total_steps=self.total_steps,
            speed=self.speed,
        )


async def validate_supertonic_voice(
    *,
    python_path: str,
    voice: str,
    language: str,
    total_steps: int | str | None = None,
    speed: float | str | None = None,
) -> dict[str, object]:
    resolved_python_path = resolve_supertonic_python_path(python_path)
    normalized_voice = normalize_supertonic_voice(voice)
    normalized_language = normalize_supertonic_language(language)
    normalized_total_steps = normalize_supertonic_total_steps(total_steps)
    normalized_speed = normalize_supertonic_speed(speed)
    synthesizer = SupertonicSynthesizer(
        python_path=resolved_python_path,
        voice=normalized_voice,
        language=normalized_language,
        total_steps=normalized_total_steps,
        speed=normalized_speed,
    )
    audio = await synthesizer.synthesize(DEFAULT_SAMPLE_TEXT)
    if not audio:
        raise ValidationError("Supertonic voice test returned no audio.")
    return {
        "ok": True,
        "python_path": resolved_python_path,
        "voice": normalized_voice,
        "voice_name": SUPERTONIC_SUPPORTED_VOICES[normalized_voice],
        "language": normalized_language,
        "language_name": SUPERTONIC_SUPPORTED_LANGUAGES[normalized_language],
        "total_steps": normalized_total_steps,
        "speed": normalized_speed,
    }
