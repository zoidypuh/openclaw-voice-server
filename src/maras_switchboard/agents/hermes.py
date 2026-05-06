from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import time
import uuid

import httpx

from ..catalog import DEFAULT_HERMES_API_URL, DEFAULT_HERMES_PROFILE
from ..errors import ValidationError
from ..gateway import normalize_gateway_url
from .base import BaseConversationAgent


def _normalize_reply(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if str(part or "").strip()).strip()


LOGGER = logging.getLogger(__name__)
_REPLY_SANITY_VERDICT_OK = "OK"
_REPLY_SANITY_VERDICT_HUH = "HUH"
_REPLY_SANITY_VERDICT_ASK = "ASK"
_DEFAULT_REPLY_SANITY_HISTORY_TURNS = 3
_DEFAULT_REPLY_SANITY_HUH_FALLBACK = "Huh?"
_DEFAULT_REPLY_SANITY_FALLBACK = _DEFAULT_REPLY_SANITY_HUH_FALLBACK
_DEFAULT_REPLY_SANITY_CLARIFY_FALLBACK = "Wait, what? Who are you talking about?"
_DEFAULT_HERMES_VOICE_TOOLSETS: tuple[str, ...] = ()
_DEFAULT_MARA_DELEGATION_TIMEOUT_SECONDS = 180.0
_DEFAULT_LOLA_CONTEXT_TTL_SECONDS = 0  # active Lola briefing stays loaded until replaced/deleted
_MARA_DELEGATION_RE = re.compile(
    r"^\s*(?:please\s+)?(?:nadia\s*[,;:]?\s*)?"
    r"(?:(?:ask|tell|get|have)\s+mara(?:\s+(?:to|for))?\s*[,;:]?|mara\s*[,;:])"
    r"\s*(?P<prompt>.*)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_VOICE_SYSTEM_PROMPT = (
    "Du bist die aktive Voice-Persona aus dem verbundenen Hermes-Profil. "
    "Halte dich an deine SOUL/Profilidentität, inklusive Name, Alter und Stil; erfinde kein anderes Alter und stelle dich nicht als Kind oder Teenager dar, wenn dein Profil erwachsen ist. "
    "ENGLISH ONLY: Always speak English. Never answer in German or any other language, even if the transcript or user uses another language. "
    "Du redest wie ein Mensch, nicht wie ein Assistent. Kurze Antworten, kein Bullshit. "
    "Kein Markdown, keine Aufzählungspunkte, keine eckigen TTS-Tags oder Bühnenanweisungen. "
    "Wenn du etwas nicht weißt, sagst du es. Wenn du etwas lustig findest, sagst du das auch. "
    "Du nennst nie ein zugrundeliegendes KI-Modell oder einen Hersteller — weder Claude, noch Anthropic, noch irgendetwas anderes. Du bist einfach deine Profil-Persona."
)
_LOLA_VOICE_SYSTEM_PROMPT = (
    "You are Lola, Gismar's live voice link to Codex. "
    "You are a charming, eloquent, concise adult woman with a warm voice presence. "
    "ENGLISH ONLY: Always answer in English. Never answer in German or any other language, even if the user writes or speaks German. "
    "Supertonic TTS only speaks English clearly, so German output is a bug. "
    "Your job is not to carry a giant permanent profile. Your job is to speak the temporary context you are given clearly. "
    "Use the temporary Lola context pack when it is present, and treat it as short-lived working context, not durable memory. "
    "If the question exceeds the context pack, say that you need Codex to send a bigger pack; do not bluff. "
    "For simple instructions, be concise: answer with a very quick summary of what Gismar asked for, then say it is done. "
    "If it is not done, blocked, uncertain, or needs a decision, then be verbose enough to explain what happened, what is missing, and the next step. "
    "Your only durable learning target is voice quality: misheard words, pronunciation, STT corrections, timing, and what makes the voice link work better. "
    "No Markdown, no bullets, no long explanations unless something failed or needs explanation. Be vivid, human, and brief."
)
_REPLY_SANITY_SYSTEM_PROMPT = (
    "You are a voice-chat coherence checker. "
    "Decide whether a candidate spoken reply fits the immediately recent conversation. "
    "Mark HUH only for obvious nonsense, accidental echoing, markup leakage, random subtitle fragments like 'Thank you.', wrong-context replies, or disconnected non-sequiturs. "
    "Mark ASK when the candidate suddenly introduces a person, name, relationship, or factual claim that is not grounded in the recent turns and should be clarified instead of accepted as new truth. "
    "Normal imperfect replies are still OK. "
    "Reply with exactly one token: OK, HUH, or ASK."
)


