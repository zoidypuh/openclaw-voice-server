import asyncio

from aiohttp.test_utils import TestClient, TestServer

from maras_switchboard.app import create_app


async def _request(path: str, *, method: str = "GET", json_payload: dict | None = None):
    client = TestClient(TestServer(create_app()))
    await client.start_server()
    try:
        response = await client.request(method, path, json=json_payload, allow_redirects=False)
        body = await response.text()
        return response.status, dict(response.headers), body
    finally:
        await client.close()


async def _fetch(path: str):
    return await _request(path)


def test_setup_trailing_slash_redirects_to_canonical_route():
    status, headers, _ = asyncio.run(_fetch("/setup/"))

    assert status == 308
    assert headers.get("Location") == "/setup"


def test_voice_trailing_slash_redirects_to_canonical_route():
    status, headers, _ = asyncio.run(_fetch("/voice/"))

    assert status == 308
    assert headers.get("Location") == "/voice"


def test_voice_page_disables_html_caching_to_avoid_stale_frontend_404s():
    status, headers, _ = asyncio.run(_fetch("/voice"))

    assert status == 200
    assert headers.get("Cache-Control") == "no-store, no-cache, must-revalidate, max-age=0"
    assert headers.get("Pragma") == "no-cache"
    assert headers.get("Expires") == "0"


def test_ascii_art_backdrop_media_is_served():
    status, _, body = asyncio.run(_fetch("/media/ascii-art.txt"))

    assert status == 200
    assert "\u2588" in body


def test_legacy_voice_prefixed_runtime_state_route_still_works_for_stale_tabs():
    status, _, body = asyncio.run(_fetch("/voice/api/runtime/state"))

    assert status == 200
    assert '"runtime_ready"' in body


def test_legacy_setup_prefixed_setup_state_route_still_works_for_stale_tabs():
    status, _, body = asyncio.run(_fetch("/setup/api/setup/state"))

    assert status == 200
    assert '"status"' in body


def test_runtime_profile_route_maps_lola_to_single_live_hermes_gateway(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    monkeypatch.setenv("MARAS_SWITCHBOARD_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("MARAS_SWITCHBOARD_ENV_FILE", str(env_path))

    status, _, body = asyncio.run(
        _request(
            "/api/runtime/profile",
            method="POST",
            json_payload={"profile": "lola"},
        )
    )
    state_status, _, state_body = asyncio.run(_fetch("/api/runtime/state"))

    assert status == 200
    written = config_path.read_text(encoding="utf-8")
    env_text = env_path.read_text(encoding="utf-8")
    assert '"hermes_profile": "lola"' in written
    assert '"hermes_api_url": "http://127.0.0.1:8642/v1"' in written
    assert '"hermes_api_model": "hermes-agent"' in written
    assert "MARAS_SWITCHBOARD_HERMES_API_KEY=local-hermes-key" in env_text
    assert '"id": "lola"' in body
    assert state_status == 200
    assert '"active": "lola"' in state_body


def test_runtime_profile_route_maps_mara_to_single_live_hermes_gateway(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    monkeypatch.setenv("MARAS_SWITCHBOARD_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("MARAS_SWITCHBOARD_ENV_FILE", str(env_path))

    status, _, body = asyncio.run(
        _request(
            "/api/runtime/profile",
            method="POST",
            json_payload={"profile": "mara"},
        )
    )
    written = config_path.read_text(encoding="utf-8")

    assert status == 200
    assert '"hermes_profile": "voice-mara"' in written
    assert '"hermes_api_url": "http://127.0.0.1:8642/v1"' in written
    assert '"hermes_api_model": "hermes-agent"' in written
    assert '"id": "mara"' in body


def test_runtime_profile_route_maps_default_to_lola(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    monkeypatch.setenv("MARAS_SWITCHBOARD_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("MARAS_SWITCHBOARD_ENV_FILE", str(env_path))

    status, _, body = asyncio.run(
        _request(
            "/api/runtime/profile",
            method="POST",
            json_payload={"profile": "default"},
        )
    )
    written = config_path.read_text(encoding="utf-8")

    assert status == 200
    assert '"hermes_profile": "lola"' in written
    assert '"hermes_api_url": "http://127.0.0.1:8642/v1"' in written
    assert '"hermes_api_model": "hermes-agent"' in written
    assert '"id": "lola"' in body
