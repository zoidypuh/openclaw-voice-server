from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import re
from typing import Any

import httpx


DEFAULT_SPEAK_ENDPOINT = "http://127.0.0.1:8765/api/runtime/speak"
DEFAULT_TIMEOUT_SECONDS = 15.0


def split_paragraphs(text: str) -> list[str]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n+", normalized)
    paragraphs: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        paragraph = " ".join(lines).strip()
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def _build_payload(
    text: str,
    *,
    timeout_seconds: float,
    preset_name: str | None,
    speaker_name: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": text,
        "timeout_seconds": float(timeout_seconds),
    }
    if preset_name:
        payload["preset_name"] = preset_name
    if speaker_name:
        payload["speaker_name"] = speaker_name
    return payload


def speak_paragraphs(
    paragraphs: list[str],
    *,
    endpoint_url: str = DEFAULT_SPEAK_ENDPOINT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    preset_name: str | None = None,
    speaker_name: str | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    own_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds + 5.0)
    try:
        results: list[dict[str, Any]] = []
        for paragraph in paragraphs:
            payload = _build_payload(
                paragraph,
                timeout_seconds=timeout_seconds,
                preset_name=preset_name,
                speaker_name=speaker_name,
            )
            response = http_client.post(endpoint_url, json=payload)
            data: dict[str, Any]
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Speak request failed with HTTP {response.status_code} and a non-JSON response."
                ) from exc
            if response.status_code >= 400 or not data.get("ok"):
                error = str(data.get("error") or response.reason_phrase or "Unknown error")
                raise RuntimeError(f"Speak request failed with HTTP {response.status_code}: {error}")
            results.append(data)
        return results
    finally:
        if own_client:
            http_client.close()


def _read_input_text(*, text_parts: list[str], file_path: str | None) -> str:
    if text_parts:
        return " ".join(text_parts).strip()
    if file_path:
        return Path(file_path).read_text(encoding="utf-8")
    return sys.stdin.read()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Split text into paragraphs and send each paragraph to the voice server TTS endpoint."
    )
    parser.add_argument("text", nargs="*", help="Text to speak. If omitted, reads from --file or stdin.")
    parser.add_argument("--file", help="Read text from a UTF-8 file instead of stdin.")
    parser.add_argument("--url", default=DEFAULT_SPEAK_ENDPOINT, help="Speak endpoint URL.")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-paragraph timeout_seconds sent to /api/runtime/speak.",
    )
    parser.add_argument("--preset-name", help="Optional reply style preset.")
    parser.add_argument("--speaker-name", help="Optional speaker override.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.file and args.text:
        parser.error("Pass either inline text or --file, not both.")
    raw_text = _read_input_text(text_parts=args.text, file_path=args.file)
    paragraphs = split_paragraphs(raw_text)
    if not paragraphs:
        parser.error("No paragraphs found to speak.")

    results = speak_paragraphs(
        paragraphs,
        endpoint_url=args.url,
        timeout_seconds=args.timeout_seconds,
        preset_name=args.preset_name,
        speaker_name=args.speaker_name,
    )

    print(f"Sent {len(results)} paragraph(s) to {args.url}")
    for index, result in enumerate(results, start=1):
        spoken_text = str(result.get("spoken_text") or "")
        audio_bytes = int(result.get("audio_bytes") or 0)
        print(f"[{index}/{len(results)}] {audio_bytes} bytes :: {spoken_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
