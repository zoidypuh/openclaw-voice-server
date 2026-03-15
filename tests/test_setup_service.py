import asyncio

from openclaw_voice_server.config_store import ConfigStore
from openclaw_voice_server.setup_service import SetupService


def test_validate_stt_persists_validated_selection(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    monkeypatch.setattr(
        "openclaw_voice_server.setup_service.validate_stt_selection_step",
        lambda settings: {"ok": True, "results": [{"backend": "faster-whisper", "model": "large-v3"}]},
    )

    result = service.validate_stt(
        {
            "enabled_backends": ["faster-whisper", "whisper"],
            "default_backend": "whisper",
            "language": "en",
            "device": "cpu",
            "compute_type": "int8",
            "backend_models": {"faster-whisper": "large-v3", "whisper": "medium"},
        }
    )
    saved = store.load_config()

    assert result["ok"] is True
    assert saved["stt"]["default_backend"] == "whisper"
    assert saved["stt"]["backend_models"]["whisper"] == "medium"
    assert saved["validation"]["stt"]["config_hash"]


def test_validate_elevenlabs_key_and_voice_save_to_split_storage(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    async def fake_validate_key(api_key):
        assert api_key == "sk-test"
        return {"ok": True, "voice_count": 3}

    async def fake_list_voices(api_key):
        assert api_key == "sk-test"
        return [{"voice_id": "voice-123", "name": "Resolved Voice"}]

    async def fake_validate_voice(*, api_key, voice_id, model_id):
        assert api_key == "sk-test"
        assert voice_id == "voice-123"
        assert model_id == "eleven-model"
        return {"ok": True, "voice_id": voice_id, "voice_name": "Resolved Voice"}

    monkeypatch.setattr("openclaw_voice_server.setup_service.validate_elevenlabs_api_key_step", fake_validate_key)
    monkeypatch.setattr("openclaw_voice_server.setup_service.list_elevenlabs_voices", fake_list_voices)
    monkeypatch.setattr("openclaw_voice_server.setup_service.validate_elevenlabs_voice_step", fake_validate_voice)

    key_result = asyncio.run(service.validate_elevenlabs_key({"api_key": "sk-test"}))
    asyncio.run(service.validate_elevenlabs_voice({"voice_id": "voice-123", "model_id": "eleven-model"}))

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    saved = store.load_config()

    assert key_result["voices"] == [{"voice_id": "voice-123", "name": "Resolved Voice"}]
    assert "OPENCLAW_VOICE_ELEVENLABS_API_KEY=sk-test" in env_text
    assert saved["tts"]["elevenlabs_voice_id"] == "voice-123"
    assert saved["tts"]["elevenlabs_voice_name"] == "Resolved Voice"
    assert saved["tts"]["elevenlabs_model"] == "eleven-model"
    assert saved["validation"]["eleven_key"]["api_key_fingerprint"]
    assert saved["validation"]["eleven_voice"]["config_hash"]


def test_elevenlabs_voices_uses_saved_secret(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_secrets({"OPENCLAW_VOICE_ELEVENLABS_API_KEY": "sk-saved"})

    async def fake_list_voices(api_key):
        assert api_key == "sk-saved"
        return [{"voice_id": "voice-abc", "name": "Saved Voice"}]

    monkeypatch.setattr("openclaw_voice_server.setup_service.list_elevenlabs_voices", fake_list_voices)

    result = asyncio.run(service.elevenlabs_voices())

    assert result == {"ok": True, "voices": [{"voice_id": "voice-abc", "name": "Saved Voice"}]}


def test_validate_gateway_saves_secret_and_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    async def fake_validate_gateway_connection(*, url, token, model, session_key):
        assert url == "https://gateway.test.ts.net/v1/chat/completions"
        assert token == "gw-secret"
        assert model == "openclaw:test"
        assert session_key == "voice-main"
        return {"ok": True, "reply_preview": "OK"}

    monkeypatch.setattr(
        "openclaw_voice_server.setup_service.validate_gateway_connection",
        fake_validate_gateway_connection,
    )

    result = asyncio.run(
        service.validate_gateway(
            {
                "url": "gateway.test.ts.net",
                "token": "gw-secret",
                "model": "openclaw:test",
                "session_key": "voice-main",
            }
        )
    )
    saved = store.load_config()
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")

    assert result["reply_preview"] == "OK"
    assert saved["gateway"]["url"] == "https://gateway.test.ts.net/v1/chat/completions"
    assert saved["gateway"]["session_key"] == "voice-main"
    assert "OPENCLAW_VOICE_GATEWAY_TOKEN=gw-secret" in env_text
    assert saved["validation"]["gateway"]["config_hash"]


def test_setup_state_requires_explicit_validation(tmp_path):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    state = service.state()

    assert state["status"]["stt_ready"] is False
    assert state["status"]["tts_selection_ready"] is False
    assert state["status"]["gateway_ready"] is False
    assert state["status"]["runtime_ready"] is False
