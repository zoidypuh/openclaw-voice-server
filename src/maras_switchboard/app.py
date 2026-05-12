from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import NoReturn

from aiohttp import web

from .catalog import APP_VERSION_LABEL, normalize_agent_backend
from .config_store import ConfigStore
from .errors import ValidationError
from .runtime import VoiceRuntime, public_tmux_targets
from .setup_service import SetupService
from .windows_client_state import WindowsClientStateStore


LOGGER = logging.getLogger(__name__)
MARA_MEMORY_SENTINEL = os.environ.get(
    "MARA_MEMORY_SENTINEL", "/home/gismar/bin/mara-memory-sentinel"
)
MARA_MEMORY_STATUS_FILE = Path(
    os.environ.get(
        "MARA_MEMORY_STATUS_FILE",
        "/home/gismar/.hermes/status/mara-memory-status.json",
    )
)
QWEN_VOICE_MODEL = "gpu/qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive"
VENICE_VOICE_MODEL = "venice/venice-uncensored-1-2"
DEFAULT_HERMES_VOICE_API_URL = "http://127.0.0.1:8643/v1"
NADIA_VOICE_API_URL = "http://127.0.0.1:8645/v1"
MARA_VOICE_API_URL = "http://127.0.0.1:8644/v1"
LOLA_VOICE_API_URL = "http://127.0.0.1:8646/v1"
LOCAL_HERMES_API_KEY = "local-hermes-key"
DEFAULT_VOICE_PROFILE_ID = "lola"
VOICE_PROFILE_CHOICES = (
    {
        "id": "lola",
        "label": "Lola",
        "hermes_profile": "lola",
        "hermes_api_url": LOLA_VOICE_API_URL,
    },
    {
        "id": "mara",
        "label": "Mara",
        "hermes_profile": "voice-mara",
        "hermes_api_url": LOLA_VOICE_API_URL,
    },
)


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


def _read_mara_memory_status() -> dict[str, object]:
    if not MARA_MEMORY_STATUS_FILE.is_file():
        return {"available": False, "status_file": str(MARA_MEMORY_STATUS_FILE)}
    try:
        data = json.loads(MARA_MEMORY_STATUS_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "status_file": str(MARA_MEMORY_STATUS_FILE),
            "error": str(exc),
        }
    if isinstance(data, dict):
        data.setdefault("available", True)
        return data
    return {
        "available": False,
        "status_file": str(MARA_MEMORY_STATUS_FILE),
        "error": "status JSON is not an object",
    }


