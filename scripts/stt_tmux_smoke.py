#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from maras_switchboard.config_store import ConfigStore
from maras_switchboard.runtime import _send_transcript_to_tmux


async def main() -> int:
    target_id = ""
    args = list(sys.argv[1:])
    if args[:1] == ["--target"] and len(args) >= 2:
        target_id = args[1]
        args = args[2:]
    text = " ".join(args).strip() or "switchboard tmux smoke test"
    settings = ConfigStore(config_path=ROOT / "config.json", env_path=ROOT / ".env").load_runtime_settings()
    sent = await _send_transcript_to_tmux(text, settings, target_id=target_id)
    print(f"{sent['target_id']} {sent['target']}: {sent['payload']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