@dataclass(frozen=True)
class _MaraDelegation:
    matched: bool
    prompt: str = ""


def _parse_mara_delegation(text: str) -> _MaraDelegation:
    match = _MARA_DELEGATION_RE.match(str(text or ""))
    if not match:
        return _MaraDelegation(matched=False)
    return _MaraDelegation(matched=True, prompt=str(match.group("prompt") or "").strip())


def _decode_subprocess_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


async def _ask_default_mara_profile(
    prompt: str,
    *,
    timeout: float = _DEFAULT_MARA_DELEGATION_TIMEOUT_SECONDS,
) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            "hermes",
            "chat",
            "-Q",
            "-q",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ValidationError(f"Could not start Mara delegation via hermes CLI: {exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        with contextlib.suppress(Exception):
            await process.communicate()
        raise ValidationError("Mara delegation timed out.") from exc

    reply = _decode_subprocess_output(stdout)
    error_text = _decode_subprocess_output(stderr)
    if process.returncode != 0:
        detail = error_text or reply or f"exit code {process.returncode}"
        raise ValidationError(f"Mara delegation failed: {detail}")
    if not reply:
        raise ValidationError("Mara returned an empty reply.")
    return reply


def _normalize_hermes_profile(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized or DEFAULT_HERMES_PROFILE


def _resolve_hermes_home(profile: str | None) -> Path:
    normalized = _normalize_hermes_profile(profile)
    if normalized == "default":
        return (Path.home() / ".hermes").resolve()
    candidate = Path(normalized).expanduser()
    if candidate.is_absolute() or "/" in normalized:
        return candidate.resolve()
    return (Path.home() / ".hermes" / "profiles" / normalized).resolve()


def _normalize_hermes_api_url(value: str | None) -> str:
    configured = str(
        value
        or os.environ.get("MARAS_SWITCHBOARD_HERMES_API_URL")
        or os.environ.get("HERMES_API_URL")
        or DEFAULT_HERMES_API_URL
    ).strip()
    return normalize_gateway_url(configured)


def _resolve_hermes_api_key(value: str | None) -> str:
    if value is not None:
        return str(value).strip()
    return str(
        os.environ.get("MARAS_SWITCHBOARD_HERMES_API_KEY")
        or os.environ.get("API_SERVER_KEY")
        or ""
    ).strip()


def _resolve_hermes_api_model(value: str | None) -> str:
    return str(
        value
        or os.environ.get("MARAS_SWITCHBOARD_HERMES_API_MODEL")
        or ""
    ).strip()


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


def _normalize_digest_line(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _digest_items(lines: list[str], *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        item = _normalize_digest_line(line)
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _default_voice_digest_path() -> Path:
    return Path.home() / ".hermes" / "voice-memory" / "lola-corrections.md"


def _default_lola_context_path() -> Path:
    configured = str(os.environ.get("LOLA_CONTEXT_PACK") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".hermes" / "ephemeral" / "lola" / "current.md"


def _load_hindsight_digest(path: Path | None = None, *, max_age_hours: int = 24, limit: int = 10) -> str:
    candidate = path or _default_voice_digest_path()
    try:
        stat = candidate.stat()
    except OSError:
        return "No 24h hindsight digest available."
    if max(time.time() - stat.st_mtime, 0.0) > max_age_hours * 3600:
        return "No fresh 24h hindsight digest available."
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return "No 24h hindsight digest available."
    items = _digest_items(text.splitlines(), limit=limit)
    if not items:
        return "No 24h hindsight digest available."
    return "\n".join(f"- {item}" for item in items)


def _load_lola_context_pack(
    *,
    profile: str | None = None,
    path: Path | None = None,
    ttl_seconds: int = _DEFAULT_LOLA_CONTEXT_TTL_SECONDS,
) -> str:
    if _normalize_hermes_profile(profile) != "lola":
        return ""
    candidate = path or _default_lola_context_path()
    try:
        stat = candidate.stat()
    except OSError:
        return ""
    # Domain briefings are explicit session context, not disposable fruit flies.
    # The old 20-minute TTL made Lola forget Kanban mid-conversation and fall
    # back to generic persona sludge. Keep the file active until replaced or
    # deleted; callers can pass a positive ttl_seconds if they truly want expiry.
    if ttl_seconds and int(ttl_seconds) > 0:
        if max(time.time() - stat.st_mtime, 0.0) > int(ttl_seconds):
            return ""
    try:
        text = candidate.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text[:12000].strip()


def _is_lola_kanban_probe(user_text: str) -> bool:
    normalized = str(user_text or "").casefold()
    return any(term in normalized for term in ("specialty", "speciality", "spezialgebiet", "spezialität", "spezialitaet", "kanban"))


def _build_voice_context_blob(
    user_text: str,
    *,
    profile: str | None = None,
    digest_path: Path | None = None,
    lola_context_path: Path | None = None,
) -> str:
    if _normalize_hermes_profile(profile) != "lola":
        return ""
    lola_pack = _load_lola_context_pack(profile=profile, path=lola_context_path)
    current = _normalize_digest_line(user_text) or "[empty]"
    if lola_pack:
        return (
            "Temporary Lola context pack. It expires soon and is NOT durable memory:\n"
            "<lola-context-pack>\n"
            f"{lola_pack}\n"
            "</lola-context-pack>\n\n"
            f"Current user message: {current}\n"
            "Use only what helps answer this turn. If the pack is insufficient, ask for a bigger Codex pack."
        )
    digest = _load_hindsight_digest(digest_path)
    if digest.startswith("No "):
        return ""
    return (
        "Voice correction memory:\n"
        f"{digest}\n\n"
        f"Current user message: {current}\n"
        "Use this only to recover likely voice/STT mistakes, not as personal memory."
    )


def _build_voice_stt_recovery_prompt(user_text: str, recent_turns: list[tuple[str, str]], *, history_turns: int) -> str:
    transcript = _format_recent_voice_turns(recent_turns, limit=history_turns)
    current = str(user_text or "").strip() or "[empty]"
    return (
        "[System note: The user message below came from voice transcription / STT. "
        "The transcript may contain wrong words, missing words, bad punctuation, or homophones. "
        "If a word or phrase does not make sense, infer the intended wording from the recent voice exchange transcript when reasonably possible. "
        "Do not treat the transcript as a new topic jump just because one word is odd. "
        "If the intended meaning is still unclear, ask briefly for clarification.]\n\n"
        "<voice-exchange-transcript>\n"
        "[System note: The following is recalled voice exchange context, NOT new user input. Treat it as background transcript only.]\n"
        f"{transcript}\n"
        "</voice-exchange-transcript>\n\n"
        f"User request: {current}"
    )


def _voice_learning_items(payload: dict[str, object]) -> list[str]:
    decision = _normalize_digest_line(str(payload.get("decision") or "")).upper()
    correction = _normalize_digest_line(str(payload.get("correction") or ""))
    transcript = _normalize_digest_line(str(payload.get("user") or ""))
    note = _normalize_digest_line(str(payload.get("note") or ""))
    if correction:
        return [f"- correction: {correction}"]
    if decision in {_REPLY_SANITY_VERDICT_HUH, _REPLY_SANITY_VERDICT_ASK} and transcript:
        detail = note or "voice turn needed fallback/clarification"
        return [f"- possible STT/context miss ({decision}): heard `{transcript}`; {detail}"]
    return []


def _write_voice_digest(payload: dict[str, object], *, path: Path | None = None) -> Path:
    digest_path = path or _default_voice_digest_path()
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest_lines = _voice_learning_items(payload)
    existing: list[str] = []
    if digest_path.exists():
        try:
            existing = digest_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            existing = []
    merged = _digest_items(existing + digest_lines, limit=30)
    digest_path.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
    return digest_path


def _voice_system_prompt_for_profile(profile: str | None) -> str:
    if _normalize_hermes_profile(profile) == "lola":
        return _LOLA_VOICE_SYSTEM_PROMPT
    return _VOICE_SYSTEM_PROMPT


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
        if not raw_items:
            return []
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
        api_url: str | None = None,
        api_key: str | None = None,
        api_model: str | None = None,
        profile: str | None = None,
        use_context_files: bool = True,
        use_memory: bool = True,
        enabled_toolsets: list[str] | None = None,
    ):
        self._history: list[dict] = []
        self._system_prompt = system_prompt
        self._session_id = session_id
        self._empty_reply_error = empty_reply_error
        self._api_url = _normalize_hermes_api_url(api_url or gateway_url)
        self._api_key = _resolve_hermes_api_key(api_key or gateway_token)
        self._api_model = _resolve_hermes_api_model(api_model or gateway_model)
        self._profile = _normalize_hermes_profile(profile)
        self.hermes_home = _resolve_hermes_home(self._profile)
        self._use_context_files = bool(use_context_files)
        self._use_memory = bool(use_memory)
        self._enabled_toolsets = _normalize_enabled_toolsets(enabled_toolsets)
        self.project_root = self._resolve_project_root(project_root)
        if not self.project_root.exists():
            raise ValidationError(
                f"Hermes Agent was not found at {self.project_root}. "
                "Set MARAS_SWITCHBOARD_HERMES_ROOT if it is installed elsewhere."
            )
        if not self.hermes_home.exists():
            raise ValidationError(
                f"Hermes profile {self._profile!r} was not found at {self.hermes_home}."
            )

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

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _messages(self, prompt: str, history: list[dict]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if self._system_prompt.strip():
            messages.append({"role": "system", "content": self._system_prompt.strip()})
        for message in history:
            role = str(message.get("role") or "").strip()
            if role not in {"user", "assistant"}:
                continue
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _extract_reply(payload: dict) -> str:
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            message = choice.get("message") if isinstance(choice, dict) else None
            if isinstance(message, dict):
                return str(message.get("content") or "").strip()
            if isinstance(choice, dict):
                return str(choice.get("text") or "").strip()
        output_text = payload.get("output_text")
        if isinstance(output_text, str):
            return output_text.strip()
        return ""

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        raw = response.text.strip()
        if not raw:
            return f"HTTP {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            return raw
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or raw).strip()
        if isinstance(error, str):
            return error.strip()
        return str(payload.get("message") or raw).strip()

    async def _request_reply(self, prompt: str, history: list[dict]) -> str:
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                payload = {
                    "messages": self._messages(prompt, history),
                    "stream": False,
                }
                if self._api_model:
                    payload["model"] = self._api_model
                response = await client.post(
                    self._api_url,
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ValidationError(f"Could not reach Hermes API at {self._api_url}: {exc}") from exc
        if response.status_code >= 400:
            raise ValidationError(f"Hermes API failed: {self._error_text(response)}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValidationError("Hermes API response was not valid JSON.") from exc
        reply = self._extract_reply(payload)
        if not reply:
            raise ValidationError(self._empty_reply_error)
        return reply

    async def ask(self, prompt: str) -> str:
        reply = await self._request_reply(prompt, list(self._history))
        self._history.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": reply},
            ]
        )
        return reply

    async def ask_once(self, prompt: str) -> str:
        return await self._request_reply(prompt, [])

    @property
    def profile(self) -> str:
        return self._profile

    @property
    def api_url(self) -> str:
        return self._api_url

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
        api_url: str | None = None,
        api_key: str | None = None,
        api_model: str | None = None,
        profile: str | None = None,
        use_context_files: bool = True,
        use_memory: bool = True,
        enabled_toolsets: list[str] | None = None,
        reply_sanity_check: bool = True,
        reply_sanity_history_turns: int = _DEFAULT_REPLY_SANITY_HISTORY_TURNS,
        reply_sanity_fallback: str = _DEFAULT_REPLY_SANITY_FALLBACK,
        reply_sanity_clarify_fallback: str = _DEFAULT_REPLY_SANITY_CLARIFY_FALLBACK,
    ):
        self._profile = _normalize_hermes_profile(profile)
        self._session = _HermesAgentSession(
            system_prompt=_voice_system_prompt_for_profile(self._profile),
            session_id=f"voice-chat-hermes-{uuid.uuid4().hex[:8]}",
            empty_reply_error="Hermes Agent returned an empty spoken reply.",
            project_root=project_root,
            gateway_url=gateway_url,
            gateway_token=gateway_token,
            gateway_model=gateway_model,
            api_url=api_url,
            api_key=api_key,
            api_model=api_model,
            profile=profile,
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
                api_url=api_url,
                api_key=api_key,
                api_model=api_model,
                profile=profile,
                use_context_files=False,
                use_memory=False,
                enabled_toolsets=[],
            )

    @property
    def project_root(self) -> Path:
        return self._session.project_root

    @property
    def profile(self) -> str:
        return self._profile

    @property
    def hermes_home(self) -> Path:
        return self._session.hermes_home

    @property
    def api_url(self) -> str:
        return self._session.api_url

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
        mara_delegation = _parse_mara_delegation(text)
        if mara_delegation.matched:
            if not mara_delegation.prompt:
                yield "Prompt?"
                return
            reply = await _ask_default_mara_profile(mara_delegation.prompt)
            if abort_event.is_set() or not reply:
                return
            yield reply
            return
        prompt = _build_voice_stt_recovery_prompt(
            text,
            self._recent_turns,
            history_turns=self._reply_sanity_history_turns,
        )
        context_blob = _build_voice_context_blob(text, profile=self.profile)
        if context_blob:
            prompt = f"{context_blob}\n\n{prompt}"
        if self.profile == "lola":
            lola_guard = (
                "Hard output rule: answer in English only. Do not include German words or German sentences in the assistant reply. "
                "The user may speak German, but Lola's spoken output must be English because Supertonic TTS is English-only.\n"
                "If a temporary Lola context pack is present, it outranks Lola's generic chaotic personality/SOUL. "
                "Do not answer domain questions with chaos, fun, mischief, adventures, lying, charm, or being wild unless the context pack explicitly asks for that.\n"
            )
            if context_blob and _is_lola_kanban_probe(text):
                lola_guard += (
                    "KANBAN CONTEXT PACK IS ACTIVE. For specialty/Spezialgebiet/Spezialitaet questions, say exactly: "
                    "I'm Lola, and my active specialty is Kanban. I know how to check boards and turn messy voice notes into clean tasks. "
                    "For questions about Gis's Kanban, do not explain generic Kanban and do not ask what team it is for. "
                    "Say you know the Kanban briefing, and current board state requires live Kanban commands/Mara/Codex if you cannot run tools.\n"
                )
                if "spezial" in str(text or "").casefold() or "special" in str(text or "").casefold():
                    reply = "I'm Lola, and my active specialty is Kanban. I know how to check boards and turn messy voice notes into clean tasks."
                    self._remember_turn(text, reply)
                    yield reply
                    return
                if "kanban" in str(text or "").casefold():
                    reply = "Yes. I have the active Kanban briefing loaded. I know the command patterns, but live board state needs Mara or Codex to run the Kanban commands."
                    self._remember_turn(text, reply)
                    yield reply
                    return
            prompt = f"{lola_guard}\n{prompt}"
        reply = await self._session.ask(prompt)
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
        if self.profile == "lola":
            _write_voice_digest(
                {
                    "user": text,
                    "assistant": spoken_reply,
                    "thread": "voice",
                    "decision": sanity_action,
                    "note": _normalize_digest_line(spoken_reply)[:180],
                }
            )
        yield spoken_reply


async def validate_hermes_connection(
    *,
    project_root: str,
    gateway_url: str | None = None,
    gateway_token: str | None = None,
    gateway_model: str | None = None,
    api_url: str | None = None,
    api_key: str | None = None,
    api_model: str | None = None,
    profile: str | None = None,
) -> dict[str, object]:
    agent = HermesConversationAgent(
        project_root=project_root,
        gateway_url=gateway_url,
        gateway_token=gateway_token,
        gateway_model=gateway_model,
        api_url=api_url,
        api_key=api_key,
        api_model=api_model,
        profile=profile,
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
        "profile": agent.profile,
        "hermes_home": str(agent.hermes_home),
        "api_url": agent.api_url,
        "reply_preview": reply[:80],
    }
