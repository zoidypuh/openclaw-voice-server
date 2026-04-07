from __future__ import annotations

import asyncio
import json
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
    ):
        self._history: list[dict] = []
        self._system_prompt = system_prompt
        self._session_id = session_id
        self._empty_reply_error = empty_reply_error
        self._gateway_url = str(gateway_url or "").strip()
        self._gateway_token = str(gateway_token or "").strip()
        self._gateway_model = str(gateway_model or "").strip()
        self.project_root = self._resolve_project_root(project_root)
        if not self.project_root.exists():
            raise ValidationError(
                f"Hermes Agent was not found at {self.project_root}. "
                "Set OPENCLAW_VOICE_HERMES_ROOT if it is installed elsewhere."
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
        configured = str(configured_root or os.environ.get("OPENCLAW_VOICE_HERMES_ROOT") or "").strip()
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
            enabled_toolsets=[],
            quiet_mode=True,
            verbose_logging=False,
            ephemeral_system_prompt=self._system_prompt,
            session_id=self._session_id,
            platform="cli",
            skip_context_files=True,
            skip_memory=True,
        )

    def _subprocess_payload(self, *, prompt: str) -> dict:
        return {
            "project_root": str(self.project_root),
            "system_prompt": self._system_prompt,
            "session_id": self._session_id,
            "prompt": prompt,
            "history": list(self._history),
            "gateway": {
                "url": self._gateway_url,
                "token": self._gateway_token,
                "model": self._gateway_model,
            },
        }

    def _reply_via_subprocess(self, *, prompt: str) -> str:
        payload = self._subprocess_payload(prompt=prompt)
        script = r"""
import json
import sys
from pathlib import Path

payload = json.loads(sys.stdin.read())
project_root = Path(payload["project_root"]).expanduser()
sys.path.insert(0, str(project_root))

from hermes_cli.config import load_config
from run_agent import AIAgent

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
    enabled_toolsets=[],
    quiet_mode=True,
    verbose_logging=False,
    ephemeral_system_prompt=payload["system_prompt"],
    session_id=payload["session_id"],
    platform="cli",
    skip_context_files=True,
    skip_memory=True,
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


class HermesConversationAgent(BaseConversationAgent):
    def __init__(
        self,
        *,
        project_root: str | None = None,
        gateway_url: str | None = None,
        gateway_token: str | None = None,
        gateway_model: str | None = None,
    ):
        self._session = _HermesAgentSession(
            system_prompt=(
                "You are a live voice chat assistant. Reply naturally and concisely. "
                "No markdown, no bullet points, and no stage directions."
            ),
            session_id=f"voice-chat-hermes-{uuid.uuid4().hex[:8]}",
            empty_reply_error="Hermes Agent returned an empty spoken reply.",
            project_root=project_root,
            gateway_url=gateway_url,
            gateway_token=gateway_token,
            gateway_model=gateway_model,
        )

    @property
    def project_root(self) -> Path:
        return self._session.project_root

    async def stream_reply(self, text: str, abort_event: asyncio.Event):
        if abort_event.is_set():
            return
        reply = await self._session.ask(text)
        if abort_event.is_set() or not reply:
            return
        yield reply


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
