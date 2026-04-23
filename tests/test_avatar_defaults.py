from agent_switchboard.app import _default_avatar_preset


def test_default_avatar_preset_prefers_girl_for_hermes_backend():
    assert _default_avatar_preset(
        {
            "agent": {"backend": "hermes"},
            "gateway": {"model": "openclaw:main"},
        }
    ) == "girl"


def test_default_avatar_preset_prefers_lobster_for_claw_gateway_models():
    assert _default_avatar_preset(
        {
            "agent": {"backend": "gateway"},
            "gateway": {"model": "openclaw:main"},
        }
    ) == "lobster"


def test_default_avatar_preset_falls_back_to_girl_for_general_models():
    assert _default_avatar_preset(
        {
            "agent": {"backend": "gateway"},
            "gateway": {"model": "gpt-5.4"},
        }
    ) == "girl"

