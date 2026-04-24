from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import NoReturn

from aiohttp import web

from .catalog import APP_VERSION_LABEL, normalize_agent_backend
from .config_store import ConfigStore
from .errors import ValidationError
from .runtime import VoiceRuntime
from .setup_service import SetupService
from .windows_client_state import WindowsClientStateStore


LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    from rich.logging import RichHandler

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False, markup=True)],
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    # Silence noisy loggers
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _static_dir() -> Path:
    return Path(__file__).with_name("static")


def _media_dir() -> Path:
    repo_media = Path(__file__).resolve().parents[2] / "media"
    if repo_media.is_dir():
        return repo_media
    return _static_dir() / "media"


def _default_avatar_preset(saved: dict[str, object]) -> str:
    agent = saved.get("agent") if isinstance(saved, dict) else {}
    gateway = saved.get("gateway") if isinstance(saved, dict) else {}

    backend = normalize_agent_backend((agent or {}).get("backend")) if isinstance(agent, dict) else "gateway"
    if backend == "hermes":
        return "girl"

    model = str((gateway or {}).get("model") or "").strip().lower() if isinstance(gateway, dict) else ""
    if any(token in model for token in ("maras-switchboard", "maras", "switchboard", "lobster")):
        return "lobster"
    if any(token in model for token in ("hermes", "mara", "claude", "sonnet", "gpt")):
        return "girl"
    return "girl"


def _runtime_ready(setup_service: SetupService) -> bool:
    return bool(setup_service.state()["status"]["runtime_ready"])


def _html_file_response(path: Path) -> web.FileResponse:
    response = web.FileResponse(path)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def create_app() -> web.Application:
    store = ConfigStore()
    setup_service = SetupService(store)
    runtime = VoiceRuntime(store)
    windows_client_state = WindowsClientStateStore()
    static_dir = _static_dir()
    media_dir = _media_dir()
    legacy_ui_prefixes = ("/voice", "/setup")

    def add_route(method: str, path: str, handler) -> None:
        app.router.add_route(method, path, handler)
        if path.startswith("/api/") or path.startswith("/ws/"):
            for prefix in legacy_ui_prefixes:
                app.router.add_route(method, f"{prefix}{path}", handler)

    async def root(request: web.Request) -> web.StreamResponse:
        if _runtime_ready(setup_service):
            return _html_file_response(static_dir / "voice.html")
        return _html_file_response(static_dir / "setup.html")

    def canonical_path_redirect(target: str) -> None:
        raise web.HTTPPermanentRedirect(location=target)

    async def setup_page(request: web.Request) -> web.FileResponse:
        return _html_file_response(static_dir / "setup.html")

    async def setup_page_slash(request: web.Request) -> NoReturn:
        canonical_path_redirect("/setup")

    async def voice_page(request: web.Request) -> web.StreamResponse:
        return _html_file_response(static_dir / "voice.html")

    async def voice_page_slash(request: web.Request) -> NoReturn:
        canonical_path_redirect("/voice")

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
                "avatar": {
                    "default_preset": _default_avatar_preset(state["saved"]),
                },
                "windows_client": state["saved"]["windows_client"],
            }
        )

    async def runtime_speech_probe(request: web.Request) -> web.Response:
        return await runtime.handle_speech_probe(request)

    async def runtime_speak(request: web.Request) -> web.Response:
        return await runtime.handle_speak_request(request)

    async def windows_client_status(request: web.Request) -> web.Response:
        shell_id = request.query.get("shell_id", "")
        return web.json_response(windows_client_state.snapshot(shell_id))

    async def parse_json(request: web.Request) -> dict:
        if request.can_read_body:
            return await request.json()
        return {}

    async def update_windows_client_status(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        return web.json_response(
            windows_client_state.update(
                str(payload.get("shell_id", "")),
                str(payload.get("state", "")),
            )
        )

    async def validate_gateway(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = await setup_service.validate_gateway(payload)
        return web.json_response(result)

    async def validate_agent(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = await setup_service.validate_agent(payload)
        return web.json_response(result)

    async def validate_windows_client(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = setup_service.validate_windows_client(payload)
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

    async def validate_supertonic(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = await setup_service.validate_supertonic(payload)
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
    add_route("GET", "/", root)
    add_route("GET", "/setup", setup_page)
    add_route("GET", "/setup/", setup_page_slash)
    add_route("GET", "/voice", voice_page)
    add_route("GET", "/voice/", voice_page_slash)
    add_route("GET", "/health", health)
    add_route("GET", "/api/setup/state", setup_state)
    add_route("GET", "/api/runtime/state", runtime_state)
    add_route("POST", "/api/runtime/speech-probe", runtime_speech_probe)
    add_route("POST", "/api/runtime/speak", runtime_speak)
    add_route("GET", "/api/windows-client/status", windows_client_status)
    add_route("POST", "/api/windows-client/status", update_windows_client_status)
    add_route("POST", "/api/setup/validate-gateway", validate_gateway)
    add_route("POST", "/api/setup/validate-agent", validate_agent)
    add_route("POST", "/api/setup/validate-windows-client", validate_windows_client)
    add_route("POST", "/api/setup/validate-stt", validate_stt)
    add_route("POST", "/api/setup/validate-tts", validate_tts)
    add_route("GET", "/api/setup/edge-voices", edge_voices)
    add_route("POST", "/api/setup/validate-edge", validate_edge)
    add_route("POST", "/api/setup/validate-eleven-key", validate_eleven_key)
    add_route("POST", "/api/setup/validate-supertonic", validate_supertonic)
    add_route("GET", "/api/setup/eleven-voices", eleven_voices)
    add_route("POST", "/api/setup/validate-eleven-voice", validate_eleven_voice)
    add_route("GET", "/ws/voice", runtime.handle_ws)
    app.router.add_static("/static", static_dir)
    app.router.add_static("/media", media_dir)
    return app


def main() -> int:
    configure_logging()
    app = create_app()
    settings = ConfigStore().load_config()["server"]
    try:
        web.run_app(
            app,
            host=settings["host"],
            port=int(settings["port"]),
            access_log=None,
        )
    except KeyboardInterrupt:
        LOGGER.info("Shutting down voice server")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
