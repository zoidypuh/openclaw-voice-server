from __future__ import annotations

import base64
import contextlib
import io
import json
from pathlib import Path
import sys
import wave

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != SCRIPT_DIR]
_PROTOCOL_STDOUT = sys.stdout

with contextlib.redirect_stdout(sys.stderr):
    import torch
    from chatterbox.tts_turbo import ChatterboxTurboTTS


_MODEL: ChatterboxTurboTTS | None = None
_MODEL_DEVICE = ""
_CONDITIONALS_KEY: tuple[int, str, float, bool] | None = None


def _cuda_support_detail(device_index: int = 0) -> tuple[bool, str]:
    try:
        major, minor = torch.cuda.get_device_capability(device_index)
        device_name = torch.cuda.get_device_name(device_index)
        required_arch = f"sm_{major}{minor}"
        supported_arches = list(torch.cuda.get_arch_list())
    except Exception as exc:
        return False, str(exc) or exc.__class__.__name__

    if required_arch in supported_arches:
        return True, ""
    supported = ", ".join(supported_arches) if supported_arches else "none reported"
    return (
        False,
        f"{device_name} requires CUDA architecture {required_arch}, but this PyTorch build supports {supported}.",
    )


def _cuda_device_index(value: str) -> int:
    if ":" not in value:
        return 0
    _, _, index_text = value.partition(":")
    try:
        return max(int(index_text), 0)
    except ValueError:
        return 0


def _resolve_device(value: str) -> str:
    requested = str(value or "").strip().lower()
    if requested.startswith("cuda"):
        supported, detail = _cuda_support_detail(_cuda_device_index(requested))
        if not supported:
            raise RuntimeError(
                f"Requested Chatterbox Turbo CUDA device is not supported. {detail} "
                "Select CPU, or install a PyTorch build that supports this GPU."
            )
        return requested
    if requested and requested != "auto":
        return requested
    if torch.cuda.is_available():
        supported, _detail = _cuda_support_detail(0)
        if supported:
            return "cuda"
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def _model_for_device(device: str) -> ChatterboxTurboTTS:
    global _MODEL, _MODEL_DEVICE, _CONDITIONALS_KEY
    if _MODEL is not None and _MODEL_DEVICE == device:
        return _MODEL
    _MODEL = ChatterboxTurboTTS.from_pretrained(device=device)
    _MODEL_DEVICE = device
    _CONDITIONALS_KEY = None
    return _MODEL


def _prepare_conditionals(
    model: ChatterboxTurboTTS,
    *,
    voice_prompt_path: str,
    exaggeration: float,
    norm_loudness: bool,
) -> None:
    global _CONDITIONALS_KEY
    prompt_path = Path(voice_prompt_path).expanduser()
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Chatterbox voice prompt was not found: {prompt_path}")
    resolved_prompt_path = str(prompt_path.resolve())
    key = (id(model), resolved_prompt_path, float(exaggeration), bool(norm_loudness))
    if _CONDITIONALS_KEY == key:
        return
    model.prepare_conditionals(
        resolved_prompt_path,
        exaggeration=float(exaggeration),
        norm_loudness=bool(norm_loudness),
    )
    _CONDITIONALS_KEY = key


def _float_audio_to_wav(audio: object, *, sample_rate: int) -> bytes:
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    pcm = np.asarray(audio, dtype=np.float32)
    if pcm.ndim > 1:
        pcm = pcm[0]
    pcm = np.clip(pcm, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype(np.int16)
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm16.tobytes())
        return buffer.getvalue()


def main() -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            with contextlib.redirect_stdout(sys.stderr):
                payload = json.loads(line)
                text = str(payload["text"])
                device = _resolve_device(str(payload.get("device") or "auto"))
                voice_prompt_path = str(payload["voice_prompt_path"])
                exaggeration = float(payload.get("exaggeration", 0.5))
                temperature = float(payload.get("temperature", 0.8))
                top_p = float(payload.get("top_p", 0.95))
                top_k = int(payload.get("top_k", 1000))
                repetition_penalty = float(payload.get("repetition_penalty", 1.2))
                norm_loudness = bool(payload.get("norm_loudness", True))

                model = _model_for_device(device)
                _prepare_conditionals(
                    model,
                    voice_prompt_path=voice_prompt_path,
                    exaggeration=exaggeration,
                    norm_loudness=norm_loudness,
                )
                wav = model.generate(
                    text,
                    audio_prompt_path=None,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repetition_penalty=repetition_penalty,
                )
                sample_rate = int(getattr(model, "sr", 24_000))
                audio = _float_audio_to_wav(wav, sample_rate=sample_rate)
            response = {
                "ok": True,
                "audio": base64.b64encode(audio).decode("ascii"),
                "sample_rate": sample_rate,
                "device": device,
            }
        except Exception as exc:  # pragma: no cover - exercised via parent process integration
            response = {"ok": False, "error": str(exc) or exc.__class__.__name__}

        _PROTOCOL_STDOUT.write(json.dumps(response) + "\n")
        _PROTOCOL_STDOUT.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
