from maras_switchboard.agents import build_conversation_agent


def test_build_conversation_agent_passes_gateway_settings_to_hermes_backend():
    captured = {}
    gateway_token = "unit-test-gateway-token"

    class FakeHermesAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    settings = {
        "agent": {
            "backend": "hermes",
            "hermes_root": "/tmp/hermes-agent",
            "use_context_files": False,
            "use_memory": True,
            "toolsets": ["browser", "file"],
        },
        "gateway": {
            "url": "http://127.0.0.1:8317/v1",
            "model": "gpt-5.4",
            "session_key": "voice-main",
        },
        "secrets": {
            "gateway_token": gateway_token,
        },
    }

    build_conversation_agent(settings, hermes_agent_cls=FakeHermesAgent)

    assert captured == {
        "project_root": "/tmp/hermes-agent",
        "gateway_url": "http://127.0.0.1:8317/v1",
        "gateway_token": gateway_token,
        "gateway_model": "gpt-5.4",
        "use_context_files": False,
        "use_memory": True,
        "enabled_toolsets": ["browser", "file"],
    }
