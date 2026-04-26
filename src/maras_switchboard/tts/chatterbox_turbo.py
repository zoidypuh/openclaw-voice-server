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


CHATTERBOX_TURBO_PROVIDER_ID = "chatterbox-turbo"
CHATTERBOX_TURBO_DEFAULT_DEVICE = "auto"
CHATTERBOX_TURBO_DEFAULT_EXAGGERATION = 0.5
CHATTERBOX_TURBO_DEFAULT_TEMPERATURE = 0.8
CHATTERBOX_TURBO_DEFAULT_TOP_P = 0.95
CHATTERBOX_TURBO_DEFAULT_TOP_K = 1000
CHATTERBOX_TURBO_DEFAULT_REPETITION_PENALTY = 1.2
_SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}
_WORKER_CACHE: dict[str, "_ChatterboxTurboWorkerClient"] = {}
_WORKER_CACHE_LOCK = threading.Lock()


def _python_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("MARAS_SWITCHBOARD_CHATTERBOX_TURBO_PYTHON_PATH") or os.environ.get(
        "MARAS_SWITCHBOARD_CHATTERBOX_PYTHON_PATH"
    )
    if env_path:
        candidates.append(Path(env_path).expanduser())

    current_python = Path(sys.executable).expanduser()
    if module_available("chatterbox") and current_python.is_file():
        candidates.append(current_python)

    sibling_root = Path.cwd().resolve().parent / "chatterbox-tts"
    for env_dir in (".venv", ".venv312", "venv"):
        candidates.extend(
            [
                sibling_root / env_dir / "bin" / "python",
                sibling_root / env_dir / "bin" / "python3",
            ]
        )
    return candidates


def detect_chatterbox_turbo_python_path() -> str:
    for candidate in _python_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return os.path.abspath(str(candidate))
    return ""


def detect_chatterbox_turbo_voice_prompt_path(preferred_voice_id: str | None = None) -> str:
    env_path = os.environ.get("MARAS_SWITCHBOARD_CHATTERBOX_TURBO_VOICE_PROMPT_PATH") or os.environ.get(
        "MARAS_SWITCHBOARD_CHATTERBOX_VOICE_PROMPT_PATH"
    )
    if env_path and Path(env_path).expanduser().is_file():
        return os.path.abspath(str(Path(env_path).expanduser()))

    roots = [Path.cwd() / "tts-eleven", Path.cwd() / "media"]
    token = str(preferred_voice_id or "").strip().lower()
    candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if path.suffix.lower() in _SUPPORTED_AUDIO_EXTENSIONS:
                candidates.append(path)
    if token:
        candidates.sort(
            key=lambda path: (
                token not in path.name.lower(),
                "mara" not in path.name.lower(),
                str(path),
            )
        )
    else:
        candidates.sort(key=lambda path: ("mara" not in path.name.lower(), str(path)))
    for candidate in candidates:
        if candidate.is_file():
            return os.path.abspath(str(candidate))
    return ""


def resolve_chatterbox_turbo_python_path(value: str | None) -> str:
    text = str(value or "").strip()
    if text:
        candidate = Path(text).expanduser()
    else:
        detected = detect_chatterbox_turbo_python_path()
        candidate = Path(detected) if detected else Path()

    if not str(candidate):
        raise ValidationError(
            "Enter a Python executable that has the chatterbox-tts package installed."
        )
    if not candidate.is_file():
        raise ValidationError(f"Chatterbox Turbo Python executable was not found: {candidate}")
    if not os.access(candidate, os.X_OK):
        raise ValidationError(f"Chatterbox Turbo Python executable is not runnable: {candidate}")
    return os.path.abspath(str(candidate))


