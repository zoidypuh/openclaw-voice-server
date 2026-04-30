import asyncio

from maras_switchboard.agents import hermes as hermes_module


def test_reply_sanity_system_prompt_handles_random_subtitles_and_invented_people():
    prompt = hermes_module._REPLY_SANITY_SYSTEM_PROMPT.lower()

    assert "subtitle" in prompt
    assert "person" in prompt or "people" in prompt
    assert "name" in prompt
    assert "ask" in prompt


def test_voice_transcript_system_prompt_warns_about_stt_and_contextual_glitches():
    prompt = hermes_module._build_voice_transcript_system_prompt(
        "please continue",
        voice_context="Recent topic: Qwen setup.",
    )
    lowered = prompt.lower()

    assert prompt.startswith("[Voice/STT transcript note]")
    assert "voice transcription / STT" in prompt
    assert "missing words" in lowered
    assert "qwen" in lowered
    assert "Meintest du X" in prompt
    assert "Recent topic: Qwen setup." in prompt
    assert "User transcript" not in prompt
    assert "please continue" not in prompt


def test_reply_looks_like_backend_error_detects_retry_error_text():
    assert hermes_module._reply_looks_like_backend_error(
        "API call failed after 3 retries: HTTP 402: Insufficient credits."
    )
    assert hermes_module._reply_looks_like_backend_error(
        "HTTP 401 unauthorized"
    )
    assert not hermes_module._reply_looks_like_backend_error("Okay, got it.")


def test_empty_enabled_toolsets_stays_empty_for_low_latency_voice_chat():
    assert hermes_module._normalize_enabled_toolsets([]) == []
    assert hermes_module._normalize_enabled_toolsets(None) == []


def test_delegate_intent_detects_explicit_voice_handoff_phrases():
    assert hermes_module._voice_text_requests_full_mara("delegate recherchiere das bitte")
    assert hermes_module._voice_text_requests_full_mara("Mara mach du das im Terminal")
    assert hermes_module._voice_text_requests_full_mara("kannst du das kurz im browser suchen")
    assert not hermes_module._voice_text_requests_full_mara("ja klingt gut")


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
            api_url=None,
            api_key=None,
            api_model=None,
            profile=None,
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
            raise AssertionError("voice prompt must pass STT note as ephemeral system prompt")

        async def ask_voice(self, prompt, *, ephemeral_system_prompt=""):
            assert self.main_session is True
            self.prompts.append(prompt)
            self.ephemeral_system_prompt = ephemeral_system_prompt
            return "<voice> You want it? You got it!"

        async def ask_once(self, prompt):
            assert self.main_session is False
            self.prompts.append(prompt)
            return "HUH"

        def replace_last_assistant_reply(self, text):
            self.replace_calls.append(text)

    monkeypatch.setattr(hermes_module, "_HermesAgentSession", FakeSession)
    monkeypatch.setattr(hermes_module, "_build_voice_context_blob", lambda text: "")

    async def scenario():
        agent = hermes_module.HermesConversationAgent(project_root="/tmp/hermes-agent")
        abort_event = asyncio.Event()
        return [chunk async for chunk in agent.stream_reply("that would help", abort_event)]

    chunks = asyncio.run(scenario())

    assert chunks == ["Huh?"]
    assert len(instances) == 2
    main_session, sanity_session = instances
    assert main_session.replace_calls == ["Huh?"]
    assert main_session.prompts[0] == "that would help"
    assert main_session.ephemeral_system_prompt.startswith("[Voice/STT transcript note]")
    assert "User transcript" not in main_session.ephemeral_system_prompt
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
            api_url=None,
            api_key=None,
            api_model=None,
            profile=None,
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
            raise AssertionError("voice prompt must pass STT note as ephemeral system prompt")

        async def ask_voice(self, prompt, *, ephemeral_system_prompt=""):
            assert self.main_session is True
            self.prompts.append(prompt)
            self.ephemeral_system_prompt = ephemeral_system_prompt
            return "Yeah, Daniel probably told Zeynep already."

        async def ask_once(self, prompt):
            assert self.main_session is False
            self.prompts.append(prompt)
            return "ASK"

        def replace_last_assistant_reply(self, text):
            self.replace_calls.append(text)

    monkeypatch.setattr(hermes_module, "_HermesAgentSession", FakeSession)
    monkeypatch.setattr(hermes_module, "_build_voice_context_blob", lambda text: "")

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
            api_url=None,
            api_key=None,
            api_model=None,
            profile=None,
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
            raise AssertionError("voice prompt must pass STT note as ephemeral system prompt")

        async def ask_voice(self, prompt, *, ephemeral_system_prompt=""):
            assert self.main_session is True
            self.prompts.append(prompt)
            self.ephemeral_system_prompt = ephemeral_system_prompt
            return "API call failed after 3 retries: HTTP 402: Insufficient credits."

        async def ask_once(self, prompt):
            raise AssertionError("sanity check should be skipped for backend error replies")

        def replace_last_assistant_reply(self, text):
            self.replace_calls.append(text)

    monkeypatch.setattr(hermes_module, "_HermesAgentSession", FakeSession)
    monkeypatch.setattr(hermes_module, "_build_voice_context_blob", lambda text: "")

    async def scenario():
        agent = hermes_module.HermesConversationAgent(project_root="/tmp/hermes-agent")
        abort_event = asyncio.Event()
        return [chunk async for chunk in agent.stream_reply("hello?", abort_event)]

    chunks = asyncio.run(scenario())

    assert chunks == ["API call failed after 3 retries: HTTP 402: Insufficient credits."]
    assert len(instances) == 2
    main_session, sanity_session = instances
    assert main_session.replace_calls == []
    assert main_session.prompts[0] == "hello?"
    assert main_session.ephemeral_system_prompt.startswith("[Voice/STT transcript note]")
    assert "User transcript" not in main_session.ephemeral_system_prompt
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
            api_url=None,
            api_key=None,
            api_model=None,
            profile=None,
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
            raise AssertionError("voice prompt must pass STT note as ephemeral system prompt")

        async def ask_voice(self, prompt, *, ephemeral_system_prompt=""):
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