async def _run_mara_memory_sentinel_on_startup(app: web.Application) -> None:
    sentinel = Path(MARA_MEMORY_SENTINEL)
    if not sentinel.is_file():
        LOGGER.warning("Mara memory sentinel missing: %s", sentinel)
        app["mara_memory_startup"] = {
            "status": "missing",
            "sentinel": str(sentinel),
        }
        return
    if not os.access(sentinel, os.X_OK):
        LOGGER.warning("Mara memory sentinel is not executable: %s", sentinel)
        app["mara_memory_startup"] = {
            "status": "not_executable",
            "sentinel": str(sentinel),
        }
        return

    env = os.environ.copy()
    path_parts = [
        "/home/linuxbrew/.linuxbrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    existing_path = env.get("PATH")
    if existing_path:
        path_parts.append(existing_path)
    env["PATH"] = ":".join(path_parts)

    proc = await asyncio.create_subprocess_exec(
        str(sentinel),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=45)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        LOGGER.warning("Mara memory sentinel timed out during Switchboard startup")
        app["mara_memory_startup"] = {
            "status": "timeout",
            "sentinel": str(sentinel),
        }
        return

    output = stdout.decode(errors="replace")[-2000:] if stdout else ""
    app["mara_memory_startup"] = {
        "status": "ok" if proc.returncode == 0 else "fail",
        "exit_code": proc.returncode,
        "sentinel": str(sentinel),
        "output_tail": output,
    }
    if proc.returncode == 0:
        LOGGER.info("Mara memory sentinel OK during Switchboard startup")
    else:
        LOGGER.warning("Mara memory sentinel failed during startup: %s", output)


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


def _normalize_voice_profile(value: str) -> dict[str, str]:
    normalized = str(value or "").strip().lower()
    if normalized == "default":
        normalized = DEFAULT_VOICE_PROFILE_ID
    for profile in VOICE_PROFILE_CHOICES:
        if normalized in {
            str(profile["id"]).lower(),
            str(profile["label"]).lower(),
            str(profile["hermes_profile"]).lower(),
        }:
            return profile
    raise ValidationError("Choose a supported voice profile.")


def _default_voice_profile() -> dict[str, str]:
    return _normalize_voice_profile(DEFAULT_VOICE_PROFILE_ID)


def _public_voice_profile(profile: dict[str, str]) -> dict[str, str]:
    return {
        "id": profile["id"],
        "label": profile["label"],
        "hermes_profile": profile["hermes_profile"],
        "hermes_api_url": profile["hermes_api_url"],
    }


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

    async def speech_to_agent_page(request: web.Request) -> web.StreamResponse:
        return _html_file_response(static_dir / "speech-to-agent.html")

    async def speech_to_agent_page_slash(request: web.Request) -> NoReturn:
        canonical_path_redirect("/speech-to-agent")

    async def health(request: web.Request) -> web.Response:
        state = setup_service.state()
        return web.json_response(
            {
                "ok": True,
                "version": APP_VERSION_LABEL,
                "runtime_ready": state["status"]["runtime_ready"],
                "config_path": state["saved"]["config_path"],
                "env_path": state["saved"]["env_path"],
                "mara_memory": _read_mara_memory_status(),
                "mara_memory_startup": request.app.get("mara_memory_startup"),
            }
        )

    async def setup_state(request: web.Request) -> web.Response:
        return web.json_response(setup_service.state())

    async def runtime_state(request: web.Request) -> web.Response:
        state = setup_service.state()
        agent = state["saved"]["agent"]
        current_profile = str(agent.get("hermes_profile") or "").strip()
        active_profile = next(
            (
                profile["id"]
                for profile in VOICE_PROFILE_CHOICES
                if profile["hermes_profile"] == current_profile
            ),
            _default_voice_profile()["id"],
        )
        return web.json_response(
            {
                "version_label": APP_VERSION_LABEL,
                "runtime_ready": state["status"]["runtime_ready"],
                "audio": state["saved"]["audio"],
                "agent": agent,
                "voice_profiles": {
                    "active": active_profile,
                    "choices": [_public_voice_profile(profile) for profile in VOICE_PROFILE_CHOICES],
                },
                "tmux": public_tmux_targets(state["saved"]),
                "avatar": {
                    "default_preset": _default_avatar_preset(state["saved"]),
                },
                "windows_client": state["saved"]["windows_client"],
                "voice_client": await runtime.playback_status(),
                "voice_reachable": await runtime.voice_reachable_status(),
            }
        )

    async def runtime_voice_reachable(request: web.Request) -> web.Response:
        if request.method == "GET":
            return web.json_response({"ok": True, "voice_reachable": await runtime.voice_reachable_status()})
        payload = await parse_json(request)
        action = str(payload.get("action") or "").strip().lower()
        if "enabled" in payload:
            enabled = bool(payload.get("enabled"))
        elif action in {"on", "enable", "enabled", "true"}:
            enabled = True
        elif action in {"off", "disable", "disabled", "false"}:
            enabled = False
        elif action == "toggle":
            enabled = not await runtime.voice_reachable_enabled()
        elif action in {"", "status"}:
            return web.json_response({"ok": True, "voice_reachable": await runtime.voice_reachable_status()})
        else:
            raise ValidationError("Use action on, off, toggle, or status.")
        return web.json_response({"ok": True, "voice_reachable": await runtime.set_voice_reachable(enabled)})

    async def runtime_profile(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        selected = _normalize_voice_profile(str(payload.get("profile") or ""))
        store.update_config(
            {
                "agent": {
                    "backend": "hermes",
                    "hermes_profile": selected["hermes_profile"],
                    "hermes_api_url": selected["hermes_api_url"],
                }
            }
        )
        self_key = LOCAL_HERMES_API_KEY
        store.update_secrets({"MARAS_SWITCHBOARD_HERMES_API_KEY": self_key})
        return web.json_response({"ok": True, "profile": selected})

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

    async def validate_chatterbox_turbo(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = await setup_service.validate_chatterbox_turbo(payload)
        return web.json_response(result)

    async def validate_xai_tts(request: web.Request) -> web.Response:
        payload = await parse_json(request)
        result = await setup_service.validate_xai_tts(payload)
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
    app.on_startup.append(_run_mara_memory_sentinel_on_startup)
    add_route("GET", "/", root)
    add_route("GET", "/setup", setup_page)
    add_route("GET", "/setup/", setup_page_slash)
    add_route("GET", "/voice", voice_page)
    add_route("GET", "/voice/", voice_page_slash)
    add_route("GET", "/speech-to-agent", speech_to_agent_page)
    add_route("GET", "/speech-to-agent/", speech_to_agent_page_slash)
    add_route("GET", "/health", health)
    add_route("GET", "/api/setup/state", setup_state)
    add_route("GET", "/api/runtime/state", runtime_state)
    add_route("GET", "/api/runtime/voice-reachable", runtime_voice_reachable)
    add_route("POST", "/api/runtime/voice-reachable", runtime_voice_reachable)
    add_route("POST", "/api/runtime/profile", runtime_profile)
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
    add_route("POST", "/api/setup/validate-chatterbox-turbo", validate_chatterbox_turbo)
    add_route("POST", "/api/setup/validate-xai-tts", validate_xai_tts)
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
