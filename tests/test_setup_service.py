import asyncio

import pytest

from agent_switchboard.config_store import ConfigStore
from agent_switchboard.errors import ValidationError
from agent_switchboard.setup_service import SetupService


def test_validate_stt_persists_validated_selection(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    monkeypatch.setattr(
        "agent_switchboard.setup_service.validate_stt_selection_step",
        lambda settings: {"ok": True, "results": [{"backend": "faster-whisper", "model": "large-v3"}]},
    )

    result = service.validate_stt(
        {
            "enabled_backends": ["faster-whisper", "whisper"],
            "default_backend": "whisper",
            "language": "en",
            "device": "cpu",
            "compute_type": "int8",
            "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            "whisper_endpoint_model": "",
            "backend_models": {"faster-whisper": "large-v3", "whisper": "medium"},
        }
    )
    saved = store.load_config()

    assert result["ok"] is True
    assert saved["stt"]["default_backend"] == "whisper"
    assert saved["stt"]["backend_models"]["whisper"] == "medium"
    assert saved["stt"]["whisper_endpoint_url"] == "http://127.0.0.1:18000/v1/audio/transcriptions"
    assert saved["stt"]["whisper_endpoint_model"] == ""
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

    async def fake_validate_voice(*, api_key, voice_id, model_id, preset_name):
        assert api_key == "sk-test"
        assert voice_id == "voice-123"
        assert model_id == "eleven-model"
        assert preset_name == "expressive"
        return {"ok": True, "voice_id": voice_id, "voice_name": "Resolved Voice"}

    monkeypatch.setattr("agent_switchboard.setup_service.validate_elevenlabs_api_key_step", fake_validate_key)
    monkeypatch.setattr("agent_switchboard.setup_service.list_elevenlabs_voices", fake_list_voices)
    monkeypatch.setattr("agent_switchboard.setup_service.validate_elevenlabs_voice_step", fake_validate_voice)

    key_result = asyncio.run(service.validate_elevenlabs_key({"api_key": "sk-test"}))
    asyncio.run(
        service.validate_elevenlabs_voice(
            {"voice_id": "voice-123", "model_id": "eleven-model", "preset_name": "expressive"}
        )
    )

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    saved = store.load_config()

    assert key_result["voices"] == [{"voice_id": "voice-123", "name": "Resolved Voice"}]
    assert "AGENT_SWITCHBOARD_ELEVENLABS_API_KEY=sk-test" in env_text
    assert saved["tts"]["elevenlabs_voice_id"] == "voice-123"
    assert saved["tts"]["elevenlabs_voice_name"] == "Resolved Voice"
    assert saved["tts"]["elevenlabs_model"] == "eleven-model"
    assert saved["tts"]["elevenlabs_preset"] == "expressive"
    assert saved["validation"]["eleven_key"]["api_key_fingerprint"]
    assert saved["validation"]["eleven_voice"]["config_hash"]


def test_elevenlabs_voices_uses_saved_secret(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_secrets({"AGENT_SWITCHBOARD_ELEVENLABS_API_KEY": "sk-saved"})

    async def fake_list_voices(api_key):
        assert api_key == "sk-saved"
        return [{"voice_id": "voice-abc", "name": "Saved Voice"}]

    monkeypatch.setattr("agent_switchboard.setup_service.list_elevenlabs_voices", fake_list_voices)

    result = asyncio.run(service.elevenlabs_voices())

    assert result == {"ok": True, "voices": [{"voice_id": "voice-abc", "name": "Saved Voice"}]}


def test_validate_piper_persists_resolved_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    resolved_model = str((tmp_path / "voice.onnx").resolve())
    resolved_config = str((tmp_path / "voice.onnx.json").resolve())

    async def fake_validate_piper(*, model_path, config_path, speaker):
        assert model_path == resolved_model
        assert config_path == ""
        assert speaker == 2
        return {
            "ok": True,
            "model_path": resolved_model,
            "config_path": resolved_config,
            "speaker": 2,
            "voice_name": "voice.onnx",
        }

    monkeypatch.setattr("agent_switchboard.setup_service.normalize_piper_model_path", lambda value: resolved_model)
    monkeypatch.setattr("agent_switchboard.setup_service.validate_piper_voice_step", fake_validate_piper)

    result = asyncio.run(
        service.validate_piper(
            {
                "model_path": "/tmp/voice.onnx",
                "config_path": "",
                "speaker": "2",
            }
        )
    )
    saved = store.load_config()

    assert result["ok"] is True
    assert saved["tts"]["piper_model_path"] == resolved_model
    assert saved["tts"]["piper_config_path"] == resolved_config
    assert saved["tts"]["piper_speaker"] == 2
    assert saved["validation"]["piper"]["config_hash"]


def test_validate_chatterbox_persists_resolved_settings(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config({"stt": {"language": "de"}})

    async def fake_validate_chatterbox(*, model, device, language, voice):
        assert model == "multilingual"
        assert device == "auto"
        assert language == "de"
        assert voice == "mara"
        return {
            "ok": True,
            "model": "multilingual",
            "device": "cpu",
            "language": "de",
            "voice": "mara",
            "voice_name": "Mara",
        }

    monkeypatch.setattr("agent_switchboard.setup_service.validate_chatterbox_voice_step", fake_validate_chatterbox)
    monkeypatch.setattr("agent_switchboard.setup_service.resolve_chatterbox_voice", lambda value: (value or "default").strip())

    result = asyncio.run(service.validate_chatterbox({"model": "multilingual", "device": "auto", "voice": "mara", "language": ""}))
    saved = store.load_config()

    assert result["ok"] is True
    assert saved["tts"]["chatterbox_model"] == "multilingual"
    assert saved["tts"]["chatterbox_device"] == "cpu"
    assert saved["tts"]["chatterbox_language"] == "de"
    assert saved["tts"]["chatterbox_voice"] == "mara"
    assert saved["validation"]["chatterbox"]["config_hash"]


def test_validate_pockettts_persists_resolved_voice(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config({"stt": {"language": "en"}})

    async def fake_validate_pockettts(*, voice):
        assert voice == "alba"
        return {
            "ok": True,
            "voice": "alba",
            "voice_name": "Alba",
            "variant": "b6369a24",
        }

    monkeypatch.setattr("agent_switchboard.setup_service.validate_pockettts_voice_step", fake_validate_pockettts)
    monkeypatch.setattr("agent_switchboard.setup_service.normalize_pockettts_voice", lambda value: (value or "alba").strip().lower())

    result = asyncio.run(service.validate_pockettts({"voice": "Alba"}))
    saved = store.load_config()

    assert result["ok"] is True
    assert saved["tts"]["pockettts_voice"] == "alba"
    assert saved["validation"]["pockettts"]["config_hash"]


def test_validate_pockettts_rejects_non_english_stt_language(tmp_path):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config({"stt": {"language": "de"}})

    with pytest.raises(ValidationError, match="Pocket TTS is English-only right now."):
        asyncio.run(service.validate_pockettts({"voice": "alba"}))


def test_validate_supertonic_persists_resolved_settings(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    python_path = tmp_path / "python"
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    python_path.chmod(0o755)

    async def fake_validate_supertonic(*, python_path, voice, language, total_steps, speed):
        return {
            "ok": True,
            "python_path": python_path,
            "voice": voice,
            "voice_name": "Male 4",
            "language": language,
            "language_name": "English",
            "total_steps": total_steps,
            "speed": speed,
        }

    monkeypatch.setattr("agent_switchboard.setup_service.validate_supertonic_voice_step", fake_validate_supertonic)

    result = asyncio.run(
        service.validate_supertonic(
            {
                "python_path": str(python_path),
                "voice": "M4",
                "language": "en",
                "total_steps": "2",
                "speed": "1.1",
            }
        )
    )

    saved = store.load_config()

    assert result["voice"] == "M4"
    assert saved["tts"]["supertonic_python_path"] == str(python_path.resolve())
    assert saved["tts"]["supertonic_voice"] == "M4"
    assert saved["tts"]["supertonic_language"] == "en"
    assert saved["tts"]["supertonic_total_steps"] == 2
    assert saved["tts"]["supertonic_speed"] == 1.1
    assert saved["validation"]["supertonic"]["config_hash"]


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
        "agent_switchboard.setup_service.validate_gateway_connection",
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
    assert saved["agent"]["backend"] == "gateway"
    assert saved["gateway"]["url"] == "https://gateway.test.ts.net/v1/chat/completions"
    assert saved["gateway"]["session_key"] == "voice-main"
    assert "AGENT_SWITCHBOARD_GATEWAY_TOKEN=gw-secret" in env_text
    assert saved["validation"]["gateway"]["config_hash"]


def test_validate_agent_saves_hermes_root_and_backend(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    resolved_root = str((tmp_path / "hermes-agent").resolve())

    async def fake_validate_hermes_connection(
        *,
        project_root,
        gateway_url=None,
        gateway_token=None,
        gateway_model=None,
    ):
        assert project_root == "/tmp/hermes-agent"
        assert gateway_url is None
        assert gateway_token is None
        assert gateway_model is None
        return {"ok": True, "project_root": resolved_root, "reply_preview": "OK"}

    monkeypatch.setattr(
        "agent_switchboard.setup_service.validate_hermes_connection",
        fake_validate_hermes_connection,
    )

    result = asyncio.run(
        service.validate_agent(
            {
                "backend": "hermes",
                "hermes_root": "/tmp/hermes-agent",
            }
        )
    )
    saved = store.load_config()

    assert result["backend"] == "hermes"
    assert saved["agent"]["backend"] == "hermes"
    assert saved["agent"]["hermes_root"] == resolved_root
    assert saved["validation"]["hermes"]["config_hash"]


def test_setup_state_requires_explicit_validation(tmp_path):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    state = service.state()

    assert state["status"]["stt_ready"] is False
    assert state["status"]["tts_selection_ready"] is False
    assert state["status"]["gateway_ready"] is False
    assert state["status"]["runtime_ready"] is False


def test_setup_state_allows_remote_whisper_without_local_module(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "language": "en",
                "device": "cpu",
                "compute_type": "int8",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
                "whisper_endpoint_model": "",
                "backend_models": {"faster-whisper": "large-v3", "whisper": "medium"},
            },
            "validation": {
                "stt": {
                    "config_hash": service._config_hash(
                        {
                            "enabled_backends": ["whisper"],
                            "default_backend": "whisper",
                            "language": "en",
                            "device": "cpu",
                            "compute_type": "int8",
                            "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
                            "whisper_endpoint_model": "",
                            "backend_models": {"faster-whisper": "large-v3", "whisper": "medium"},
                        }
                    )
                }
            },
        }
    )

    monkeypatch.setattr(
        "agent_switchboard.setup_service.module_available",
        lambda import_name: False,
    )

    state = service.state()

    assert state["status"]["stt_ready"] is True


def test_setup_state_includes_default_remote_whisper_hint(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    monkeypatch.setattr(
        service,
        "_resolve_ssh_hostname",
        lambda alias: "192.168.50.60",
    )

    state = service.state()

    assert state["hints"]["default_remote_whisper_endpoint_url"] == "http://192.168.50.60:18000/v1/audio/transcriptions"
    assert state["hints"]["default_remote_whisper_endpoint_model"] == ""
    assert state["hints"]["remote_whisper_host_alias"] == "remote-whisper"


def test_setup_state_ignores_unresolvable_default_remote_whisper_alias(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    monkeypatch.setattr(service, "_resolve_ssh_hostname", lambda alias: "remote-whisper")
    monkeypatch.setattr(service, "_host_is_resolvable", lambda host: False)

    state = service.state()

    assert state["hints"]["default_remote_whisper_endpoint_url"] == ""


def test_setup_state_detects_local_piper_voices(tmp_path):
    voices_dir = tmp_path / "piper-voices"
    voices_dir.mkdir()
    model_path = voices_dir / "de_DE-demo.onnx"
    config_path = voices_dir / "de_DE-demo.onnx.json"
    model_path.write_bytes(b"fake-model")
    config_path.write_text("{}", encoding="utf-8")

    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    state = service.state()

    assert state["hints"]["default_piper_model_path"] == str(model_path.resolve())
    assert state["hints"]["default_piper_config_path"] == str(config_path.resolve())
    assert {
        "voice_name": "de_DE-demo.onnx",
        "model_path": str(model_path.resolve()),
        "config_path": str(config_path.resolve()),
        "source_dir": str(voices_dir.resolve()),
    } in state["hints"]["local_piper_voices"]
    assert state["hints"]["local_piper_voices"][0] == {
        "voice_name": "de_DE-demo.onnx",
        "model_path": str(model_path.resolve()),
        "config_path": str(config_path.resolve()),
        "source_dir": str(voices_dir.resolve()),
    }
    assert "not the Piper install directory" in state["hints"]["piper_note"]
    assert str(voices_dir.resolve()) in state["hints"]["piper_note"]


def test_runtime_ready_uses_live_config_even_if_stt_validation_is_stale(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "language": "de",
                "device": "cpu",
                "compute_type": "int8",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
                "whisper_endpoint_model": "distil-large-v3",
                "backend_models": {"faster-whisper": "large-v3", "whisper": "large"},
            },
            "tts": {
                "enabled_providers": ["elevenlabs"],
                "default_provider": "elevenlabs",
                "elevenlabs_voice_id": "voice-123",
                "elevenlabs_model": "eleven_flash_v2_5",
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "openclaw:main",
                "session_key": "voice-main",
            },
            "validation": {
                "stt": {"config_hash": "stale-hash"},
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["elevenlabs"], "default_provider": "elevenlabs"}
                    )
                },
                "eleven_key": {"api_key_fingerprint": service._fingerprint_secret("sk-test")},
                "eleven_voice": {
                    "config_hash": service._config_hash(
                        {
                            "voice_id": "voice-123",
                            "model_id": "eleven_flash_v2_5",
                            "preset": "expressive",
                        }
                    ),
                    "api_key_fingerprint": service._fingerprint_secret("sk-test"),
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "openclaw:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets(
        {
            "AGENT_SWITCHBOARD_ELEVENLABS_API_KEY": "sk-test",
            "AGENT_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret",
        }
    )

    monkeypatch.setattr("agent_switchboard.setup_service.module_available", lambda import_name: False)

    state = service.state()

    assert state["status"]["stt_ready"] is False
    assert state["status"]["runtime_ready"] is True


def test_runtime_ready_requires_provider_specific_live_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "language": "en",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["edge"],
                "default_provider": "edge",
                "edge_voice": "",
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "openclaw:main",
            },
        }
    )
    store.update_secrets({"AGENT_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr("agent_switchboard.setup_service.module_available", lambda import_name: True)

    state = service.state()

    assert state["status"]["runtime_ready"] is False


def test_runtime_ready_accepts_vibevoice_live_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "language": "en",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["vibevoice"],
                "default_provider": "vibevoice",
                "vibevoice_base_url": "http://127.0.0.1:3000",
                "vibevoice_voice": "en-Carter_man",
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "openclaw:main",
                "session_key": "voice-main",
            },
            "validation": {
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["vibevoice"], "default_provider": "vibevoice"}
                    )
                },
                "vibevoice": {
                    "config_hash": service._config_hash(
                        {"base_url": "http://127.0.0.1:3000", "voice": "en-Carter_man"}
                    )
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "openclaw:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"AGENT_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr("agent_switchboard.setup_service.module_available", lambda import_name: True)

    state = service.state()

    assert state["status"]["vibevoice_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_runtime_ready_accepts_supertonic_live_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "language": "en",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["supertonic"],
                "default_provider": "supertonic",
                "supertonic_python_path": "/tmp/supertonic-python",
                "supertonic_voice": "M4",
                "supertonic_language": "en",
                "supertonic_total_steps": 2,
                "supertonic_speed": 1.05,
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "openclaw:main",
                "session_key": "voice-main",
            },
            "validation": {
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["supertonic"], "default_provider": "supertonic"}
                    )
                },
                "supertonic": {
                    "config_hash": service._config_hash(
                        {
                            "python_path": "/tmp/supertonic-python",
                            "voice": "M4",
                            "language": "en",
                            "total_steps": 2,
                            "speed": 1.05,
                        }
                    )
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "openclaw:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"AGENT_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr("agent_switchboard.setup_service.module_available", lambda import_name: import_name is None)

    state = service.state()

    assert state["status"]["supertonic_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_runtime_ready_accepts_pockettts_live_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "language": "en",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["pockettts"],
                "default_provider": "pockettts",
                "pockettts_voice": "alba",
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "openclaw:main",
                "session_key": "voice-main",
            },
            "validation": {
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["pockettts"], "default_provider": "pockettts"}
                    )
                },
                "pockettts": {
                    "config_hash": service._config_hash({"voice": "alba"})
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "openclaw:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"AGENT_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr(
        "agent_switchboard.setup_service.module_available",
        lambda import_name: import_name in {"pocket_tts", None},
    )

    state = service.state()

    assert state["status"]["pockettts_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_runtime_ready_rejects_pockettts_when_stt_language_is_not_english(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "language": "de",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["pockettts"],
                "default_provider": "pockettts",
                "pockettts_voice": "alba",
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "openclaw:main",
                "session_key": "voice-main",
            },
            "validation": {
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["pockettts"], "default_provider": "pockettts"}
                    )
                },
                "pockettts": {
                    "config_hash": service._config_hash({"voice": "alba"})
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "openclaw:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"AGENT_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr(
        "agent_switchboard.setup_service.module_available",
        lambda import_name: import_name in {"pocket_tts", None},
    )

    state = service.state()

    assert state["status"]["pockettts_ready"] is False
    assert state["status"]["runtime_ready"] is False


def test_runtime_ready_accepts_neutts_live_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["neutts"],
                "default_provider": "neutts",
                "neutts_backbone": "neuphonic/neutts-nano-german",
                "neutts_codec": "neuphonic/neucodec",
                "neutts_device": "cpu",
                "neutts_voice": "mara",
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "openclaw:main",
                "session_key": "voice-main",
            },
            "validation": {
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["neutts"], "default_provider": "neutts"}
                    )
                },
                "neutts": {
                    "config_hash": service._config_hash(
                        {
                            "backbone": "neuphonic/neutts-nano-german",
                            "codec": "neuphonic/neucodec",
                            "device": "cpu",
                            "voice": "mara",
                        }
                    )
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "openclaw:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"AGENT_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr(
        "agent_switchboard.setup_service.module_available",
        lambda import_name: import_name in {"neutts", None},
    )

    state = service.state()

    assert state["status"]["neutts_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_runtime_ready_accepts_disabled_tts_mode(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["disabled"],
                "default_provider": "disabled",
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "openclaw:main",
                "session_key": "voice-main",
            },
            "validation": {
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["disabled"], "default_provider": "disabled"}
                    )
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "openclaw:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"AGENT_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr("agent_switchboard.setup_service.module_available", lambda import_name: True)

    state = service.state()

    assert state["status"]["tts_selection_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_runtime_ready_accepts_piper_live_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["piper"],
                "default_provider": "piper",
                "piper_model_path": "/voices/de-demo.onnx",
                "piper_config_path": "/voices/de-demo.onnx.json",
                "piper_speaker": 1,
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "openclaw:main",
                "session_key": "voice-main",
            },
            "validation": {
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["piper"], "default_provider": "piper"}
                    )
                },
                "piper": {
                    "config_hash": service._config_hash(
                        {
                            "model_path": "/voices/de-demo.onnx",
                            "config_path": "/voices/de-demo.onnx.json",
                            "speaker": 1,
                        }
                    )
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "openclaw:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"AGENT_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr(
        "agent_switchboard.setup_service.module_available",
        lambda import_name: import_name == "piper",
    )

    state = service.state()

    assert state["status"]["piper_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_runtime_ready_accepts_chatterbox_live_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["chatterbox"],
                "default_provider": "chatterbox",
                "chatterbox_model": "multilingual",
                "chatterbox_device": "cpu",
                "chatterbox_language": "de",
                "chatterbox_voice": "mara",
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "openclaw:main",
                "session_key": "voice-main",
            },
            "validation": {
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["chatterbox"], "default_provider": "chatterbox"}
                    )
                },
                "chatterbox": {
                    "config_hash": service._config_hash(
                        {"model": "multilingual", "device": "cpu", "language": "de", "voice": "mara"}
                    )
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "openclaw:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"AGENT_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr("agent_switchboard.setup_service.module_available", lambda import_name: True)

    state = service.state()

    assert state["status"]["chatterbox_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_runtime_ready_accepts_hermes_live_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    hermes_root = tmp_path / "hermes-agent"
    python_bin = hermes_root / "venv" / "bin"
    python_bin.mkdir(parents=True)
    (python_bin / "python").write_text("", encoding="utf-8")
    store.update_config(
        {
            "agent": {
                "backend": "hermes",
                "hermes_root": str(hermes_root.resolve()),
            },
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["edge"],
                "default_provider": "edge",
                "edge_voice": "en-US-AvaNeural",
            },
            "validation": {
                "edge": {
                    "config_hash": service._config_hash(
                        {"voice": "en-US-AvaNeural", "rate": "+0%"}
                    )
                },
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["edge"], "default_provider": "edge"}
                    )
                },
                "hermes": {
                    "config_hash": service._config_hash(
                        {"hermes_root": str(hermes_root.resolve())}
                    )
                },
            },
        }
    )

    monkeypatch.setattr("agent_switchboard.setup_service.module_available", lambda import_name: True)

    state = service.state()

    assert state["status"]["hermes_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_validate_windows_client_normalizes_and_persists_shortcuts(tmp_path):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    result = service.validate_windows_client(
        {
            "toggle_window": "control + shift + space",
            "pause_resume": "ctrl + shift + keyp",
            "interrupt": "alt + ctrl + a",
        }
    )
    saved = store.load_config()

    assert result == {
        "ok": True,
        "shortcuts": {
            "toggle_window": "Ctrl+Shift+Space",
            "pause_resume": "Ctrl+Shift+P",
            "interrupt": "Ctrl+Alt+A",
        },
    }
    assert saved["windows_client"]["shortcuts"] == result["shortcuts"]
    assert saved["validation"]["windows_client"]["config_hash"]


def test_validate_windows_client_rejects_duplicate_shortcuts(tmp_path):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    with pytest.raises(ValidationError, match="Windows client shortcuts must be unique."):
        service.validate_windows_client(
            {
                "toggle_window": "Ctrl+Shift+Space",
                "pause_resume": "Ctrl+Shift+Space",
                "interrupt": "Ctrl+Alt+A",
            }
        )


def test_validate_tts_selection_rejects_disabled_with_other_provider(tmp_path):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    with pytest.raises(ValidationError, match="Disabled TTS must be selected on its own."):
        asyncio.run(
            service.validate_tts_selection(
                {
                    "enabled_providers": ["disabled", "edge"],
                    "default_provider": "disabled",
                }
            )
        )
