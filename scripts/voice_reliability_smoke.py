#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_SERVICE = "maras-switchboard.service"
DEFAULT_TEXT = "Voice reliability smoke test."
ERROR_PATTERNS = (
    ("no_client", ("No active voice client is connected.", "no active voice client")),
    ("stale_client", ("Active voice client is stale", "stale voice client", "stale_websocket")),
    ("disconnected_client", ("active voice client disconnected before playback", "disconnected before playback")),
    ("playback_accept_timeout", ("Timed out waiting for the active voice client to accept playback",)),
    ("paused_client", ("The voice client is paused.", "voice client is paused")),
    ("playback_rejected", ("active voice client rejected playback", "playback rejected")),
    ("tts_disabled", ("TTS is disabled",)),
    ("empty_tts", ("Speech synthesis returned no audio",)),
    ("runtime_init", ("Voice runtime initialization failed",)),
    ("websocket_error", ("WebSocket error",)),
)
LOCAL_TTS_WORKER_PATTERNS = (
    "supertonic_worker.py",
    "chatterbox_turbo_worker.py",
)


@dataclass
class HttpResult:
    ok: bool
    status: int | None
    body: dict[str, Any] | None
    text: str
    error: str
    elapsed_seconds: float


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str


def run_command(args: list[str], *, timeout: float = 5.0) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(ok=False, stdout="", stderr=str(exc))
    return CommandResult(
        ok=completed.returncode == 0,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> HttpResult:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    started = time.perf_counter()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            elapsed = time.perf_counter() - started
            return HttpResult(
                ok=200 <= response.status < 300,
                status=response.status,
                body=parse_json_object(raw),
                text=raw,
                error="",
                elapsed_seconds=elapsed,
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        elapsed = time.perf_counter() - started
        return HttpResult(
            ok=False,
            status=exc.code,
            body=parse_json_object(raw),
            text=raw,
            error=str(exc),
            elapsed_seconds=elapsed,
        )
    except (OSError, TimeoutError) as exc:
        elapsed = time.perf_counter() - started
        return HttpResult(
            ok=False,
            status=None,
            body=None,
            text="",
            error=str(exc),
            elapsed_seconds=elapsed,
        )


def parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def classify_text(text: str) -> str:
    lowered = text.lower()
    for label, patterns in ERROR_PATTERNS:
        if any(pattern.lower() in lowered for pattern in patterns):
            return label
    return ""


def classify_speak_result(
    speak: HttpResult | None,
    *,
    voice_client: dict[str, Any],
    post_voice_client: dict[str, Any] | None = None,
    recent_log_text: str,
) -> tuple[str, str]:
    active_client = bool(voice_client.get("active_voice_client"))
    playback_accept = bool(voice_client.get("playback_accept"))
    pending_accepts = int(voice_client.get("pending_playback_accepts") or 0)
    client_status = str(voice_client.get("client_status") or "")
    post_voice_client = post_voice_client if isinstance(post_voice_client, dict) else {}
    post_client_status = str(post_voice_client.get("client_status") or "")
    post_playback_accept = bool(post_voice_client.get("playback_accept"))

    if speak is None:
        if not active_client:
            return ("no_client", "Open or refresh /voice so a browser voice client connects.")
        if not playback_accept:
            return (
                "client_not_ready",
                "Refresh /voice; the websocket is connected but did not report playback_accept support.",
            )
        return ("not_run", "Speak test skipped.")

    speak_text = " ".join(
        part
        for part in (
            speak.error,
            speak.text,
        )
        if part
    )
    direct = classify_text(speak_text)
    log_direct = classify_text(recent_log_text)
    if speak.ok:
        return ("ok", "Speak request completed; browser accepted playback.")
    if speak.status is None:
        return ("server_unreachable", "Start or restart the Switchboard service, then rerun the smoke.")
    if direct == "stale_client" or client_status == "stale_websocket":
        return ("stale_client", "Focus or refresh the existing /voice tab so it sends a fresh playback-ready heartbeat.")
    if direct == "no_client" or not active_client:
        return ("no_client", "Open or refresh http://127.0.0.1:8765/voice, then rerun the smoke.")
    if direct == "disconnected_client":
        return ("disconnected_client", "Refresh the existing /voice tab; the server saw the client drop mid-playback.")
    if direct == "paused_client":
        return ("paused_client", "Turn voice ON in the /voice page, then rerun the smoke.")
    if direct == "playback_accept_timeout" or speak.status == 504:
        if playback_accept and client_status == "ready":
            if post_client_status == "accept_timed_out" and not post_playback_accept:
                return (
                    "state_claimed_ready_accept_timeout",
                    "Runtime said ready before the smoke, but the browser never accepted playback; focus /voice to re-register.",
                )
            return (
                "state_truthfulness_bug",
                "Runtime state still claims playback ready after an acceptance timeout; inspect playback readiness bookkeeping.",
            )
        if pending_accepts or playback_accept:
            return (
                "playback_accept_timeout",
                "The browser did not acknowledge audio start. Refresh /voice and make one user gesture to unlock audio.",
            )
        return (
            "tts_or_server_timeout",
            "The speak endpoint timed out before playback was accepted; check TTS provider readiness and worker logs.",
        )
    if direct in {"tts_disabled", "empty_tts"}:
        return (direct, "Fix TTS provider configuration in /setup before testing playback.")
    if direct == "playback_rejected":
        return ("playback_rejected", "Browser rejected playback; refresh /voice and unlock audio with the start control.")
    if log_direct:
        return (log_direct, "The speak result was ambiguous; inspect the recent service log line printed below.")
    return ("unknown_failure", "Check the recent service log lines printed below.")


def port_from_base_url(base_url: str) -> int:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.port:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    return 80


def port_listener_lines(port: int) -> list[str]:
    result = run_command(["ss", "-ltnp"], timeout=5)
    if not result.ok and not result.stdout:
        return [f"ss failed: {result.stderr}"]
    needle = f":{port}"
    return [line for line in result.stdout.splitlines() if needle in line] or ["no listener found"]


def service_state(service: str) -> str:
    result = run_command(["systemctl", "--user", "is-active", service], timeout=5)
    if result.ok:
        return result.stdout or "active"
    return result.stdout or result.stderr or "unknown"


def recent_service_logs(service: str, lines: int) -> str:
    result = run_command(["journalctl", "--user", "-u", service, "-n", str(lines), "--no-pager"], timeout=5)
    if result.ok or result.stdout:
        return result.stdout
    return result.stderr


def recent_error_shape(log_text: str) -> tuple[str, str]:
    matches: list[str] = []
    for line in log_text.splitlines():
        if classify_text(line):
            matches.append(line.strip())
    if not matches:
        return ("none", "No known recent voice playback error pattern found in service logs.")
    last = matches[-1]
    return (classify_text(last) or "unknown", last[-500:])


def tts_worker_lines() -> list[str]:
    result = run_command(["ps", "-eo", "pid=,args="], timeout=5)
    if not result.ok and not result.stdout:
        return [f"ps failed: {result.stderr}"]
    lines = []
    for line in result.stdout.splitlines():
        if any(pattern in line for pattern in LOCAL_TTS_WORKER_PATTERNS):
            lines.append(line.strip())
    return lines or ["no local TTS worker process found; this is expected for xAI/Edge/ElevenLabs TTS"]


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def print_block(title: str, lines: list[str]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for line in lines:
        print(line)


def summarize_setup(setup_state: dict[str, Any] | None) -> list[str]:
    if not setup_state:
        return ["setup state unavailable"]
    status = setup_state.get("status") if isinstance(setup_state.get("status"), dict) else {}
    saved = setup_state.get("saved") if isinstance(setup_state.get("saved"), dict) else {}
    tts = saved.get("tts") if isinstance(saved.get("tts"), dict) else {}
    interesting_status = {
        key: status.get(key)
        for key in (
            "runtime_ready",
            "tts_selection_ready",
            "xai_tts_ready",
            "supertonic_ready",
            "chatterbox_turbo_ready",
        )
        if key in status
    }
    return [
        f"status={compact_json(interesting_status)}",
        f"tts.default_provider={tts.get('default_provider', '-')}",
        f"tts.enabled_providers={compact_json(tts.get('enabled_providers', []))}",
    ]


def summarize_runtime(runtime_state: dict[str, Any] | None) -> tuple[list[str], dict[str, Any]]:
    if not runtime_state:
        return (["runtime state unavailable"], {})
    voice_client = runtime_state.get("voice_client")
    if not isinstance(voice_client, dict):
        voice_client = {}
    profile = runtime_state.get("voice_profiles") if isinstance(runtime_state.get("voice_profiles"), dict) else {}
    return (
        [
            f"runtime_ready={runtime_state.get('runtime_ready')}",
            f"profile.active={profile.get('active', '-')}",
            f"voice_client={compact_json(voice_client)}",
        ],
        voice_client,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke and diagnose Switchboard voice playback reliability.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--journal-lines", type=int, default=80)
    parser.add_argument("--no-speak", action="store_true", help="Collect diagnostics without POSTing /api/runtime/speak.")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    port = port_from_base_url(base_url)

    health = request_json(base_url, "/health", timeout=5)
    setup = request_json(base_url, "/api/setup/state", timeout=5)
    runtime = request_json(base_url, "/api/runtime/state", timeout=5)
    logs = recent_service_logs(args.service, args.journal_lines)
    error_label, error_detail = recent_error_shape(logs)
    runtime_lines, voice_client = summarize_runtime(runtime.body)
    post_runtime_lines: list[str] = []
    post_voice_client: dict[str, Any] = {}

    speak: HttpResult | None = None
    if not args.no_speak:
        speak = request_json(
            base_url,
            "/api/runtime/speak",
            method="POST",
            payload={"text": args.text, "timeout_seconds": args.timeout},
            timeout=args.timeout + 2.0,
        )
        post_runtime = request_json(base_url, "/api/runtime/state", timeout=5)
        post_runtime_lines, post_voice_client = summarize_runtime(post_runtime.body)

    diagnosis, action = classify_speak_result(
        speak,
        voice_client=voice_client,
        post_voice_client=post_voice_client,
        recent_log_text=logs,
    )

    print(f"Voice reliability smoke: {base_url}")
    print_block(
        "Server",
        [
            f"health.status={health.status} ok={health.ok} elapsed={health.elapsed_seconds:.3f}s",
            f"health.body={compact_json(health.body) if health.body else health.error or health.text}",
            f"service.{args.service}={service_state(args.service)}",
            *[f"port.{port} {line}" for line in port_listener_lines(port)],
        ],
    )
    print_block("Runtime", runtime_lines)
    if post_runtime_lines:
        print_block("Runtime After Speak", post_runtime_lines)
    print_block("Setup/TTS", summarize_setup(setup.body))
    print_block("TTS Worker", tts_worker_lines())
    print_block("Recent Error Shape", [f"{error_label}: {error_detail}"])
    if speak is None:
        speak_lines = ["skipped"]
    else:
        speak_body = compact_json(speak.body) if speak.body else speak.error or speak.text
        speak_lines = [
            f"status={speak.status} ok={speak.ok} elapsed={speak.elapsed_seconds:.3f}s",
            f"body={speak_body}",
        ]
    print_block("Speak Test", speak_lines)
    print_block("Diagnosis", [diagnosis, f"action: {action}"])

    if diagnosis in {"ok", "not_run"} and health.ok and runtime.ok:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
