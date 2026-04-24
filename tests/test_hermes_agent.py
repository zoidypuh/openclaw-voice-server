import asyncio
import sys
import types

from agentic_switchboard.agents import hermes as hermes_module


def test_reply_sanity_system_prompt_handles_random_subtitles_and_invented_people():
    prompt = hermes_module._REPLY_SANITY_SYSTEM_PROMPT.lower()

    assert "subtitle" in prompt
    assert "person" in prompt or "people" in prompt
    assert "name" in prompt
    assert "ask" in prompt


def test_reply_looks_like_backend_error_detects_retry_error_text():
    assert hermes_module._reply_looks_like_backend_error(
        "API call failed after 3 retries: HTTP 402: Insufficient credits."
    )
    assert hermes_module._reply_looks_like_backend_error(
        "HTTP 401 unauthorized"
    )
    assert not hermes_module._reply_looks_like_backend_error("Okay, got it.")


def test_format_recent_voice_turns_keeps_only_last_three():
    formatted = hermes_module._format_recent_voice_turns(
        [
            ("u1", "a1"),
            ("u2", "a2"),
            ("u3", "a3"),
            ("u4", "a4"),
        ],
        limit=3,
    )

    assert "u1" not in formatted
    assert "a1" not in formatted
    assert "u2" in formatted
    assert "a2" in formatted
    assert "u4" in formatted
    assert "a4" in formatted


def test_hermes_conversation_agent_replaces_incoherent_reply_with_huh(monkeypatch):
    instances = []

    class FakeSession:
        def __init__(
            self,
            *,
            system_prompt,
            session_id,
            empty_reply_error,
            project_root=None,
            gateway_url=None,
            gateway_token=None,
            gateway_model=None,
            use_context_files=True,
            use_memory=True,
            enabled_toolsets=None,
        ):
            self.system_prompt = system_prompt
            self.session_id = session_id
            self.empty_reply_error = empty_reply_error
            self.project_root = project_root
            self.gateway_url = gateway_url
            self.gateway_token = gateway_token
            self.gateway_model = gateway_model
            self.use_context_files = use_context_files
            self.use_memory = use_memory
            self.prompts = []
            self.replace_calls = []
            self.main_session = system_prompt.startswith("Du bist Mara")
            instances.append(self)

        async def ask(self, prompt):
            assert self.main_session is True
            self.prompts.append(prompt)
            return "<voice> You want it? You got it!"

        async def ask_once(self, prompt):
            assert self.main_session is False
            self.prompts.append(prompt)
            return "HUH"

        def replace_last_assistant_reply(self, text):
            self.replace_calls.append(text)

    monkeypatch.setattr(hermes_module, "_HermesAgentSession", FakeSession)

    async def scenario():
        agent = hermes_module.HermesConversationAgent(project_root="/tmp/hermes-agent")
        abort_event = asyncio.Event()
        return [chunk async for chunk in agent.stream_reply("that would help", abort_event)]

    chunks = asyncio.run(scenario())

    assert chunks == ["Huh?"]
    assert len(instances) == 2
    main_session, sanity_session = instances
    assert main_session.replace_calls == ["Huh?"]
    assert main_session.prompts == ["that would help"]
    assert "Current user: that would help" in sanity_session.prompts[0]
    assert "Candidate reply: <voice> You want it? You got it!" in sanity_session.prompts[0]


