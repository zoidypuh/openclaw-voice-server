import asyncio

import httpx
import pytest

from agent_switchboard.gateway import (
    DirectGatewayClient,
    _friendly_connection_error,
    normalize_gateway_url,
    resolve_voice_session_key,
)
from agent_switchboard.errors import ValidationError


def test_resolve_voice_session_key_keeps_configured_value():
    assert resolve_voice_session_key("voice-speaker-a") == "voice-speaker-a"


def test_resolve_voice_session_key_defaults_to_stable_voice_chat_key_when_blank():
    session_key = resolve_voice_session_key("   ")

    assert session_key == "agent:main:voice-chat-main"


def test_normalize_gateway_url_appends_chat_completions_for_plain_host():
    assert normalize_gateway_url("https://machine.example.ts.net") == "https://machine.example.ts.net/v1/chat/completions"


def test_normalize_gateway_url_defaults_to_https_for_bare_host():
    assert normalize_gateway_url("machine.example.ts.net") == "https://machine.example.ts.net/v1/chat/completions"


def test_normalize_gateway_url_rewrites_non_api_path_to_chat_completions():
    assert normalize_gateway_url("http://gateway.test/custom/path") == "http://gateway.test/v1/chat/completions"


def test_normalize_gateway_url_rewrites_sessions_page_to_chat_completions():
    assert (
        normalize_gateway_url("https://machine.example.ts.net/sessions")
        == "https://machine.example.ts.net/v1/chat/completions"
    )


def test_friendly_connection_error_guides_ts_net_users_to_local_gateway():
    exc = httpx.ConnectError("[Errno -2] Name or service not known")

    message = _friendly_connection_error("https://machine.example.ts.net/v1/chat/completions", exc)

    assert "Use the local gateway URL http://127.0.0.1:18789" in message


def test_validate_gateway_connection_includes_session_key_header(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("agent_switchboard.gateway.httpx.AsyncClient", lambda timeout: FakeClient())

    from agent_switchboard.gateway import validate_gateway_connection

    result = asyncio.run(
        validate_gateway_connection(
            url="http://127.0.0.1:18789",
            token="speaker-a",
            model="openclaw:main",
            session_key="agent:main:voice-chat-main",
        )
    )

    assert result["reply_preview"] == "OK"
    assert captured["url"] == "http://127.0.0.1:18789/v1/chat/completions"
    assert captured["headers"]["X-OpenClaw-Scopes"] == "operator.write"
    assert captured["headers"]["X-OpenClaw-Session-Key"] == "agent:main:voice-chat-main"


def test_stream_reply_reads_stream_error_body_before_parsing(monkeypatch):
    class FakeResponse:
        status_code = 403
        headers = {"content-type": "application/json"}

        def __init__(self):
            self._read = False

        async def aread(self):
            self._read = True
            return b'{"error":{"message":"Forbidden"}}'

        def json(self):
            if not self._read:
                raise httpx.ResponseNotRead()
            return {"error": {"message": "Forbidden"}}

        @property
        def text(self):
            if not self._read:
                raise httpx.ResponseNotRead()
            return '{"error":{"message":"Forbidden"}}'

    class FakeStreamContext:
        def __init__(self, response):
            self._response = response

        async def __aenter__(self):
            return self._response

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, headers, json):
            return FakeStreamContext(FakeResponse())

    monkeypatch.setattr("agent_switchboard.gateway.httpx.AsyncClient", lambda timeout: FakeClient())

    gateway = DirectGatewayClient(url="http://127.0.0.1:18789", token="speaker-a", model="openclaw:main")

    async def run_stream():
        abort_event = asyncio.Event()
        async for _chunk in gateway.stream_reply("hello", abort_event):
            pass

    with pytest.raises(ValidationError, match="Forbidden"):
        asyncio.run(run_stream())
