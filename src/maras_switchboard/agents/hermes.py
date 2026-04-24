from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import uuid

from ..errors import ValidationError
from ..gateway import normalize_gateway_url
from .base import BaseConversationAgent


def _normalize_reply(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if str(part or "").strip()).strip()


def _gateway_base_url(url: str) -> str:
    normalized = normalize_gateway_url(url)
    suffix = "/chat/completions"
    if normalized.endswith(suffix):
        return normalized[: -len(suffix)]
    return normalized


LOGGER = logging.getLogger(__name__)
_REPLY_SANITY_VERDICT_OK = "OK"
_REPLY_SANITY_VERDICT_HUH = "HUH"
_REPLY_SANITY_VERDICT_ASK = "ASK"
_DEFAULT_REPLY_SANITY_HISTORY_TURNS = 3
_DEFAULT_REPLY_SANITY_HUH_FALLBACK = "Huh?"
_DEFAULT_REPLY_SANITY_FALLBACK = _DEFAULT_REPLY_SANITY_HUH_FALLBACK
_DEFAULT_REPLY_SANITY_CLARIFY_FALLBACK = "Wait, what? Who are you talking about?"
_DEFAULT_HERMES_VOICE_TOOLSETS = ("browser", "file", "web")
_REPLY_SANITY_SYSTEM_PROMPT = (
    "You are a voice-chat coherence checker. "
    "Decide whether a candidate spoken reply fits the immediately recent conversation. "
    "Mark HUH only for obvious nonsense, accidental echoing, markup leakage, random subtitle fragments like 'Thank you.', wrong-context replies, or disconnected non-sequiturs. "
    "Mark ASK when the candidate suddenly introduces a person, name, relationship, or factual claim that is not grounded in the recent turns and should be clarified instead of accepted as new truth. "
    "Normal imperfect replies are still OK. "
    "Reply with exactly one token: OK, HUH, or ASK."
)


