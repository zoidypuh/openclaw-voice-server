import asyncio

from aiohttp.test_utils import TestClient, TestServer

from maras_switchboard.app import create_app


async def _fetch(path: str):
    client = TestClient(TestServer(create_app()))
    await client.start_server()
    try:
        response = await client.get(path, allow_redirects=False)
        body = await response.text()
        return response.status, dict(response.headers), body
    finally:
        await client.close()


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
