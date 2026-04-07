from openclaw_voice_server.app import _static_dir


def test_setup_html_has_stt_target_switch_presets():
    setup_html = (_static_dir() / "setup.html").read_text(encoding="utf-8")

    assert 'id="stt-target-remote"' in setup_html
    assert 'id="stt-target-local-gpu"' in setup_html
    assert 'id="stt-target-note"' in setup_html
    assert "const REMOTE_STT_MEMORY_KEY = 'openclaw.voice.remote-stt.v1';" in setup_html
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


def test_setup_html_has_piper_provider_controls():
    setup_html = (_static_dir() / "setup.html").read_text(encoding="utf-8")

    assert 'id="piper-section"' in setup_html
    assert 'id="piper-local-voice"' in setup_html
    assert 'id="piper-model-path"' in setup_html
    assert 'id="piper-config-path"' in setup_html
    assert 'id="piper-speaker"' in setup_html
    assert 'id="piper-github-link"' in setup_html
    assert 'id="piper-voices-link"' in setup_html
    assert 'id="validate-piper"' in setup_html
    assert 'id="continue-piper"' in setup_html
    assert "provider === 'piper'" in setup_html
    assert "status.piper_ready" in setup_html
    assert "piper_note" in setup_html
    assert "renderPiperVoiceOptions(" in setup_html
    assert "syncPiperSelectionFromInput()" in setup_html
    assert "api/setup/validate-piper" in setup_html


def test_setup_html_has_conversation_agent_selector_and_hermes_controls():
    setup_html = (_static_dir() / "setup.html").read_text(encoding="utf-8")

    assert 'id="agent-backend"' in setup_html
    assert 'id="openclaw-backend-fields"' in setup_html
    assert 'id="hermes-backend-fields"' in setup_html
    assert 'id="agent-hermes-root"' in setup_html
    assert "function currentAgentBackend() {" in setup_html
    assert "function renderConversationBackendControls() {" in setup_html
    assert "api/setup/validate-agent" in setup_html
    assert "Validated Hermes reply" in setup_html