def test_hermes_conversation_agent_routes_delegate_intent_to_full_session(monkeypatch):
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
            api_url=None,
            api_key=None,
            api_model=None,
            profile=None,
            use_context_files=True,
            use_memory=True,
            enabled_toolsets=None,
            override_toolsets=True,
        ):
            self.system_prompt = system_prompt
            self.session_id = session_id
            self.api_model = api_model
            self.use_context_files = use_context_files
            self.use_memory = use_memory
            self.enabled_toolsets = enabled_toolsets
            self.override_toolsets = override_toolsets
            self.prompts = []
            self.main_session = system_prompt.startswith("Du bist Mara")
            instances.append(self)

        async def ask(self, prompt):
            raise AssertionError("voice path should use ask_voice")

        async def ask_voice(self, prompt, *, ephemeral_system_prompt=""):
            assert self.main_session is True
            self.prompts.append(prompt)
            if self.api_model == "full-mara-model":
                return "I found the thing."
            return "cheap voice should not answer delegate turns"

        async def ask_once(self, prompt):
            assert self.main_session is False
            return "OK"

        def replace_last_assistant_reply(self, text):
            pass

    monkeypatch.setattr(hermes_module, "_HermesAgentSession", FakeSession)
    monkeypatch.setattr(hermes_module, "_build_voice_context_blob", lambda text: "")
    monkeypatch.setattr(hermes_module, "_write_voice_digest", lambda payload: None)

    async def scenario():
        agent = hermes_module.HermesConversationAgent(
            project_root="/tmp/hermes-agent",
            session_id="same-session",
            api_model="cheap-voice-model",
            use_context_files=False,
            use_memory=False,
            enabled_toolsets=[],
            delegate_api_model="full-mara-model",
            delegate_use_context_files=True,
            delegate_use_memory=True,
            delegate_enabled_toolsets=["terminal", "file", "web"],
            reply_sanity_check=False,
        )
        abort_event = asyncio.Event()
        return [chunk async for chunk in agent.stream_reply("delegate such das bitte", abort_event)]

    chunks = asyncio.run(scenario())

    assert chunks == ["Wait a second… let me get that for you.", "I found the thing."]
    assert len(instances) == 2
    voice_session, delegate_session = instances
    assert voice_session.session_id == "same-session"
    assert delegate_session.session_id == "same-session"
    assert voice_session.api_model == "cheap-voice-model"
    assert voice_session.enabled_toolsets == []
    assert voice_session.use_memory is False
    assert delegate_session.api_model == "full-mara-model"
    assert delegate_session.enabled_toolsets == ["terminal", "file", "web"]
    assert delegate_session.use_memory is True
    assert delegate_session.prompts == ["delegate such das bitte"]
    assert voice_session.prompts == []


def test_voice_context_blob_includes_fresh_digest(tmp_path):
    digest_path = tmp_path / "digest.txt"
    digest_path.write_text(
        "stable preference\ncurrent thread\ncurrent thread\nimportant decision\n",
        encoding="utf-8",
    )

    blob = hermes_module._build_voice_context_blob("hello mara", digest_path=digest_path)

    assert "Voice context digest (last 24h):" in blob
    assert blob.count("current thread") == 1
    assert "stable preference" in blob
    assert "Current user message: hello mara" in blob