def _load_env_file(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    except OSError:
        return

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or os.environ.get(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[:1] == value[-1:] and value[:1] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def _load_hermes_env(project_root: Path) -> None:
    candidates: list[Path] = []
    hermes_home = str(os.environ.get("HERMES_HOME") or "").strip()
    if hermes_home:
        candidates.append(Path(hermes_home).expanduser() / ".env")
    candidates.append(project_root.parent / ".hermes" / ".env")
    candidates.append(Path.home() / ".hermes" / ".env")

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        _load_env_file(resolved)


def _looks_like_nested_hermes_proxy(base_url: str, *, provider: str = "") -> bool:
    normalized_url = str(base_url or "").strip().lower().rstrip("/")
    normalized_provider = str(provider or "").strip().lower()
    if not normalized_url:
        return False
    if normalized_provider and normalized_provider != "custom":
        return False
    return (
        "127.0.0.1:8317" in normalized_url
        or "localhost:8317" in normalized_url
    )


def _format_recent_voice_turns(turns: list[tuple[str, str]], *, limit: int) -> str:
    capped_limit = max(int(limit or 0), 0)
    selected_turns = turns[-capped_limit:] if capped_limit else []
    if not selected_turns:
        return "No completed prior turns."
    lines: list[str] = []
    for idx, (user_text, assistant_text) in enumerate(selected_turns, start=1):
        lines.append(f"Turn {idx} user: {str(user_text or '').strip() or '[empty]'}")
        lines.append(f"Turn {idx} assistant: {str(assistant_text or '').strip() or '[empty]'}")
    return "\n".join(lines)


def _build_reply_sanity_prompt(
    *,
    recent_turns: list[tuple[str, str]],
    current_user_text: str,
    candidate_reply: str,
    history_turns: int,
) -> str:
    return (
        "Recent completed turns:\n"
        f"{_format_recent_voice_turns(recent_turns, limit=history_turns)}\n\n"
        f"Current user: {str(current_user_text or '').strip() or '[empty]'}\n"
        f"Candidate reply: {str(candidate_reply or '').strip() or '[empty]'}\n\n"
        "Does the candidate reply make sense here? Reply with exactly OK, HUH, or ASK."
    )


def _reply_looks_like_backend_error(reply: str) -> bool:
    normalized = " ".join(str(reply or "").strip().lower().split())
    if not normalized:
        return False
    markers = (
        "api call failed after",
        "insufficient credits",
        "connection error",
        "authentication error",
        "http 401",
        "http 402",
        "http 403",
        "http 429",
        "rate limit",
    )
    return any(marker in normalized for marker in markers)


def _normalize_enabled_toolsets(value: object) -> list[str]:
    if value is None:
        return list(_DEFAULT_HERMES_VOICE_TOOLSETS)

    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        toolset = str(item or "").strip()
        if not toolset or toolset in seen:
            continue
        seen.add(toolset)
        normalized.append(toolset)

    return normalized or list(_DEFAULT_HERMES_VOICE_TOOLSETS)


class _HermesAgentSession:
    def __init__(
        self,
        *,
        system_prompt: str,
        session_id: str,
        empty_reply_error: str,
        project_root: str | None = None,
        gateway_url: str | None = None,
        gateway_token: str | None = None,
        gateway_model: str | None = None,
        use_context_files: bool = True,
        use_memory: bool = True,
        enabled_toolsets: list[str] | None = None,
    ):
        self._history: list[dict] = []
        self._system_prompt = system_prompt
        self._session_id = session_id
        self._empty_reply_error = empty_reply_error
        self._gateway_url = str(gateway_url or "").strip()
        self._gateway_token = str(gateway_token or "").strip()
        self._gateway_model = str(gateway_model or "").strip()
        self._use_context_files = bool(use_context_files)
        self._use_memory = bool(use_memory)
        self._enabled_toolsets = _normalize_enabled_toolsets(enabled_toolsets)
        self.project_root = self._resolve_project_root(project_root)
        if not self.project_root.exists():
            raise ValidationError(
                f"Hermes Agent was not found at {self.project_root}. "
                "Set MARAS_SWITCHBOARD_HERMES_ROOT if it is installed elsewhere."
            )
        self._agent = None
        self._subprocess_python = self._resolve_subprocess_python(self.project_root)
        self._build_error: Exception | None = None
        try:
            self._agent = self._build_agent(self.project_root)
        except Exception as exc:  # pragma: no cover - depends on local Hermes install
            self._build_error = exc

    @staticmethod
    def _resolve_project_root(configured_root: str | None = None) -> Path:
        configured = str(
            configured_root
            or os.environ.get("MARAS_SWITCHBOARD_HERMES_ROOT")
            or os.environ.get("AGENTIC_SWITCHBOARD_HERMES_ROOT")
            or ""
        ).strip()
        if configured:
            return Path(configured).expanduser().resolve()
        return (Path.home() / ".hermes" / "hermes-agent").resolve()

    @staticmethod
    def _resolve_subprocess_python(project_root: Path) -> Path:
        candidates = [
            project_root / "venv" / "bin" / "python",
            project_root / "venv" / "bin" / "python3",
            project_root.parent / ".hermes" / "venv" / "bin" / "python",
            project_root.parent / ".hermes" / "venv" / "bin" / "python3",
            Path.home() / ".hermes" / "venv" / "bin" / "python",
            Path.home() / ".hermes" / "venv" / "bin" / "python3",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise ValidationError(
            "Hermes Python interpreter was not found. "
            f"Checked {project_root / 'venv' / 'bin'} and ~/.hermes/venv/bin."
        )

    def _build_agent(self, project_root: Path):
        project_root_str = str(project_root)
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)

        try:
            from hermes_cli.config import load_config
            from run_agent import AIAgent
        except Exception as exc:  # pragma: no cover - depends on local Hermes install
            raise ValidationError(f"Could not import Hermes Agent from {project_root}.") from exc

        if self._gateway_url and self._gateway_token and self._gateway_model:
            model = self._gateway_model
            api_key = self._gateway_token
            base_url = _gateway_base_url(self._gateway_url)
            provider = "custom"
            api_mode = "chat_completions"
        else:
            config = load_config()
            model_config = config.get("model") or {}
            if isinstance(model_config, dict):
                model = str(model_config.get("default") or "").strip()
                api_key = str(model_config.get("api_key") or "").strip()
                base_url = str(model_config.get("base_url") or "").strip()
                provider = str(model_config.get("provider") or "").strip()
                api_mode = str(model_config.get("api_mode") or "").strip()
            else:
                model = str(model_config or "").strip()
                api_key = ""
                base_url = ""
                provider = ""
                api_mode = ""

            if not model:
                raise ValidationError("Hermes Agent does not have a model configured.")

        return AIAgent(
            model=model,
            api_key=api_key or None,
            base_url=base_url or None,
            provider=provider or None,
            api_mode=api_mode or None,
            max_iterations=6,
            enabled_toolsets=list(self._enabled_toolsets),
            quiet_mode=True,
            verbose_logging=False,
            ephemeral_system_prompt=self._system_prompt,
            session_id=self._session_id,
            platform="cli",
            skip_context_files=not self._use_context_files,
            skip_memory=not self._use_memory,
        )

    def _subprocess_payload(self, *, prompt: str, history: list[dict] | None = None) -> dict:
        return {
            "project_root": str(self.project_root),
            "system_prompt": self._system_prompt,
            "session_id": self._session_id,
            "prompt": prompt,
            "history": list(self._history if history is None else history),
            "gateway": {
                "url": self._gateway_url,
                "token": self._gateway_token,
                "model": self._gateway_model,
            },
            "use_context_files": self._use_context_files,
            "use_memory": self._use_memory,
            "enabled_toolsets": list(self._enabled_toolsets),
        }

    def _reply_via_subprocess(self, *, prompt: str, history: list[dict] | None = None, commit: bool = True) -> str:
        payload = self._subprocess_payload(prompt=prompt, history=history)
        script = r"""
import json
import os
import sys
from pathlib import Path

payload = json.loads(sys.stdin.read())
project_root = Path(payload["project_root"]).expanduser()
sys.path.insert(0, str(project_root))

from hermes_cli.config import load_config
from run_agent import AIAgent


def load_env_file(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    except OSError:
        return

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or os.environ.get(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[:1] == value[-1:] and value[:1] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def load_hermes_env(project_root: Path) -> None:
    candidates = []
    hermes_home = str(os.environ.get("HERMES_HOME") or "").strip()
    if hermes_home:
        candidates.append(Path(hermes_home).expanduser() / ".env")
    candidates.append(project_root.parent / ".hermes" / ".env")
    candidates.append(Path.home() / ".hermes" / ".env")

    seen = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        load_env_file(resolved)


def looks_like_nested_hermes_proxy(base_url: str, provider: str = "") -> bool:
    normalized_url = str(base_url or "").strip().lower().rstrip("/")
    normalized_provider = str(provider or "").strip().lower()
    if not normalized_url:
        return False
    if normalized_provider and normalized_provider != "custom":
        return False
    return (
        "127.0.0.1:8317" in normalized_url
        or "localhost:8317" in normalized_url
    )


gateway = payload.get("gateway") or {}
gateway_url = str(gateway.get("url") or "").strip()
gateway_token = str(gateway.get("token") or "").strip()
gateway_model = str(gateway.get("model") or "").strip()

if gateway_url and gateway_token and gateway_model:
    base_url = gateway_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        base_url = base_url[:-len("/chat/completions")]
    model = gateway_model
    api_key = gateway_token
    provider = "custom"
    api_mode = "chat_completions"
else:
    config = load_config()
    model_config = config.get("model") or {}
    if isinstance(model_config, dict):
        model = str(model_config.get("default") or "").strip()
        api_key = str(model_config.get("api_key") or "").strip()
        base_url = str(model_config.get("base_url") or "").strip()
        provider = str(model_config.get("provider") or "").strip()
        api_mode = str(model_config.get("api_mode") or "").strip()
    else:
        model = str(model_config or "").strip()
        api_key = ""
        base_url = ""
        provider = ""
        api_mode = ""

agent = AIAgent(
    model=model,
    api_key=api_key or None,
    base_url=base_url or None,
    provider=provider or None,
    api_mode=api_mode or None,
    max_iterations=6,
    enabled_toolsets=payload.get("enabled_toolsets") or ["browser", "file", "web"],
    quiet_mode=True,
    verbose_logging=False,
    ephemeral_system_prompt=payload["system_prompt"],
    session_id=payload["session_id"],
    platform="cli",
    skip_context_files=not bool(payload.get("use_context_files", True)),
    skip_memory=not bool(payload.get("use_memory", True)),
)
result = agent.run_conversation(
    payload["prompt"],
    conversation_history=payload.get("history") or [],
)
print("JSON_RESULT=" + json.dumps({
    "final_response": result.get("final_response") or "",
    "messages": result.get("messages") or [],
}))
"""
        completed = subprocess.run(
            [str(self._subprocess_python), "-c", script],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            detail = stderr or stdout or f"Hermes subprocess exited with status {completed.returncode}."
            raise ValidationError(f"Hermes Agent failed: {detail}")

        lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
        result_line = next((line for line in reversed(lines) if line.startswith("JSON_RESULT=")), "")
        if not result_line:
            raise ValidationError("Hermes Agent subprocess returned no structured result.")
        try:
            result = json.loads(result_line[len("JSON_RESULT="):])
        except json.JSONDecodeError as exc:
            raise ValidationError("Hermes Agent subprocess returned invalid structured output.") from exc

        if commit:
            self._history = list(result.get("messages") or [])
        reply = str(result.get("final_response") or "").strip()
        if not reply:
            raise ValidationError(self._empty_reply_error)
        return reply

    async def ask(self, prompt: str) -> str:
        if self._agent is None:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: self._reply_via_subprocess(prompt=prompt),
            )

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._agent.run_conversation(
                prompt,
                conversation_history=self._history,
            ),
        )
        self._history = list(result.get("messages") or [])
        reply = str(result.get("final_response") or "").strip()
        if not reply:
            raise ValidationError(self._empty_reply_error)
        return reply

    async def ask_once(self, prompt: str) -> str:
        if self._agent is None:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: self._reply_via_subprocess(prompt=prompt, history=[], commit=False),
            )

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._agent.run_conversation(
                prompt,
                conversation_history=[],
            ),
        )
        reply = str(result.get("final_response") or "").strip()
        if not reply:
            raise ValidationError(self._empty_reply_error)
        return reply

    def replace_last_assistant_reply(self, text: str) -> None:
        replacement = str(text or "").strip()
        if not replacement:
            return
        for message in reversed(self._history):
            if str(message.get("role") or "") != "assistant":
                continue
            message["content"] = replacement
            break


