from __future__ import annotations

import argparse
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

from .config_store import ConfigStore
from .providers import build_transcriber
from .runtime import VoiceRuntime
from .text import detect_voice_control_command, split_send_phrase


@dataclass(slots=True)
class CalibrationResult:
    path: Path
    heard: str
    action: str
    matched: bool
    duration_seconds: float


def _read_wav_pcm16(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        audio_bytes = wav_file.readframes(frame_count)

    if channels != 1:
        raise ValueError(f"{path}: expected mono WAV, got {channels} channels")
    if sample_width != 2:
        raise ValueError(f"{path}: expected 16-bit PCM WAV, got sample width {sample_width}")
    if sample_rate != 16000:
        raise ValueError(f"{path}: expected 16kHz WAV, got {sample_rate}Hz")
    return audio_bytes


def _expand_paths(paths: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            resolved.extend(sorted(item for item in path.iterdir() if item.suffix.lower() == ".wav"))
            continue
        resolved.append(path)
    return resolved


def resolve_command_action(text: str, *, send_phrase: str) -> str:
    action = detect_voice_control_command(text) or ""
    if action:
        return action

    candidate_phrases = ((send_phrase,) if send_phrase else tuple()) + ("go",)
    for phrase in candidate_phrases:
        _, matched_send_phrase = split_send_phrase(text, phrase)
        if matched_send_phrase:
            return "send"
    return ""


def evaluate_samples(
    sample_paths: list[Path],
    *,
    expected_action: str,
    send_phrase: str,
) -> list[CalibrationResult]:
    settings = VoiceRuntime._interrupt_stt_settings(ConfigStore().load_runtime_settings()["stt"])
    transcriber = build_transcriber(settings)
    results: list[CalibrationResult] = []

    for path in sample_paths:
        audio_bytes = _read_wav_pcm16(path)
        transcription = transcriber.transcribe(audio_bytes)
        heard = transcription.text.strip()
        action = resolve_command_action(heard, send_phrase=send_phrase)
        results.append(
            CalibrationResult(
                path=path,
                heard=heard,
                action=action,
                matched=action == expected_action,
                duration_seconds=transcription.duration_seconds,
            )
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay recorded voice-command WAVs through the configured STT path and report hit rate."
    )
    parser.add_argument("paths", nargs="+", help="WAV files or directories containing WAV files")
    parser.add_argument(
        "--expected-action",
        choices=["interrupt", "pause", "send"],
        default="send",
        help="Command action you expect Whisper to resolve",
    )
    parser.add_argument(
        "--send-phrase",
        default="hey go",
        help="Trailing send phrase used for expected-action=send",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sample_paths = _expand_paths(args.paths)
    if not sample_paths:
        parser.error("No WAV files found.")

    missing = [path for path in sample_paths if not path.exists()]
    if missing:
        parser.error(f"Missing file: {missing[0]}")

    try:
        results = evaluate_samples(
            sample_paths,
            expected_action=args.expected_action,
            send_phrase=args.send_phrase,
        )
    except ValueError as exc:
        parser.error(str(exc))

    hits = sum(1 for result in results if result.matched)
    total = len(results)
    print(f"expected_action={args.expected_action} send_phrase={args.send_phrase!r}")
    print(f"hit_rate={hits}/{total} ({(hits / total) * 100:.1f}%)")
    print()
    for result in results:
        status = "hit" if result.matched else "miss"
        print(
            f"{status:4}  {result.path}  action={result.action or '-'}  "
            f"duration={result.duration_seconds:.2f}s  heard={result.heard!r}"
        )
    return 0 if hits == total else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