def test_write_voice_digest_deduplicates_and_persists(tmp_path):
    digest_path = tmp_path / "digest.txt"
    digest_path.write_text("alpha\n", encoding="utf-8")

    written = hermes_module._write_voice_digest(
        {
            "user": "alpha",
            "assistant": "beta",
            "thread": "alpha",
            "decision": "ASK",
            "note": "beta",
        },
        path=digest_path,
    )

    assert written == digest_path
    text = digest_path.read_text(encoding="utf-8")
    assert text.splitlines() == ["alpha", "beta", "ASK"]


def test_hermes_session_posts_to_api_and_reads_reply(monkeypatch, tmp_path):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "OK",
                        }
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(hermes_module.httpx, "AsyncClient", FakeAsyncClient)

    session = hermes_module._HermesAgentSession(
        system_prompt="System prompt.",
        session_id="test-session",
        empty_reply_error="nope",
        project_root=str(tmp_path),
        profile=str(tmp_path),
        api_url="http://127.0.0.1:8642/v1",
        api_key="unit-test-key",
        api_model="gpt-5.5",
    )

    reply = asyncio.run(session.ask("hello"))

    assert reply == "OK"
    assert captured["url"] == "http://127.0.0.1:8642/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer unit-test-key"
    assert captured["headers"]["X-Hermes-Session-Id"] == "test-session"
    assert captured["json"]["model"] == "gpt-5.5"
    assert captured["json"]["stream"] is False
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": "hello"},
    ]


def test_hermes_session_sends_per_request_agent_options(monkeypatch, tmp_path):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(hermes_module.httpx, "AsyncClient", FakeAsyncClient)

    session = hermes_module._HermesAgentSession(
        system_prompt="System prompt.",
        session_id="shared-mara-session",
        empty_reply_error="nope",
        project_root=str(tmp_path),
        profile=str(tmp_path),
        api_model="cheap-voice-model",
        use_context_files=False,
        use_memory=False,
        enabled_toolsets=[],
    )

    asyncio.run(session.ask_voice("raw stt", ephemeral_system_prompt="Voice note."))

    assert captured["headers"]["X-Hermes-Session-Id"] == "shared-mara-session"
    assert captured["json"]["x_hermes_agent_options"] == {
        "model": "cheap-voice-model",
        "enabled_toolsets": [],
        "skip_context_files": True,
        "skip_memory": True,
    }


def test_hermes_session_sends_ephemeral_system_prompt_without_polluting_user_history(monkeypatch, tmp_path):
    captured_payloads = []
    replies = iter(["first", "second"])

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": next(replies)}}]}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured_payloads.append(json)
            return FakeResponse()

    monkeypatch.setattr(hermes_module.httpx, "AsyncClient", FakeAsyncClient)

    session = hermes_module._HermesAgentSession(
        system_prompt="Base system.",
        session_id="voice-session",
        empty_reply_error="nope",
        project_root=str(tmp_path),
        profile=str(tmp_path),
    )

    asyncio.run(session.ask_voice("raw stt one", ephemeral_system_prompt="Voice/STT guardrail."))
    asyncio.run(session.ask_voice("raw stt two", ephemeral_system_prompt="Voice/STT guardrail."))

    assert captured_payloads[0]["messages"] == [
        {"role": "system", "content": "Base system."},
        {"role": "system", "content": "Voice/STT guardrail."},
        {"role": "user", "content": "raw stt one"},
    ]
    assert captured_payloads[1]["messages"] == [
        {"role": "system", "content": "Base system."},
        {"role": "system", "content": "Voice/STT guardrail."},
        {"role": "user", "content": "raw stt one"},
        {"role": "assistant", "content": "first"},
        {"role": "user", "content": "raw stt two"},
    ]


def test_hermes_session_sends_local_history_to_api(monkeypatch, tmp_path):
    captured_payloads = []
    replies = iter(["first", "second"])

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": next(replies)}}]}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured_payloads.append(json)
            return FakeResponse()

    monkeypatch.setattr(hermes_module.httpx, "AsyncClient", FakeAsyncClient)

    session = hermes_module._HermesAgentSession(
        system_prompt="System prompt.",
        session_id="test-session",
        empty_reply_error="nope",
        project_root=str(tmp_path),
        profile=str(tmp_path),
    )

    asyncio.run(session.ask("one"))
    asyncio.run(session.ask("two"))

    assert captured_payloads[1]["messages"] == [
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "first"},
        {"role": "user", "content": "two"},
    ]


def test_hermes_session_resolves_named_voice_profile_home(monkeypatch, tmp_path):
    hermes_root = tmp_path / "hermes-agent"
    voice_home = tmp_path / ".hermes" / "profiles" / "voice"
    hermes_root.mkdir()
    voice_home.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(tmp_path))

    session = hermes_module._HermesAgentSession(
        system_prompt="You are Mara.",
        session_id="test-session",
        empty_reply_error="nope",
        project_root=str(hermes_root),
        profile="voice",
    )

    assert session.profile == "voice"
    assert session.hermes_home == voice_home.resolve()
