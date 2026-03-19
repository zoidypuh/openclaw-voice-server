from openclaw_voice_server.windows_client_state import WindowsClientStateStore
from openclaw_voice_server.errors import ValidationError


def test_windows_client_state_store_tracks_and_expires_status():
    now = 100.0

    def clock() -> float:
        return now

    store = WindowsClientStateStore(ttl_seconds=5.0, clock=clock)

    initial = store.snapshot("shell-1")
    assert initial["state"] == "reconnecting"
    assert initial["known"] is False
    assert initial["stale"] is True

    updated = store.update("shell-1", "thinking")
    assert updated["state"] == "thinking"
    assert updated["known"] is True
    assert updated["stale"] is False

    now = 103.0
    fresh = store.snapshot("shell-1")
    assert fresh["state"] == "thinking"
    assert fresh["stale"] is False

    now = 106.5
    expired = store.snapshot("shell-1")
    assert expired["state"] == "reconnecting"
    assert expired["known"] is False
    assert expired["stale"] is True


def test_windows_client_state_store_rejects_invalid_input():
    store = WindowsClientStateStore()

    try:
        store.update("", "listening")
    except ValidationError as exc:
        assert "shell_id" in str(exc)
    else:  # pragma: no cover - defensive guard
        raise AssertionError("expected ValidationError for empty shell_id")

    try:
        store.update("shell-1", "invalid")
    except ValidationError as exc:
        assert "unsupported" in str(exc)
    else:  # pragma: no cover - defensive guard
        raise AssertionError("expected ValidationError for invalid state")
