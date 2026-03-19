from __future__ import annotations

import time
from typing import Callable

from .errors import ValidationError


ALLOWED_WINDOWS_CLIENT_STATES = {
    "listening",
    "thinking",
    "speaking",
    "reconnecting",
    "paused",
}


class WindowsClientStateStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = 15.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.clock = clock or time.monotonic
        self._records: dict[str, dict[str, float | str]] = {}

    def update(self, shell_id: str, state: str) -> dict[str, object]:
        shell_id = (shell_id or "").strip()
        state = (state or "").strip().lower()
        if not shell_id:
            raise ValidationError("shell_id is required")
        if state not in ALLOWED_WINDOWS_CLIENT_STATES:
            raise ValidationError(f"unsupported windows client state: {state or 'unknown'}")
        now = self.clock()
        self._records[shell_id] = {"state": state, "updated_at": now}
        self._prune(now)
        return self.snapshot(shell_id)

    def snapshot(self, shell_id: str) -> dict[str, object]:
        shell_id = (shell_id or "").strip()
        now = self.clock()
        self._prune(now)
        if not shell_id:
            return {
                "ok": True,
                "shell_id": "",
                "known": False,
                "state": "reconnecting",
                "stale": True,
                "age_seconds": None,
            }
        record = self._records.get(shell_id)
        if record is None:
            return {
                "ok": True,
                "shell_id": shell_id,
                "known": False,
                "state": "reconnecting",
                "stale": True,
                "age_seconds": None,
            }
        age_seconds = max(0.0, now - float(record["updated_at"]))
        stale = age_seconds > self.ttl_seconds
        return {
            "ok": True,
            "shell_id": shell_id,
            "known": True,
            "state": "reconnecting" if stale else str(record["state"]),
            "stale": stale,
            "age_seconds": age_seconds,
        }

    def _prune(self, now: float) -> None:
        cutoff = now - self.ttl_seconds
        expired = [
            shell_id
            for shell_id, record in self._records.items()
            if float(record["updated_at"]) < cutoff
        ]
        for shell_id in expired:
            self._records.pop(shell_id, None)
