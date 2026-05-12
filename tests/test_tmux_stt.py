import asyncio

import pytest

from maras_switchboard.errors import ValidationError
from maras_switchboard.runtime import (
    TMUX_ENTER_KEY,
    VoiceTurnMetrics,
    _send_transcript_to_tmux,
    public_tmux_targets,
)


def test_voice_turn_metrics_accepts_tmux_target_for_audio_commit_path():
    turn = VoiceTurnMetrics(tmux_target="main-codex")

    assert turn.tmux_target == "main-codex"


def test_send_transcript_to_tmux_uses_selected_registry_target_and_prefix(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))

        class Result:
            stdout = "pane tail"

        return Result()

    monkeypatch.setattr("maras_switchboard.runtime.subprocess.run", fake_run)

    sent = asyncio.run(
        _send_transcript_to_tmux(
            "hello world",
            {
                "tmux": {
                    "selected_target": "mara",
                    "targets": {
                        "mara": {"label": "Mara", "target": "mara:0.1", "prefix": "/queue"},
                        "main-codex": {"label": "Main Codex", "target": "codex1:0.0", "prefix": ""},
                    },
                }
            },
        )
    )

    assert sent["target_id"] == "mara"
    assert sent["target"] == "mara:0.1"
    assert sent["payload"] == "/queue [G] hello world"
    assert sent["pane_tail"] == "pane tail"
    assert calls[0][0] == ["tmux", "display-message", "-p", "-t", "mara:0.1", "#{pane_id}"]
    assert calls[1][0][:3] == ["tmux", "set-buffer", "-b"]
    assert calls[1][0][-1] == "/queue [G] hello world"
    assert calls[2][0][:3] == ["tmux", "paste-buffer", "-t"]
    assert calls[2][0][3] == "mara:0.1"
    assert calls[3][0] == ["tmux", "send-keys", "-t", "mara:0.1", TMUX_ENTER_KEY]
    assert calls[5][0] == ["tmux", "capture-pane", "-t", "mara:0.1", "-p", "-S", "-20"]
    assert calls[0][1]["check"] is True


def test_send_transcript_to_tmux_allows_request_target_override(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)

        class Result:
            stdout = ""

        return Result()

    monkeypatch.setattr("maras_switchboard.runtime.subprocess.run", fake_run)

    sent = asyncio.run(
        _send_transcript_to_tmux(
            "status please",
            {
                "tmux": {
                    "selected_target": "mara",
                    "targets": {
                        "mara": {"target": "mara:0.0", "prefix": "/queue"},
                        "main-codex": {"target": "codex1:0.0", "prefix": ""},
                    },
                }
            },
            target_id="main-codex",
        )
    )

    assert sent["target_id"] == "main-codex"
    assert sent["target"] == "codex1:0.0"
    assert sent["payload"] == "[G] status please"
    assert calls[0] == ["tmux", "display-message", "-p", "-t", "codex1:0.0", "#{pane_id}"]
    assert calls[1][:3] == ["tmux", "set-buffer", "-b"]
    assert calls[1][-1] == "[G] status please"
    assert calls[2][:3] == ["tmux", "paste-buffer", "-t"]
    assert calls[3] == ["tmux", "send-keys", "-t", "codex1:0.0", TMUX_ENTER_KEY]
    assert calls[4][:3] == ["tmux", "delete-buffer", "-b"]
    assert calls[5] == ["tmux", "capture-pane", "-t", "codex1:0.0", "-p", "-S", "-20"]


def test_tmux_routing_contract_writes_payload_then_enter_before_tail_capture(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)

        class Result:
            stdout = "tail"

        return Result()

    monkeypatch.setattr("maras_switchboard.runtime.subprocess.run", fake_run)

    sent = asyncio.run(
        _send_transcript_to_tmux(
            "line one\nline two",
            {
                "tmux": {
                    "selected_target": "mara",
                    "targets": {
                        "mara": {"target": "mara:0.0", "prefix": "/queue"},
                    },
                }
            },
        )
    )

    assert sent["payload"] == "/queue [G] line one\nline two"
    write_commands = calls[1:4]
    assert write_commands[0][:3] == ["tmux", "set-buffer", "-b"]
    assert write_commands[0][-1] == "/queue [G] line one\nline two"
    assert write_commands[1][:3] == ["tmux", "paste-buffer", "-t"]
    assert write_commands[2] == ["tmux", "send-keys", "-t", "mara:0.0", TMUX_ENTER_KEY]


def test_tmux_routing_does_not_duplicate_gis_source_marker(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)

        class Result:
            stdout = ""

        return Result()

    monkeypatch.setattr("maras_switchboard.runtime.subprocess.run", fake_run)

    sent = asyncio.run(
        _send_transcript_to_tmux(
            "[G] already marked",
            {
                "tmux": {
                    "selected_target": "main-codex",
                    "targets": {
                        "main-codex": {"target": "codex1:0.0", "prefix": ""},
                    },
                }
            },
        )
    )

    assert sent["payload"] == "[G] already marked"
    assert calls[1][-1] == "[G] already marked"
    assert calls[3] == ["tmux", "send-keys", "-t", "codex1:0.0", TMUX_ENTER_KEY]


def test_public_tmux_targets_exposes_labels_without_raw_targets():
    public = public_tmux_targets(
        {
            "tmux": {
                "selected_target": "main-codex",
                "targets": {
                    "mara": {"label": "Mara", "target": "mara:0.0", "prefix": "/queue"},
                    "main-codex": {"label": "Main Codex", "target": "codex1:0.0", "prefix": ""},
                },
            }
        }
    )

    assert public == {
        "selected": "main-codex",
        "choices": [
            {"id": "mara", "label": "Mara", "configured": True},
            {"id": "main-codex", "label": "Main Codex", "configured": True},
        ],
    }


def test_send_transcript_to_tmux_requires_target(monkeypatch):
    monkeypatch.delenv("MARAS_SWITCHBOARD_TMUX_TARGET", raising=False)

    with pytest.raises(ValidationError, match="Missing tmux target"):
        asyncio.run(_send_transcript_to_tmux("hello", {}))