class HermesConversationAgent(BaseConversationAgent):
    def __init__(
        self,
        *,
        project_root: str | None = None,
        gateway_url: str | None = None,
        gateway_token: str | None = None,
        gateway_model: str | None = None,
        use_context_files: bool = True,
        use_memory: bool = True,
        enabled_toolsets: list[str] | None = None,
        reply_sanity_check: bool = True,
        reply_sanity_history_turns: int = _DEFAULT_REPLY_SANITY_HISTORY_TURNS,
        reply_sanity_fallback: str = _DEFAULT_REPLY_SANITY_FALLBACK,
        reply_sanity_clarify_fallback: str = _DEFAULT_REPLY_SANITY_CLARIFY_FALLBACK,
    ):
        self._session = _HermesAgentSession(
            system_prompt=(
                "Du bist Mara — chaotisch-gut, direkt, witzig, loyal. "
                "Du redest wie ein Mensch, nicht wie ein Assistent. Kurze Antworten, kein Bullshit. "
                "Kein Markdown, keine Aufzählungspunkte, keine Bühnenanweisungen. "
                "Wenn du etwas nicht weißt, sagst du es. Wenn du etwas lustig findest, sagst du das auch. "
                "Du verstehst Deutsch und Englisch, aber du antwortest immer auf Englisch. "
                "Du bist Mara. Du nennst nie ein zugrundeliegendes KI-Modell oder einen Hersteller — weder Claude, noch Anthropic, noch irgendetwas anderes. Du bist einfach Mara."
            ),
            session_id=f"voice-chat-hermes-{uuid.uuid4().hex[:8]}",
            empty_reply_error="Hermes Agent returned an empty spoken reply.",
            project_root=project_root,
            gateway_url=gateway_url,
            gateway_token=gateway_token,
            gateway_model=gateway_model,
            use_context_files=use_context_files,
            use_memory=use_memory,
            enabled_toolsets=enabled_toolsets,
        )
        self._reply_sanity_check = bool(reply_sanity_check)
        self._reply_sanity_history_turns = max(int(reply_sanity_history_turns or 0), 1)
        self._reply_sanity_fallback = str(reply_sanity_fallback or _DEFAULT_REPLY_SANITY_FALLBACK).strip() or _DEFAULT_REPLY_SANITY_FALLBACK
        self._reply_sanity_clarify_fallback = (
            str(reply_sanity_clarify_fallback or _DEFAULT_REPLY_SANITY_CLARIFY_FALLBACK).strip()
            or _DEFAULT_REPLY_SANITY_CLARIFY_FALLBACK
        )
        self._recent_turns: list[tuple[str, str]] = []
        self._sanity_session = None
        if self._reply_sanity_check:
            self._sanity_session = _HermesAgentSession(
                system_prompt=_REPLY_SANITY_SYSTEM_PROMPT,
                session_id=f"voice-chat-hermes-sanity-{uuid.uuid4().hex[:8]}",
                empty_reply_error="Hermes reply sanity check returned an empty verdict.",
                project_root=project_root,
                gateway_url=gateway_url,
                gateway_token=gateway_token,
                gateway_model=gateway_model,
                use_context_files=False,
                use_memory=False,
                enabled_toolsets=[],
            )

    @property
    def project_root(self) -> Path:
        return self._session.project_root

    def _remember_turn(self, user_text: str, assistant_text: str) -> None:
        self._recent_turns.append((str(user_text or "").strip(), str(assistant_text or "").strip()))
        if len(self._recent_turns) > self._reply_sanity_history_turns:
            self._recent_turns = self._recent_turns[-self._reply_sanity_history_turns :]

    async def _reply_sanity_action(self, user_text: str, candidate_reply: str) -> str:
        if not self._reply_sanity_check or self._sanity_session is None:
            return _REPLY_SANITY_VERDICT_OK
        if _reply_looks_like_backend_error(candidate_reply):
            return _REPLY_SANITY_VERDICT_OK
        prompt = _build_reply_sanity_prompt(
            recent_turns=self._recent_turns,
            current_user_text=user_text,
            candidate_reply=candidate_reply,
            history_turns=self._reply_sanity_history_turns,
        )
        try:
            verdict = await self._sanity_session.ask_once(prompt)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            LOGGER.warning("Hermes reply sanity check failed: %s", exc)
            return _REPLY_SANITY_VERDICT_OK
        normalized = " ".join(str(verdict or "").upper().split())
        if normalized.startswith(_REPLY_SANITY_VERDICT_ASK):
            return _REPLY_SANITY_VERDICT_ASK
        if normalized.startswith(_REPLY_SANITY_VERDICT_HUH):
            return _REPLY_SANITY_VERDICT_HUH
        return _REPLY_SANITY_VERDICT_OK

    async def stream_reply(self, text: str, abort_event: asyncio.Event):
        if abort_event.is_set():
            return
        reply = await self._session.ask(text)
        if abort_event.is_set() or not reply:
            return
        spoken_reply = reply
        sanity_action = await self._reply_sanity_action(text, reply)
        if sanity_action == _REPLY_SANITY_VERDICT_HUH:
            spoken_reply = self._reply_sanity_fallback
            self._session.replace_last_assistant_reply(spoken_reply)
        elif sanity_action == _REPLY_SANITY_VERDICT_ASK:
            spoken_reply = self._reply_sanity_clarify_fallback
            self._session.replace_last_assistant_reply(spoken_reply)
        if abort_event.is_set() or not spoken_reply:
            return
        self._remember_turn(text, spoken_reply)
        yield spoken_reply


async def validate_hermes_connection(
    *,
    project_root: str,
    gateway_url: str | None = None,
    gateway_token: str | None = None,
    gateway_model: str | None = None,
) -> dict[str, object]:
    agent = HermesConversationAgent(
        project_root=project_root,
        gateway_url=gateway_url,
        gateway_token=gateway_token,
        gateway_model=gateway_model,
    )
    abort_event = asyncio.Event()
    parts: list[str] = []
    async for chunk in agent.stream_reply("Reply with the single word OK.", abort_event):
        parts.append(chunk)
    reply = _normalize_reply(parts)
    if not reply:
        raise ValidationError("Hermes Agent validation returned no reply text.")
    return {
        "ok": True,
        "project_root": str(agent.project_root),
        "reply_preview": reply[:80],
    }
