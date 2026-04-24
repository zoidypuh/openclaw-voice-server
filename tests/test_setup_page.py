from agentic_switchboard.app import _static_dir


def test_setup_html_has_stt_target_switch_presets():
    setup_html = (_static_dir() / "setup.html").read_text(encoding="utf-8")

    assert 'id="stt-target-remote"' in setup_html
    assert 'id="stt-target-local-gpu"' in setup_html
    assert 'id="stt-target-note"' in setup_html
    assert "const REMOTE_STT_MEMORY_KEY = 'agentic-switchboard.voice.remote-stt.v1';" in setup_html
    assert "function resolveSttTarget() {" in setup_html
    assert "function renderSttTargetControls() {" in setup_html
    assert "function applySttTarget(target) {" in setup_html
    assert "function defaultRemoteWhisperEndpointUrl() {" in setup_html
    assert "function defaultRemoteWhisperEndpointModel() {" in setup_html
    assert "rememberRemoteStt(" in setup_html
    assert "default_remote_whisper_endpoint_url" in setup_html
    assert "default_remote_whisper_endpoint_model" in setup_html
    assert "applySttTarget('remote');" in setup_html
    assert "applySttTarget('local-gpu');" in setup_html


def test_setup_html_does_not_expose_legacy_tts_provider_controls():
    setup_html = (_static_dir() / "setup.html").read_text(encoding="utf-8")

    for legacy_provider in ("piper", "chatterbox", "pockettts", "vibevoice", "neutts"):
        assert legacy_provider not in setup_html.lower()


def test_setup_html_supports_core_tts_provider_state_tracking():
    setup_html = (_static_dir() / "setup.html").read_text(encoding="utf-8")

    assert "provider === 'disabled'" in setup_html
    assert "provider === 'supertonic'" in setup_html
    assert 'id="supertonic-section"' in setup_html
    assert 'id="supertonic-python-path"' in setup_html
    assert 'id="validate-supertonic"' in setup_html
    assert "api/setup/validate-supertonic" in setup_html
    assert "return 'gateway-section';" in setup_html


def test_setup_html_has_conversation_agent_selector_and_hermes_controls():
    setup_html = (_static_dir() / "setup.html").read_text(encoding="utf-8")

    assert 'id="agent-backend"' in setup_html
    assert 'id="gateway-backend-fields"' in setup_html
    assert 'id="hermes-backend-fields"' in setup_html
    assert 'id="agent-hermes-root"' in setup_html
    assert "function currentAgentBackend() {" in setup_html
    assert "function renderConversationBackendControls() {" in setup_html
    assert "api/setup/validate-agent" in setup_html
    assert "Validated Hermes reply" in setup_html


def test_setup_html_uses_root_app_base_so_trailing_slash_urls_do_not_404():
    setup_html = (_static_dir() / "setup.html").read_text(encoding="utf-8")

    assert "function resolveAppBase()" in setup_html
    assert "return new URL('/', window.location.href);" in setup_html