def test_hermes_conversation_agent_asks_for_clarification_on_random_person_or_name(monkeypatch):
    instances = []

    class FakeSession:
        def __init__(
            self,
            *,
            system_prompt,
            session_id,
            empty_reply_error,
            project_root=None,
            gateway_url=None,
            gateway_token=None,
            gateway_model=None,
            use_context_files=True,
            use_memory=True,
            enabled_toolsets=None,
        ):
            self.system_prompt = system_prompt
            self.prompts = []
            self.replace_calls = []
            self.main_session = system_prompt.startswith("Du bist Mara")
            instances.append(self)

        async def ask(self, prompt):
            assert self.main_session is True
            self.prompts.append(prompt)
            return "Yeah, Daniel probably told Zeynep already."

        async def ask_once(self, prompt):
            assert self.main_session is False
            self.prompts.append(prompt)
            return "ASK"

        def replace_last_assistant_reply(self, text):
            self.replace_calls.append(text)

    monkeypatch.setattr(hermes_module, "_HermesAgentSession", FakeSession)

    async def scenario():
        agent = hermes_module.HermesConversationAgent(project_root="/tmp/hermes-agent")
        abort_event = asyncio.Event()
        return [chunk async for chunk in agent.stream_reply("wait what did he say?", abort_event)]

    chunks = asyncio.run(scenario())

    assert chunks == [hermes_module._DEFAULT_REPLY_SANITY_CLARIFY_FALLBACK]
    assert len(instances) == 2
    main_session, sanity_session = instances
    assert main_session.replace_calls == [hermes_module._DEFAULT_REPLY_SANITY_CLARIFY_FALLBACK]
    assert "Current user: wait what did he say?" in sanity_session.prompts[0]
    assert "Candidate reply: Yeah, Daniel probably told Zeynep already." in sanity_session.prompts[0]


def test_hermes_conversation_agent_skips_sanity_check_for_backend_error_reply(monkeypatch):
    instances = []

    class FakeSession:
        def __init__(
            self,
            *,
            system_prompt,
            session_id,
            empty_reply_error,
            project_root=None,
            gateway_url=None,
            gateway_token=None,
            gateway_model=None,
            use_context_files=True,
            use_memory=True,
            enabled_toolsets=None,
        ):
            self.system_prompt = system_prompt
            self.prompts = []
            self.replace_calls = []
            self.main_session = system_prompt.startswith("Du bist Mara")
            instances.append(self)

        async def ask(self, prompt):
            assert self.main_session is True
            self.prompts.append(prompt)
            return "API call failed after 3 retries: HTTP 402: Insufficient credits."

        async def ask_once(self, prompt):
            raise AssertionError("sanity check should be skipped for backend error replies")

        def replace_last_assistant_reply(self, text):
            self.replace_calls.append(text)

    monkeypatch.setattr(hermes_module, "_HermesAgentSession", FakeSession)

    async def scenario():
        agent = hermes_module.HermesConversationAgent(project_root="/tmp/hermes-agent")
        abort_event = asyncio.Event()
        return [chunk async for chunk in agent.stream_reply("hello?", abort_event)]

    chunks = asyncio.run(scenario())

    assert chunks == ["API call failed after 3 retries: HTTP 402: Insufficient credits."]
    assert len(instances) == 2
    main_session, sanity_session = instances
    assert main_session.replace_calls == []
    assert main_session.prompts == ["hello?"]
    assert sanity_session.prompts == []


def test_hermes_conversation_agent_sanity_prompt_uses_sliding_last_three_turns(monkeypatch):
    instances = []
    replies = iter(["a1", "a2", "a3", "a4", "a5"])

    class FakeSession:
        def __init__(
            self,
            *,
            system_prompt,
            session_id,
            empty_reply_error,
            project_root=None,
            gateway_url=None,
            gateway_token=None,
            gateway_model=None,
            use_context_files=True,
            use_memory=True,
            enabled_toolsets=None,
        ):
            self.system_prompt = system_prompt
            self.prompts = []
            self.replace_calls = []
            self.main_session = system_prompt.startswith("Du bist Mara")
            instances.append(self)

        async def ask(self, prompt):
            assert self.main_session is True
            self.prompts.append(prompt)
            return next(replies)

        async def ask_once(self, prompt):
            assert self.main_session is False
            self.prompts.append(prompt)
            return "OK"

        def replace_last_assistant_reply(self, text):
            self.replace_calls.append(text)

    monkeypatch.setattr(hermes_module, "_HermesAgentSession", FakeSession)

    async def scenario():
        agent = hermes_module.HermesConversationAgent(project_root="/tmp/hermes-agent")
        abort_event = asyncio.Event()
        outputs = []
        for text in ["u1", "u2", "u3", "u4", "u5"]:
            outputs.append([chunk async for chunk in agent.stream_reply(text, abort_event)])
        return outputs

    outputs = asyncio.run(scenario())

    assert outputs == [["a1"], ["a2"], ["a3"], ["a4"], ["a5"]]
    assert len(instances) == 2
    main_session, sanity_session = instances
    assert main_session.replace_calls == []
    last_prompt = sanity_session.prompts[-1]
    assert "Turn 1 user: u1" not in last_prompt
    assert "Turn 1 assistant: a1" not in last_prompt
    assert "Turn 1 user: u2" in last_prompt
    assert "Turn 2 user: u3" in last_prompt
    assert "Turn 3 user: u4" in last_prompt
    assert "Current user: u5" in last_prompt
    assert "Candidate reply: a5" in last_prompt