def resolve_chatterbox_turbo_voice_prompt_path(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        detected = detect_chatterbox_turbo_voice_prompt_path()
        candidate = Path(detected) if detected else Path()
    else:
        candidate = Path(text).expanduser()
    if not str(candidate):
        raise ValidationError("Enter a voice prompt audio file for Chatterbox Turbo.")
    if not candidate.is_file():
        raise ValidationError(f"Chatterbox Turbo voice prompt was not found: {candidate}")
    if candidate.suffix.lower() not in _SUPPORTED_AUDIO_EXTENSIONS:
        raise ValidationError("Chatterbox Turbo voice prompt must be WAV, MP3, FLAC, M4A, or OGG.")
    return os.path.abspath(str(candidate))


def normalize_chatterbox_turbo_device(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return CHATTERBOX_TURBO_DEFAULT_DEVICE
    if normalized == "gpu":
        return "cuda"
    if normalized == "auto" or normalized == "cpu" or normalized == "mps" or normalized.startswith("cuda"):
        return normalized
    raise ValidationError("Chatterbox Turbo device must be auto, cpu, cuda, cuda:N, or mps.")


def _normalize_float(
    value: float | str | None,
    *,
    default: float,
    name: str,
    minimum: float | None = None,
    maximum: float | None = None,
    inclusive_minimum: bool = True,
) -> float:
    text = str(default if value in (None, "") else value).strip()
    try:
        parsed = float(text)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Chatterbox Turbo {name} must be a number.") from exc
    if minimum is not None:
        invalid = parsed < minimum if inclusive_minimum else parsed <= minimum
        if invalid:
            comparator = "at least" if inclusive_minimum else "greater than"
            raise ValidationError(f"Chatterbox Turbo {name} must be {comparator} {minimum}.")
    if maximum is not None and parsed > maximum:
        raise ValidationError(f"Chatterbox Turbo {name} must be at most {maximum}.")
    return parsed


def normalize_chatterbox_turbo_exaggeration(value: float | str | None) -> float:
    return _normalize_float(
        value,
        default=CHATTERBOX_TURBO_DEFAULT_EXAGGERATION,
        name="exaggeration",
        minimum=0,
        maximum=2,
    )


def normalize_chatterbox_turbo_temperature(value: float | str | None) -> float:
    return _normalize_float(
        value,
        default=CHATTERBOX_TURBO_DEFAULT_TEMPERATURE,
        name="temperature",
        minimum=0,
        maximum=5,
        inclusive_minimum=False,
    )


def normalize_chatterbox_turbo_top_p(value: float | str | None) -> float:
    return _normalize_float(
        value,
        default=CHATTERBOX_TURBO_DEFAULT_TOP_P,
        name="top-p",
        minimum=0,
        maximum=1,
        inclusive_minimum=False,
    )


def normalize_chatterbox_turbo_repetition_penalty(value: float | str | None) -> float:
    return _normalize_float(
        value,
        default=CHATTERBOX_TURBO_DEFAULT_REPETITION_PENALTY,
        name="repetition penalty",
        minimum=0,
        maximum=10,
        inclusive_minimum=False,
    )


def normalize_chatterbox_turbo_top_k(value: int | str | None) -> int:
    text = str(CHATTERBOX_TURBO_DEFAULT_TOP_K if value in (None, "") else value).strip()
    try:
        top_k = int(text)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Chatterbox Turbo top-k must be a whole number.") from exc
    if top_k < 1:
        raise ValidationError("Chatterbox Turbo top-k must be at least 1.")
    return top_k


def _worker_script_path() -> str:
    path = Path(__file__).with_name("chatterbox_turbo_worker.py")
    if not path.is_file():
        raise ValidationError(f"Chatterbox Turbo worker script was not found: {path}")
    return str(path.resolve())


class _ChatterboxTurboWorkerClient:
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
                if len(self._stderr_lines) > 80:
                    self._stderr_lines[:] = self._stderr_lines[-80:]
        finally:
            with contextlib.suppress(Exception):
                stream.close()

    def _stderr_detail(self) -> str:
        if not self._stderr_lines:
            return ""
        return " ".join(self._stderr_lines[-5:])

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
        for _attempt in range(2):
            with self._lock:
                self._start()
                process = self._process
                if process is None or process.stdin is None or process.stdout is None:
                    raise ValidationError("Chatterbox Turbo worker failed to start.")
                try:
                    process.stdin.write(json.dumps(payload) + "\n")
                    process.stdin.flush()
                except (BrokenPipeError, OSError) as exc:
                    last_error = str(exc)
                    self._terminate()
                    continue

                for _ in range(200):
                    line = process.stdout.readline()
                    if not line:
                        last_error = self._stderr_detail() or "Chatterbox Turbo worker exited unexpectedly."
                        self._terminate()
                        break

                    try:
                        response = json.loads(line)
                    except json.JSONDecodeError:
                        leaked = line.strip()
                        if leaked:
                            self._stderr_lines.append(f"stdout: {leaked[:500]}")
                            if len(self._stderr_lines) > 80:
                                self._stderr_lines[:] = self._stderr_lines[-80:]
                        continue
                    if isinstance(response, dict):
                        return response
                    raise ValidationError("Chatterbox Turbo worker returned an unexpected response.")
                else:
                    last_error = "Chatterbox Turbo worker emitted too many non-JSON lines."
                    self._terminate()

        detail = last_error or self._stderr_detail() or "Chatterbox Turbo worker exited unexpectedly."
        raise ValidationError(detail)

    def synthesize(
        self,
        *,
        text: str,
        voice_prompt_path: str,
        device: str,
        exaggeration: float,
        temperature: float,
        top_p: float,
        top_k: int,
        repetition_penalty: float,
    ) -> bytes:
        response = self._request(
            {
                "text": text,
                "voice_prompt_path": voice_prompt_path,
                "device": device,
                "exaggeration": exaggeration,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repetition_penalty": repetition_penalty,
                "norm_loudness": True,
            }
        )
        if not response.get("ok"):
            raise ValidationError(str(response.get("error") or "Chatterbox Turbo synthesis failed."))

        audio = str(response.get("audio") or "")
        if not audio:
            raise ValidationError("Chatterbox Turbo returned no audio.")
        try:
            return base64.b64decode(audio)
        except (ValueError, TypeError) as exc:
            raise ValidationError("Chatterbox Turbo returned invalid audio data.") from exc


def _worker_client(python_path: str) -> _ChatterboxTurboWorkerClient:
    with _WORKER_CACHE_LOCK:
        client = _WORKER_CACHE.get(python_path)
        if client is None:
            client = _ChatterboxTurboWorkerClient(python_path)
            _WORKER_CACHE[python_path] = client
        return client


def _run_chatterbox_turbo_synthesis(
    text: str,
    *,
    python_path: str,
    voice_prompt_path: str,
    device: str,
    exaggeration: float,
    temperature: float,
    top_p: float,
    top_k: int,
    repetition_penalty: float,
) -> bytes:
    if not text.strip():
        return b""
    client = _worker_client(python_path)
    return client.synthesize(
        text=text,
        voice_prompt_path=voice_prompt_path,
        device=device,
        exaggeration=exaggeration,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repetition_penalty=repetition_penalty,
    )


class ChatterboxTurboSynthesizer(BaseSynthesizer):
    audio_mime_type = "audio/wav"

    def __init__(
        self,
        *,
        python_path: str,
        voice_prompt_path: str,
        device: str,
        exaggeration: float | str | None,
        temperature: float | str | None,
        top_p: float | str | None,
        top_k: int | str | None,
        repetition_penalty: float | str | None,
    ):
        self.python_path = resolve_chatterbox_turbo_python_path(python_path)
        self.voice_prompt_path = resolve_chatterbox_turbo_voice_prompt_path(voice_prompt_path)
        self.device = normalize_chatterbox_turbo_device(device)
        self.exaggeration = normalize_chatterbox_turbo_exaggeration(exaggeration)
        self.temperature = normalize_chatterbox_turbo_temperature(temperature)
        self.top_p = normalize_chatterbox_turbo_top_p(top_p)
        self.top_k = normalize_chatterbox_turbo_top_k(top_k)
        self.repetition_penalty = normalize_chatterbox_turbo_repetition_penalty(repetition_penalty)

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
            _run_chatterbox_turbo_synthesis,
            text,
            python_path=self.python_path,
            voice_prompt_path=self.voice_prompt_path,
            device=self.device,
            exaggeration=self.exaggeration,
            temperature=self.temperature,
            top_p=self.top_p,
            top_k=self.top_k,
            repetition_penalty=self.repetition_penalty,
        )


async def validate_chatterbox_turbo_voice(
    *,
    python_path: str,
    voice_prompt_path: str,
    device: str,
    exaggeration: float | str | None = None,
    temperature: float | str | None = None,
    top_p: float | str | None = None,
    top_k: int | str | None = None,
    repetition_penalty: float | str | None = None,
) -> dict[str, object]:
    synthesizer = ChatterboxTurboSynthesizer(
        python_path=python_path,
        voice_prompt_path=voice_prompt_path,
        device=device,
        exaggeration=exaggeration,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repetition_penalty=repetition_penalty,
    )
    audio = await synthesizer.synthesize(DEFAULT_SAMPLE_TEXT)
    if not audio:
        raise ValidationError("Chatterbox Turbo voice test returned no audio.")
    return {
        "ok": True,
        "python_path": synthesizer.python_path,
        "voice_prompt_path": synthesizer.voice_prompt_path,
        "device": synthesizer.device,
        "exaggeration": synthesizer.exaggeration,
        "temperature": synthesizer.temperature,
        "top_p": synthesizer.top_p,
        "top_k": synthesizer.top_k,
        "repetition_penalty": synthesizer.repetition_penalty,
    }
