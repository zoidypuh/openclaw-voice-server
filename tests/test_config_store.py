import json

from maras_switchboard.config_store import ConfigStore


def test_config_store_splits_config_and_secrets(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP_ME=1\n", encoding="utf-8")

    store = ConfigStore(config_path=config_path, env_path=env_path)
    store.update_config(
        {
            "gateway": {"url": "http://example.test/v1/chat/completions", "model": "maras-switchboard:test"},
            "tts": {"elevenlabs_voice_id": "voice-123", "elevenlabs_voice_name": "Test Voice"},
        }
    )
    store.update_secrets(
        {
            "MARAS_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret",
            "MARAS_SWITCHBOARD_ELEVENLABS_API_KEY": "sk-secret",
        }
    )

    written_config = json.loads(config_path.read_text(encoding="utf-8"))
    written_env = env_path.read_text(encoding="utf-8")

    assert written_config["gateway"]["url"] == "http://example.test/v1/chat/completions"
    assert written_config["tts"]["elevenlabs_voice_id"] == "voice-123"
    assert "gw-secret" not in written_config
    assert "sk-secret" not in written_config
    assert "KEEP_ME=1" in written_env
    assert "MARAS_SWITCHBOARD_GATEWAY_TOKEN=gw-secret" in written_env
    assert "MARAS_SWITCHBOARD_ELEVENLABS_API_KEY=sk-secret" in written_env


def test_config_store_reads_voice_id_from_env(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    env_path.write_text("MARAS_SWITCHBOARD_ELEVENLABS_VOICE_ID=voice-from-env\n", encoding="utf-8")

    store = ConfigStore(config_path=config_path, env_path=env_path)
    settings = store.load_runtime_settings()

    assert settings["tts"]["elevenlabs_voice_id"] == "voice-from-env"


def test_config_store_reads_chatterbox_turbo_paths_from_env(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "MARAS_SWITCHBOARD_CHATTERBOX_TURBO_PYTHON_PATH=/envs/chatterbox/bin/python",
                "MARAS_SWITCHBOARD_CHATTERBOX_TURBO_VOICE_PROMPT_PATH=/voices/mara.wav",
                "MARAS_SWITCHBOARD_CHATTERBOX_TURBO_DEVICE=cpu",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store = ConfigStore(config_path=config_path, env_path=env_path)
    settings = store.load_runtime_settings()

    assert settings["tts"]["chatterbox_python_path"] == "/envs/chatterbox/bin/python"
    assert settings["tts"]["chatterbox_voice_prompt_path"] == "/voices/mara.wav"
    assert settings["tts"]["chatterbox_device"] == "cpu"


def test_config_store_reads_whisper_endpoint_from_env(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MARAS_SWITCHBOARD_WHISPER_ENDPOINT_URL=http://127.0.0.1:18000/v1/audio/transcriptions\n",
        encoding="utf-8",
    )

    store = ConfigStore(config_path=config_path, env_path=env_path)
    settings = store.load_runtime_settings()

    assert settings["stt"]["whisper_endpoint_url"] == "http://127.0.0.1:18000/v1/audio/transcriptions"


def test_config_store_reads_xai_api_key_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("MARAS_SWITCHBOARD_XAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENTIC_SWITCHBOARD_XAI_API_KEY", raising=False)
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    env_path.write_text("XAI_API_KEY=xai-test\n", encoding="utf-8")

    store = ConfigStore(config_path=config_path, env_path=env_path)
    settings = store.load_runtime_settings()
    public = store.public_setup_state()

    assert settings["secrets"]["xai_api_key"] == "xai-test"
    assert public["stt"]["xai_api_key_present"] is True


def test_config_store_reads_hermes_root_from_env(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MARAS_SWITCHBOARD_HERMES_ROOT=/tmp/hermes-agent\n"
        "MARAS_SWITCHBOARD_HERMES_PROFILE=voice\n"
        "MARAS_SWITCHBOARD_HERMES_SESSION_ID=current-mara-session\n"
        "MARAS_SWITCHBOARD_HERMES_API_MODEL=cheap-voice-model\n"
        "MARAS_SWITCHBOARD_HERMES_DELEGATE_API_MODEL=full-mara-model\n"
        "MARAS_SWITCHBOARD_HERMES_DELEGATE_TOOLSETS=terminal,file,web\n",
        encoding="utf-8",
    )

    store = ConfigStore(config_path=config_path, env_path=env_path)
    settings = store.load_runtime_settings()

    assert settings["agent"]["hermes_root"] == "/tmp/hermes-agent"
    assert settings["agent"]["hermes_profile"] == "voice"
    assert settings["agent"]["hermes_session_id"] == "current-mara-session"
    assert settings["agent"]["hermes_api_model"] == "cheap-voice-model"
    assert settings["agent"]["delegate_api_model"] == "full-mara-model"
    assert settings["agent"]["delegate_toolsets"] == ["terminal", "file", "web"]


def test_config_store_accepts_agentic_env_aliases(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "AGENTIC_SWITCHBOARD_GATEWAY_TOKEN=legacy-gw\n"
        "AGENTIC_SWITCHBOARD_ELEVENLABS_API_KEY=legacy-sk\n"
        "AGENTIC_SWITCHBOARD_WHISPER_ENDPOINT_URL=http://127.0.0.1:18000/v1/audio/transcriptions\n",
        encoding="utf-8",
    )

    store = ConfigStore(config_path=config_path, env_path=env_path)
    settings = store.load_runtime_settings()

    assert settings["secrets"]["gateway_token"] == "legacy-gw"
    assert settings["secrets"]["elevenlabs_api_key"] == "legacy-sk"
    assert settings["stt"]["whisper_endpoint_url"] == "http://127.0.0.1:18000/v1/audio/transcriptions"


def test_config_store_accepts_old_agent_switchboard_secret_aliases(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "AGENT_SWITCHBOARD_GATEWAY_TOKEN=old-gw\n"
        "OPENCLAW_VOICE_ELEVENLABS_API_KEY=old-sk\n",
        encoding="utf-8",
    )

    store = ConfigStore(config_path=config_path, env_path=env_path)
    settings = store.load_runtime_settings()

    assert settings["secrets"]["gateway_token"] == "old-gw"
    assert settings["secrets"]["elevenlabs_api_key"] == "old-sk"


def test_config_store_prefers_explicit_config_over_env(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    config_path.write_text(
        json.dumps({"agent": {"hermes_root": "/srv/hermes-agent"}}),
        encoding="utf-8",
    )
    env_path.write_text("MARAS_SWITCHBOARD_HERMES_ROOT=/tmp/hermes-agent\n", encoding="utf-8")

    store = ConfigStore(config_path=config_path, env_path=env_path)
    settings = store.load_runtime_settings()

    assert settings["agent"]["hermes_root"] == "/srv/hermes-agent"


def test_update_config_replaces_validation_section_payloads(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    config_path.write_text(
        json.dumps(
            {
                "validation": {
                    "gateway": {
                        "snapshot": {"url": "http://old.test"},
                        "token_fingerprint": "old",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    store = ConfigStore(config_path=config_path, env_path=env_path)
    store.update_config({"validation": {"gateway": {"config_hash": "new-hash", "token_fingerprint": "new"}}})

    written_config = json.loads(config_path.read_text(encoding="utf-8"))

    assert written_config["validation"]["gateway"] == {
        "config_hash": "new-hash",
        "token_fingerprint": "new",
    }