def test_hermes_session_keeps_nested_local_proxy_as_custom_openai(monkeypatch, tmp_path):
    captured = {}
    api_key = "unit-test-api-key"

    class FakeAIAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_config_module = types.ModuleType("hermes_cli.config")
    fake_config_module.load_config = lambda: {
        "model": {
            "default": "gpt-5.4",
            "api_key": api_key,
            "base_url": "http://127.0.0.1:8317/v1",
            "provider": "custom",
            "api_mode": "chat_completions",
        }
    }
    fake_run_agent_module = types.ModuleType("run_agent")
    fake_run_agent_module.AIAgent = FakeAIAgent

    monkeypatch.setitem(sys.modules, "hermes_cli.config", fake_config_module)
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent_module)
    monkeypatch.setattr(
        hermes_module._HermesAgentSession,
        "_resolve_subprocess_python",
        staticmethod(lambda project_root: tmp_path / "python"),
    )

    session = hermes_module._HermesAgentSession(
        system_prompt="You are Mara.",
        session_id="test-session",
        empty_reply_error="nope",
        project_root=str(tmp_path),
    )

    assert session._agent is not None
    assert captured["model"] == "gpt-5.4"
    assert captured["provider"] == "custom"
    assert captured["api_mode"] == "chat_completions"
    assert captured["api_key"] == api_key
    assert captured["base_url"] == "http://127.0.0.1:8317/v1"


def test_hermes_session_passes_enabled_toolsets_to_aiagent(monkeypatch, tmp_path):
    captured = {}

    class FakeAIAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_config_module = types.ModuleType("hermes_cli.config")
    fake_config_module.load_config = lambda: {
        "model": {
            "default": "gpt-5.4",
            "api_key": "***",
            "base_url": "http://127.0.0.1:8317/v1",
            "provider": "custom",
            "api_mode": "chat_completions",
        }
    }
    fake_run_agent_module = types.ModuleType("run_agent")
    fake_run_agent_module.AIAgent = FakeAIAgent

    monkeypatch.setitem(sys.modules, "hermes_cli.config", fake_config_module)
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent_module)
    monkeypatch.setattr(
        hermes_module._HermesAgentSession,
        "_resolve_subprocess_python",
        staticmethod(lambda project_root: tmp_path / "python"),
    )

    session = hermes_module._HermesAgentSession(
        system_prompt="You are Mara.",
        session_id="test-session",
        empty_reply_error="nope",
        project_root=str(tmp_path),
        enabled_toolsets=["browser", "file"],
    )

    assert session._agent is not None
    assert captured["enabled_toolsets"] == ["browser", "file"]


def test_hermes_session_subprocess_payload_keeps_enabled_toolsets(monkeypatch, tmp_path):
    monkeypatch.setattr(
        hermes_module._HermesAgentSession,
        "_resolve_subprocess_python",
        staticmethod(lambda project_root: tmp_path / "python"),
    )
    monkeypatch.setattr(
        hermes_module._HermesAgentSession,
        "_build_agent",
        lambda self, project_root: object(),
    )

    session = hermes_module._HermesAgentSession(
        system_prompt="You are Mara.",
        session_id="test-session",
        empty_reply_error="nope",
        project_root=str(tmp_path),
        enabled_toolsets=["browser", "file"],
    )

    payload = session._subprocess_payload(prompt="hi")

    assert payload["enabled_toolsets"] == ["browser", "file"]
