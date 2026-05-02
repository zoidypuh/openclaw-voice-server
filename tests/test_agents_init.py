from maras_switchboard.agents import build_conversation_agent


def test_build_conversation_agent_lets_hermes_use_its_configured_model():
    captured = {}

    class FakeHermesAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    settings = {
        "agent": {
            "backend": "hermes",
            "hermes_root": "/tmp/hermes-agent",
            "hermes_profile": "voice",
            "use_context_files": False,
            "use_memory": True,
            "toolsets": ["browser", "file"],
            "reply_sanity_check": False,
            "hermes_api_url": "http://127.0.0.1:8642/v1/chat/completions",
            "hermes_api_model": "hermes-agent",
        },
        "gateway": {
            "url": "http://127.0.0.1:8317/v1",
            "model": "gpt-5.4",
            "session_key": "voice-main",
        },
        "secrets": {
            "gateway_token": "unit-test-gateway-token",
            "hermes_api_key": "local-hermes-key",
        },
    }

    build_conversation_agent(settings, hermes_agent_cls=FakeHermesAgent)

    assert captured == {
        "project_root": "/tmp/hermes-agent",
        "profile": "voice",
        "use_context_files": False,
        "use_memory": True,
        "enabled_toolsets": ["browser", "file"],
        "reply_sanity_check": False,
        "api_url": "http://127.0.0.1:8642/v1/chat/completions",
        "api_key": "local-hermes-key",
        "api_model": "hermes-agent",
    }


def test_build_conversation_agent_restores_hermes_context_without_tools_by_default():
    captured = {}

    class FakeHermesAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    settings = {
        "agent": {
            "backend": "hermes",
            "hermes_root": "/tmp/hermes-agent",
        },
        "gateway": {
            "url": "http://127.0.0.1:8317/v1",
            "model": "gpt-5.4",
            "session_key": "voice-main",
        },
        "secrets": {
            "gateway_token": "unit-test-gateway-token",
        },
    }

    build_conversation_agent(settings, hermes_agent_cls=FakeHermesAgent)

    assert captured["use_context_files"] is True
    assert captured["use_memory"] is True
    assert captured["profile"] == "voice"
    assert captured["enabled_toolsets"] == []
