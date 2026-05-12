from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "voice_reliability_smoke.py"
SPEC = importlib.util.spec_from_file_location("voice_reliability_smoke", SCRIPT_PATH)
assert SPEC is not None
smoke = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = smoke
SPEC.loader.exec_module(smoke)


def http_result(status: int | None, text: str, *, ok: bool = False):
    return smoke.HttpResult(
        ok=ok,
        status=status,
        body=smoke.parse_json_object(text),
        text=text,
        error="",
        elapsed_seconds=0.1,
    )


def test_classifies_no_active_voice_client():
    result = http_result(400, '{"ok": false, "error": "No active voice client is connected."}')

    label, action = smoke.classify_speak_result(result, voice_client={}, recent_log_text="")

    assert label == "no_client"
    assert "Open or refresh" in action


def test_classifies_disconnected_client_before_playback():
    result = http_result(
        400,
        '{"ok": false, "error": "The active voice client disconnected before playback."}',
    )

    label, action = smoke.classify_speak_result(
        result,
        voice_client={"active_voice_client": True, "playback_accept": True},
        recent_log_text="",
    )

    assert label == "disconnected_client"
    assert "Refresh" in action


def test_classifies_stale_active_voice_client():
    result = http_result(
        400,
        '{"ok": false, "error": "Active voice client is stale; focus or refresh /voice to re-register playback."}',
    )

    label, action = smoke.classify_speak_result(
        result,
        voice_client={"active_voice_client": False, "playback_accept": False, "client_status": "stale_websocket"},
        recent_log_text="",
    )

    assert label == "stale_client"
    assert "fresh playback-ready heartbeat" in action


def test_classifies_paused_voice_client():
    result = http_result(400, '{"ok": false, "error": "The voice client is paused."}')

    label, action = smoke.classify_speak_result(
        result,
        voice_client={"active_voice_client": True, "playback_accept": True, "client_status": "ready"},
        recent_log_text="",
    )

    assert label == "paused_client"
    assert "Turn voice ON" in action


def test_classifies_playback_acceptance_timeout():
    result = http_result(
        504,
        '{"ok": false, "error": "Timed out waiting for the active voice client to accept playback."}',
    )

    label, action = smoke.classify_speak_result(
        result,
        voice_client={"active_voice_client": True, "playback_accept": True, "pending_playback_accepts": 1},
        recent_log_text="",
    )

    assert label == "playback_accept_timeout"
    assert "acknowledge audio start" in action


def test_classifies_ready_state_that_times_out_then_self_marks_timeout():
    result = http_result(
        504,
        '{"ok": false, "error": "Timed out waiting for the active voice client to accept playback."}',
    )

    label, action = smoke.classify_speak_result(
        result,
        voice_client={"active_voice_client": True, "playback_accept": True, "client_status": "ready"},
        post_voice_client={"active_voice_client": True, "playback_accept": False, "client_status": "accept_timed_out"},
        recent_log_text="",
    )

    assert label == "state_claimed_ready_accept_timeout"
    assert "said ready before the smoke" in action


def test_classifies_state_truthfulness_bug_when_timeout_still_claims_ready():
    result = http_result(
        504,
        '{"ok": false, "error": "Timed out waiting for the active voice client to accept playback."}',
    )

    label, action = smoke.classify_speak_result(
        result,
        voice_client={"active_voice_client": True, "playback_accept": True, "client_status": "ready"},
        post_voice_client={"active_voice_client": True, "playback_accept": True, "client_status": "ready"},
        recent_log_text="",
    )

    assert label == "state_truthfulness_bug"
    assert "still claims playback ready" in action


def test_classifies_client_not_ready_when_speak_is_skipped():
    label, action = smoke.classify_speak_result(
        None,
        voice_client={"active_voice_client": True, "playback_accept": False},
        recent_log_text="",
    )

    assert label == "client_not_ready"
    assert "playback_accept" in action


def test_stale_recent_log_does_not_override_unreachable_speak_result():
    result = smoke.HttpResult(
        ok=False,
        status=None,
        body=None,
        text="",
        error="[Errno 111] Connection refused",
        elapsed_seconds=0.1,
    )

    label, action = smoke.classify_speak_result(
        result,
        voice_client={"active_voice_client": True, "playback_accept": True},
        recent_log_text="older: The active voice client disconnected before playback.",
    )

    assert label == "server_unreachable"
    assert "restart" in action


def test_recent_error_shape_uses_last_known_error():
    label, detail = smoke.recent_error_shape(
        "\n".join(
            [
                "older: No active voice client is connected.",
                "newer: The active voice client disconnected before playback.",
            ]
        )
    )

    assert label == "disconnected_client"
    assert "disconnected before playback" in detail
