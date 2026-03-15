import httpx

from openclaw_voice_server.gateway import (
    _friendly_connection_error,
    normalize_gateway_url,
    resolve_voice_session_key,
)


def test_resolve_voice_session_key_keeps_configured_value():
    assert resolve_voice_session_key("voice-bonnie") == "voice-bonnie"


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

    assert "Use the local OpenClaw gateway URL http://127.0.0.1:18789" in message


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

    monkeypatch.setattr("openclaw_voice_server.gateway.httpx.AsyncClient", lambda timeout: FakeClient())

    import asyncio
    from openclaw_voice_server.gateway import validate_gateway_connection

    result = asyncio.run(
        validate_gateway_connection(
            url="http://127.0.0.1:18789",
            token="bonnie",
            model="openclaw:main",
            session_key="agent:main:voice-chat-main",
        )
    )

    assert result["reply_preview"] == "OK"
    assert captured["url"] == "http://127.0.0.1:18789/v1/chat/completions"
    assert captured["headers"]["X-OpenClaw-Session-Key"] == "agent:main:voice-chat-main"
