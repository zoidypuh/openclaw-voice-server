from __future__ import annotations

import logging
import sys
from pathlib import Path

from aiohttp import web

from .catalog import APP_VERSION_LABEL
from .config_store import ConfigStore
from .errors import ValidationError
from .runtime import VoiceRuntime
from .setup_service import SetupService


LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _static_dir() -> Path:
    return Path(__file__).with_name("static")


def _runtime_ready(setup_service: SetupService) -> bool:
    return bool(setup_service.state()["status"]["runtime_ready"])


def create_app() -> web.Application:
    store = ConfigStore()
    setup_service = SetupService(store)
    runtime = VoiceRuntime(store)
    static_dir = _static_dir()

    async def root(request: web.Request) -> web.StreamResponse:
        if _runtime_ready(setup_service):
            return web.FileResponse(static_dir / "voice.html")
        return web.FileResponse(static_dir / "setup.html")

    async def setup_page(request: web.Request) -> web.FileResponse:
        return web.FileResponse(static_dir / "setup.html")

    async def voice_page(request: web.Request) -> web.StreamResponse:
        return web.FileResponse(static_dir / "voice.html")

    async def health(request: web.Request) -> web.Response:
        state = setup_service.state()
        return web.json_response(
            {
                "ok": True,
                "version": APP_VERSION_LABEL,
                "runtime_ready": state["status"]["runtime_ready"],
                "config_path": state["saved"]["config_path"],
                "env_path": state["saved"]["env_path"],
            }
        )

    async def setup_state(request: web.Request) -> web.Response:
        return web.json_response(setup_service.state())

    async def runtime_state(request: web.Request) -> web.Response:
        state = setup_service.state()
        return web.json_response(
            {
                "version_label": APP_VERSION_LABEL,
                "runtime_ready": state["status"]["runtime_ready"],
                "audio": state["saved"]["audio"],
            }
        )

    async def parse_json(request: web.Request) -> dict:
        if request.can_read_body:
            return await request.json()
        return {}

    async def validate_gateway(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = await setup_service.validate_gateway(payload)
        return web.json_response(result)

    async def validate_stt(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = setup_service.validate_stt(payload)
        return web.json_response(result)

    async def validate_tts(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = await setup_service.validate_tts_selection(payload)
        return web.json_response(result)

    async def edge_voices(request: web.Request) -> web.Response:
        result = await setup_service.edge_voices()
        return web.json_response(result)

    async def validate_edge(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = await setup_service.validate_edge(payload)
        return web.json_response(result)

    async def validate_eleven_key(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = await setup_service.validate_elevenlabs_key(payload)
        return web.json_response(result)

    async def eleven_voices(request: web.Request) -> web.Response:
        result = await setup_service.elevenlabs_voices()
        return web.json_response(result)

    async def validate_eleven_voice(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = await setup_service.validate_elevenlabs_voice(payload)
        return web.json_response(result)

    @web.middleware
    async def error_middleware(request: web.Request, handler):
        try:
            return await handler(request)
        except ValidationError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    app = web.Application(middlewares=[error_middleware])
    app.router.add_get("/", root)
    app.router.add_get("/setup", setup_page)
    app.router.add_get("/voice", voice_page)
    app.router.add_get("/health", health)
    app.router.add_get("/api/setup/state", setup_state)
    app.router.add_get("/api/runtime/state", runtime_state)
    app.router.add_post("/api/setup/validate-gateway", validate_gateway)
    app.router.add_post("/api/setup/validate-stt", validate_stt)
    app.router.add_post("/api/setup/validate-tts", validate_tts)
    app.router.add_get("/api/setup/edge-voices", edge_voices)
    app.router.add_post("/api/setup/validate-edge", validate_edge)
    app.router.add_post("/api/setup/validate-eleven-key", validate_eleven_key)
    app.router.add_get("/api/setup/eleven-voices", eleven_voices)
    app.router.add_post("/api/setup/validate-eleven-voice", validate_eleven_voice)
    app.router.add_get("/ws/voice", runtime.handle_ws)
    app.router.add_static("/static", static_dir)
    return app


def main() -> int:
    configure_logging()
    app = create_app()
    settings = ConfigStore().load_config()["server"]
    try:
        web.run_app(app, host=settings["host"], port=int(settings["port"]))
    except KeyboardInterrupt:
        LOGGER.info("Shutting down voice server")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
