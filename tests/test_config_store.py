import json

from openclaw_voice_server.config_store import ConfigStore


def test_config_store_splits_config_and_secrets(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP_ME=1\n", encoding="utf-8")

    store = ConfigStore(config_path=config_path, env_path=env_path)
    store.update_config(
        {
            "gateway": {"url": "http://example.test/v1/chat/completions", "model": "openclaw:test"},
            "tts": {"elevenlabs_voice_id": "voice-123", "elevenlabs_voice_name": "Test Voice"},
        }
    )
    store.update_secrets(
        {
            "OPENCLAW_VOICE_GATEWAY_TOKEN": "gw-secret",
            "OPENCLAW_VOICE_ELEVENLABS_API_KEY": "sk-secret",
        }
    )

    written_config = json.loads(config_path.read_text(encoding="utf-8"))
    written_env = env_path.read_text(encoding="utf-8")

    assert written_config["gateway"]["url"] == "http://example.test/v1/chat/completions"
    assert written_config["tts"]["elevenlabs_voice_id"] == "voice-123"
    assert "gw-secret" not in written_config
    assert "sk-secret" not in written_config
    assert "KEEP_ME=1" in written_env
    assert "OPENCLAW_VOICE_GATEWAY_TOKEN=gw-secret" in written_env
    assert "OPENCLAW_VOICE_ELEVENLABS_API_KEY=sk-secret" in written_env


def test_config_store_reads_legacy_voice_id_from_env(tmp_path):
    config_path = tmp_path / "config.json"
    env_path = tmp_path / ".env"
    env_path.write_text("OPENCLAW_VOICE_ELEVENLABS_VOICE_ID=voice-from-env\n", encoding="utf-8")

    store = ConfigStore(config_path=config_path, env_path=env_path)
    settings = store.load_runtime_settings()

    assert settings["tts"]["elevenlabs_voice_id"] == "voice-from-env"


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
