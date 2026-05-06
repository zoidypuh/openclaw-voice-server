import asyncio

import pytest

from maras_switchboard.config_store import ConfigStore
from maras_switchboard.errors import ValidationError
from maras_switchboard.setup_service import SetupService


def test_validate_stt_persists_validated_selection(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    monkeypatch.setattr(
        "maras_switchboard.setup_service.validate_stt_selection_step",
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

    monkeypatch.setattr("maras_switchboard.setup_service.validate_elevenlabs_api_key_step", fake_validate_key)
    monkeypatch.setattr("maras_switchboard.setup_service.list_elevenlabs_voices", fake_list_voices)
    monkeypatch.setattr("maras_switchboard.setup_service.validate_elevenlabs_voice_step", fake_validate_voice)

    key_result = asyncio.run(service.validate_elevenlabs_key({"api_key": "sk-test"}))
    asyncio.run(
        service.validate_elevenlabs_voice(
            {"voice_id": "voice-123", "model_id": "eleven-model", "preset_name": "expressive"}
        )
    )

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    saved = store.load_config()

    assert key_result["voices"] == [{"voice_id": "voice-123", "name": "Resolved Voice"}]
    assert "MARAS_SWITCHBOARD_ELEVENLABS_API_KEY=sk-test" in env_text
    assert saved["tts"]["elevenlabs_voice_id"] == "voice-123"
    assert saved["tts"]["elevenlabs_voice_name"] == "Resolved Voice"
    assert saved["tts"]["elevenlabs_model"] == "eleven-model"
    assert saved["tts"]["elevenlabs_preset"] == "expressive"
    assert saved["validation"]["eleven_key"]["api_key_fingerprint"]
    assert saved["validation"]["eleven_voice"]["config_hash"]


def test_elevenlabs_voices_uses_saved_secret(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    store.update_secrets({"MARAS_SWITCHBOARD_ELEVENLABS_API_KEY": "sk-saved"})

    async def fake_list_voices(api_key):
        assert api_key == "sk-saved"
        return [{"voice_id": "voice-abc", "name": "Saved Voice"}]

    monkeypatch.setattr("maras_switchboard.setup_service.list_elevenlabs_voices", fake_list_voices)

    result = asyncio.run(service.elevenlabs_voices())

    assert result == {"ok": True, "voices": [{"voice_id": "voice-abc", "name": "Saved Voice"}]}


def test_validate_xai_tts_persists_resolved_settings(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    async def fake_validate_xai_tts(*, api_key, voice_id, language, codec, sample_rate, bit_rate):
        assert api_key == "xai-test"
        assert voice_id == "Eve"
        assert language == "en"
        assert codec == "mp3"
        assert sample_rate == 44100
        assert bit_rate == 128000
        return {
            "ok": True,
            "voice_id": voice_id,
            "voice_name": voice_id,
            "language": language,
            "output_format": {"codec": codec, "sample_rate": sample_rate, "bit_rate": bit_rate},
            "audio_bytes": 1234,
        }

    monkeypatch.setattr("maras_switchboard.setup_service.validate_xai_tts_voice_step", fake_validate_xai_tts)

    result = asyncio.run(
        service.validate_xai_tts(
            {
                "api_key": "xai-test",
                "voice_id": "eve",
                "language": "en",
                "codec": "mp3",
                "sample_rate": "44100",
                "bit_rate": "128000",
            }
        )
    )

    saved = store.load_config()
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")

    assert result["audio_bytes"] == 1234
    assert "MARAS_SWITCHBOARD_XAI_API_KEY=xai-test" in env_text
    assert saved["tts"]["xai_voice_id"] == "Eve"
    assert saved["tts"]["xai_language"] == "en"
    assert saved["tts"]["xai_output_codec"] == "mp3"
    assert saved["tts"]["xai_sample_rate"] == 44100
    assert saved["tts"]["xai_bit_rate"] == 128000
    assert saved["validation"]["xai_tts"]["config_hash"]
    assert saved["validation"]["xai_tts"]["api_key_fingerprint"]


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

    monkeypatch.setattr("maras_switchboard.setup_service.validate_supertonic_voice_step", fake_validate_supertonic)

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


def test_validate_chatterbox_turbo_persists_resolved_settings(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    python_path = tmp_path / "python"
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    python_path.chmod(0o755)
    voice_prompt_path = tmp_path / "voice.wav"
    voice_prompt_path.write_bytes(b"RIFFdemo")

    async def fake_validate_chatterbox(
        *,
        python_path,
        voice_prompt_path,
        device,
        exaggeration,
        temperature,
        top_p,
        top_k,
        repetition_penalty,
    ):
        return {
            "ok": True,
            "python_path": python_path,
            "voice_prompt_path": voice_prompt_path,
            "device": device,
            "exaggeration": exaggeration,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "repetition_penalty": repetition_penalty,
        }

    monkeypatch.setattr(
        "maras_switchboard.setup_service.validate_chatterbox_turbo_voice_step",
        fake_validate_chatterbox,
    )

    result = asyncio.run(
        service.validate_chatterbox_turbo(
            {
                "python_path": str(python_path),
                "voice_prompt_path": str(voice_prompt_path),
                "device": "cpu",
                "exaggeration": "0.6",
                "temperature": "0.7",
                "top_p": "0.9",
                "top_k": "900",
                "repetition_penalty": "1.1",
            }
        )
    )

    saved = store.load_config()

    assert result["device"] == "cpu"
    assert saved["tts"]["chatterbox_python_path"] == str(python_path.resolve())
    assert saved["tts"]["chatterbox_voice_prompt_path"] == str(voice_prompt_path.resolve())
    assert saved["tts"]["chatterbox_device"] == "cpu"
    assert saved["tts"]["chatterbox_exaggeration"] == 0.6
    assert saved["tts"]["chatterbox_temperature"] == 0.7
    assert saved["tts"]["chatterbox_top_p"] == 0.9
    assert saved["tts"]["chatterbox_top_k"] == 900
    assert saved["tts"]["chatterbox_repetition_penalty"] == 1.1
    assert saved["validation"]["chatterbox_turbo"]["config_hash"]


def test_validate_gateway_saves_secret_and_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    async def fake_validate_gateway_connection(*, url, token, model, session_key):
        assert url == "https://gateway.test.ts.net/v1/chat/completions"
        assert token == "gw-secret"
        assert model == "maras-switchboard:test"
        assert session_key == "voice-main"
        return {"ok": True, "reply_preview": "OK"}

    monkeypatch.setattr(
        "maras_switchboard.setup_service.validate_gateway_connection",
        fake_validate_gateway_connection,
    )

    result = asyncio.run(
        service.validate_gateway(
            {
                "url": "gateway.test.ts.net",
                "token": "gw-secret",
                "model": "maras-switchboard:test",
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
    assert "MARAS_SWITCHBOARD_GATEWAY_TOKEN=gw-secret" in env_text
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
        api_url=None,
        api_key=None,
        api_model=None,
        profile=None,
    ):
        assert project_root == "/tmp/hermes-agent"
        assert gateway_url is None
        assert gateway_token is None
        assert gateway_model is None
        assert api_url == "http://127.0.0.1:8642/v1/chat/completions"
        assert api_key == ""
        assert api_model == "hermes-agent"
        assert profile == "voice"
        return {
            "ok": True,
            "project_root": resolved_root,
            "profile": "voice",
            "hermes_home": str((tmp_path / ".hermes" / "profiles" / "voice").resolve()),
            "api_url": "http://127.0.0.1:8642/v1/chat/completions",
            "reply_preview": "OK",
        }

    monkeypatch.setattr(
        "maras_switchboard.setup_service.validate_hermes_connection",
        fake_validate_hermes_connection,
    )

    result = asyncio.run(
        service.validate_agent(
            {
                "backend": "hermes",
                "hermes_root": "/tmp/hermes-agent",
                "hermes_api_url": "http://127.0.0.1:8642",
                "hermes_api_key": "",
                "hermes_api_model": "hermes-agent",
            }
        )
    )
    saved = store.load_config()

    assert result["backend"] == "hermes"
    assert result["profile"] == "voice"
    assert saved["agent"]["backend"] == "hermes"
    assert saved["agent"]["hermes_root"] == resolved_root
    assert saved["agent"]["hermes_profile"] == "voice"
    assert saved["agent"]["hermes_api_url"] == "http://127.0.0.1:8642/v1/chat/completions"
    assert saved["agent"]["hermes_api_model"] == "hermes-agent"
    assert saved["validation"]["hermes"]["config_hash"]
    assert saved["validation"]["hermes"]["api_key_fingerprint"] == ""



def test_validate_agent_saves_optional_hermes_api_key(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    resolved_root = str((tmp_path / "hermes-agent").resolve())

    async def fake_validate_hermes_connection(
        *,
        project_root,
        gateway_url=None,
        gateway_token=None,
        gateway_model=None,
        api_url=None,
        api_key=None,
        api_model=None,
        profile=None,
    ):
        assert api_url == "https://hermes.example.test/v1/chat/completions"
        assert api_key == "local-secret"
        assert api_model == "mara-agent"
        return {
            "ok": True,
            "project_root": resolved_root,
            "profile": profile,
            "hermes_home": str((tmp_path / ".hermes" / "profiles" / "voice").resolve()),
            "api_url": api_url,
            "reply_preview": "OK",
        }

    monkeypatch.setattr(
        "maras_switchboard.setup_service.validate_hermes_connection",
        fake_validate_hermes_connection,
    )

    result = asyncio.run(
        service.validate_agent(
            {
                "backend": "hermes",
                "hermes_root": "/tmp/hermes-agent",
                "hermes_api_url": "https://hermes.example.test",
                "hermes_api_key": "local-secret",
                "hermes_api_model": "mara-agent",
            }
        )
    )
    saved = store.load_config()
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")

    assert result["api_url"] == "https://hermes.example.test/v1/chat/completions"
    assert saved["agent"]["hermes_api_url"] == "https://hermes.example.test/v1/chat/completions"
    assert saved["agent"]["hermes_api_model"] == "mara-agent"
    assert "MARAS_SWITCHBOARD_HERMES_API_KEY=local-secret" in env_text
    assert saved["validation"]["hermes"]["api_key_fingerprint"] == service._fingerprint_secret("local-secret")

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
        "maras_switchboard.setup_service.module_available",
        lambda import_name: False,
    )

    state = service.state()

    assert state["status"]["stt_ready"] is True


def test_setup_state_allows_xai_stt_with_api_key(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    stt_config = {
        "enabled_backends": ["xai"],
        "default_backend": "xai",
        "language": "en",
        "device": "cpu",
        "compute_type": "int8",
        "whisper_endpoint_url": "",
        "whisper_endpoint_model": "",
        "backend_models": {"faster-whisper": "large-v3", "whisper": "large", "xai": "xai-stt"},
    }
    store.update_config(
        {
            "stt": stt_config,
            "validation": {
                "stt": {
                    "config_hash": service._config_hash(stt_config),
                }
            },
        }
    )
    store.update_secrets({"XAI_API_KEY": "xai-test"})

    monkeypatch.setattr("maras_switchboard.setup_service.module_available", lambda import_name: False)

    state = service.state()

    assert state["status"]["stt_ready"] is True
    assert state["saved"]["stt"]["xai_api_key_present"] is True


def test_setup_state_requires_xai_api_key_for_xai_stt(tmp_path, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("MARAS_SWITCHBOARD_XAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENTIC_SWITCHBOARD_XAI_API_KEY", raising=False)
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    stt_config = {
        "enabled_backends": ["xai"],
        "default_backend": "xai",
        "language": "en",
        "device": "cpu",
        "compute_type": "int8",
        "whisper_endpoint_url": "",
        "whisper_endpoint_model": "",
        "backend_models": {"faster-whisper": "large-v3", "whisper": "large", "xai": "xai-stt"},
    }
    store.update_config(
        {
            "stt": stt_config,
            "validation": {
                "stt": {
                    "config_hash": service._config_hash(stt_config),
                }
            },
        }
    )

    monkeypatch.setattr("maras_switchboard.setup_service.module_available", lambda import_name: True)

    state = service.state()

    assert state["status"]["stt_ready"] is False
    assert state["status"]["runtime_ready"] is False


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
    assert state["hints"]["default_remote_whisper_endpoint_model"] == "distil-large-v3"
    assert state["hints"]["remote_whisper_host_alias"] == "remote-whisper"


def test_setup_state_ignores_unresolvable_default_remote_whisper_alias(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    monkeypatch.setattr(service, "_resolve_ssh_hostname", lambda alias: "remote-whisper")
    monkeypatch.setattr(service, "_host_is_resolvable", lambda host: False)

    state = service.state()

    assert state["hints"]["default_remote_whisper_endpoint_url"] == ""


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
                "model": "maras-switchboard:main",
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
                            "model": "maras-switchboard:main",
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
            "MARAS_SWITCHBOARD_ELEVENLABS_API_KEY": "sk-test",
            "MARAS_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret",
        }
    )

    monkeypatch.setattr("maras_switchboard.setup_service.module_available", lambda import_name: False)

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
                "model": "maras-switchboard:main",
            },
        }
    )
    store.update_secrets({"MARAS_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr("maras_switchboard.setup_service.module_available", lambda import_name: True)

    state = service.state()

    assert state["status"]["runtime_ready"] is False


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
                "model": "maras-switchboard:main",
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
                            "model": "maras-switchboard:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"MARAS_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr("maras_switchboard.setup_service.module_available", lambda import_name: import_name is None)

    state = service.state()

    assert state["status"]["supertonic_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_runtime_ready_accepts_xai_tts_live_config(tmp_path, monkeypatch):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)
    output_format = {"codec": "mp3", "sample_rate": 44100, "bit_rate": 128000}
    store.update_config(
        {
            "stt": {
                "enabled_backends": ["whisper"],
                "default_backend": "whisper",
                "language": "en",
                "whisper_endpoint_url": "http://127.0.0.1:18000/v1/audio/transcriptions",
            },
            "tts": {
                "enabled_providers": ["xai"],
                "default_provider": "xai",
                "xai_voice_id": "Eve",
                "xai_language": "en",
                "xai_output_codec": "mp3",
                "xai_sample_rate": 44100,
                "xai_bit_rate": 128000,
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "maras-switchboard:main",
                "session_key": "voice-main",
            },
            "validation": {
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["xai"], "default_provider": "xai"}
                    )
                },
                "xai_tts": {
                    "config_hash": service._config_hash(
                        {"voice_id": "Eve", "language": "en", "output_format": output_format}
                    ),
                    "api_key_fingerprint": service._fingerprint_secret("xai-test"),
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "maras-switchboard:main",
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
            "MARAS_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret",
            "XAI_API_KEY": "xai-test",
        }
    )
    monkeypatch.setenv("XAI_API_KEY", "xai-test")

    monkeypatch.setattr("maras_switchboard.setup_service.module_available", lambda import_name: import_name is None)

    state = service.state()

    assert state["status"]["xai_tts_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_runtime_ready_accepts_chatterbox_turbo_live_config(tmp_path, monkeypatch):
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
                "enabled_providers": ["chatterbox-turbo"],
                "default_provider": "chatterbox-turbo",
                "chatterbox_python_path": "/tmp/chatterbox-python",
                "chatterbox_voice_prompt_path": "/tmp/voice.wav",
                "chatterbox_device": "cpu",
                "chatterbox_exaggeration": 0.5,
                "chatterbox_temperature": 0.8,
                "chatterbox_top_p": 0.95,
                "chatterbox_top_k": 1000,
                "chatterbox_repetition_penalty": 1.2,
            },
            "gateway": {
                "url": "http://127.0.0.1:18789/v1/chat/completions",
                "model": "maras-switchboard:main",
                "session_key": "voice-main",
            },
            "validation": {
                "tts": {
                    "config_hash": service._config_hash(
                        {"enabled_providers": ["chatterbox-turbo"], "default_provider": "chatterbox-turbo"}
                    )
                },
                "chatterbox_turbo": {
                    "config_hash": service._config_hash(
                        {
                            "python_path": "/tmp/chatterbox-python",
                            "voice_prompt_path": "/tmp/voice.wav",
                            "device": "cpu",
                            "exaggeration": 0.5,
                            "temperature": 0.8,
                            "top_p": 0.95,
                            "top_k": 1000,
                            "repetition_penalty": 1.2,
                        }
                    )
                },
                "gateway": {
                    "config_hash": service._config_hash(
                        {
                            "url": "http://127.0.0.1:18789/v1/chat/completions",
                            "model": "maras-switchboard:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"MARAS_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr("maras_switchboard.setup_service.module_available", lambda import_name: import_name is None)

    state = service.state()

    assert state["status"]["chatterbox_ready"] is True
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
                "model": "maras-switchboard:main",
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
                            "model": "maras-switchboard:main",
                            "session_key": "voice-main",
                        }
                    ),
                    "token_fingerprint": service._fingerprint_secret("gw-secret"),
                },
            },
        }
    )
    store.update_secrets({"MARAS_SWITCHBOARD_GATEWAY_TOKEN": "gw-secret"})

    monkeypatch.setattr("maras_switchboard.setup_service.module_available", lambda import_name: True)

    state = service.state()

    assert state["status"]["tts_selection_ready"] is True
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
                            {
                                "hermes_root": str(hermes_root.resolve()),
                                "hermes_profile": "voice",
                                "hermes_api_url": "http://127.0.0.1:8646/v1/chat/completions",
                            }
                        ),
                    "api_key_fingerprint": "",
                },
            },
        }
    )

    monkeypatch.setattr("maras_switchboard.setup_service.module_available", lambda import_name: True)

    state = service.state()

    assert state["status"]["hermes_ready"] is True
    assert state["status"]["runtime_ready"] is True


def test_validate_windows_client_persists_fixed_client_state(tmp_path):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    result = service.validate_windows_client({})
    saved = store.load_config()

    assert result == {"ok": True}
    assert saved["windows_client"] == {}
    assert saved["validation"]["windows_client"]["config_hash"]


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


def test_validate_tts_selection_rejects_removed_provider(tmp_path):
    store = ConfigStore(config_path=tmp_path / "config.json", env_path=tmp_path / ".env")
    service = SetupService(store)

    with pytest.raises(ValidationError, match="Unsupported TTS provider: piper"):
        asyncio.run(
            service.validate_tts_selection(
                {
                    "enabled_providers": ["piper"],
                    "default_provider": "piper",
                }
            )
        )
