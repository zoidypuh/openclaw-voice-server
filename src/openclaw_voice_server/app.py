from __future__ import annotations

import asyncio
import logging
import sys

from .config import VoiceServerConfig
from .gateway import OpenClawGatewayClient
from .service import VoiceServer
from .stt import FasterWhisperTranscriber
from .tts import ElevenLabsSynthesizer


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    configure_logging()
    config = VoiceServerConfig.from_env()
    try:
        config.validate()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    transcriber = FasterWhisperTranscriber(config)
    transcriber.load()

    server = VoiceServer(
        config=config,
        transcriber=transcriber,
        tts=ElevenLabsSynthesizer(config),
        gateway=OpenClawGatewayClient(config),
    )

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Shutting down voice server")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

