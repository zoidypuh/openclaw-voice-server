from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .catalog import DEFAULT_LOCAL_GATEWAY_URL, DEFAULT_VOICE_SESSION_KEY
from .errors import ValidationError
from .text import pop_early_chunk, pop_sentence_chunk


def _collect_text_fragments(value: Any) -> list[str]:
    parts: list[str] = []
    if isinstance(value, str):
        if value:
            parts.append(value)
        return parts
    if isinstance(value, list):
        for item in value:
            parts.extend(_collect_text_fragments(item))
        return parts
    if isinstance(value, dict):
        for key in ("text", "value", "content"):
            if key in value:
                parts.extend(_collect_text_fragments(value.get(key)))
        return parts
    return parts


def _extract_stream_text(payload: dict[str, Any]) -> str:
    candidates = []
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        if isinstance(choice, dict):
            delta = choice.get("delta")
            if isinstance(delta, dict):
                candidates.append(delta.get("content"))
            message = choice.get("message")
            if isinstance(message, dict):
                candidates.append(message.get("content"))
            candidates.append(choice.get("text"))
    candidates.extend([payload.get("output_text"), payload.get("content"), payload.get("text")])
    parts: list[str] = []
    for candidate in candidates:
        parts.extend(_collect_text_fragments(candidate))
    return "".join(parts)


class DirectGatewayClient:
    def __init__(self, *, url: str, token: str, model: str, session_key: str = ""):
        self.url = normalize_gateway_url(url)
        self.token = token
        self.model = model
        self.session_key = session_key

    def _headers(self, *, include_session: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if include_session and self.session_key:
            headers["X-OpenClaw-Session-Key"] = self.session_key
        return headers

    def _payload(self, text: str, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": text}],
            "stream": stream,
        }
        if self.model:
            payload["model"] = self.model
        return payload

    async def stream_reply(self, text: str, abort_event: asyncio.Event):
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                self.url,
                headers=self._headers(include_session=True),
                json=self._payload(text, stream=True),
            ) as response:
                if response.status_code >= 400:
                    raise ValidationError(_read_error(response))
                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type:
                    raw_body = (await response.aread()).decode("utf-8", errors="replace").strip()
                    if not raw_body:
                        return
                    try:
                        payload = json.loads(raw_body)
                    except json.JSONDecodeError as exc:
                        raise ValidationError(str(exc)) from exc
                    text_body = _extract_stream_text(payload)
                    if text_body:
                        yield text_body
                    return

                buf = ""
                first_chunk_sent = False
                async for line in response.aiter_lines():
                    if abort_event.is_set():
                        return
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].lstrip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta = _extract_stream_text(chunk)
                    if not delta:
                        continue
                    buf += delta
                    while True:
                        sentence, buf = pop_sentence_chunk(buf)
                        if not sentence:
                            break
                        first_chunk_sent = True
                        yield sentence
                    if not first_chunk_sent:
                        early_chunk, buf = pop_early_chunk(buf)
                        if early_chunk:
                            first_chunk_sent = True
                            yield early_chunk
                if buf.strip():
                    yield buf.strip()


def resolve_voice_session_key(configured_session_key: str) -> str:
    configured = configured_session_key.strip()
    if configured:
        return configured
    return DEFAULT_VOICE_SESSION_KEY


def normalize_gateway_url(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlsplit(text)
    path = parsed.path.rstrip("/")
    if path in {"", "/", "/setup", "/voice", "/sessions"} or not path.endswith("/v1/chat/completions"):
        path = "/v1/chat/completions"
    normalized = parsed._replace(path=path)
    return urlunsplit(normalized)


def _read_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str):
        return error
    return payload.get("message") or f"HTTP {response.status_code}"


def _friendly_connection_error(normalized_url: str, exc: httpx.HTTPError) -> str:
    message = str(exc).strip()
    host = urlsplit(normalized_url).hostname or ""
    if host.endswith(".ts.net") and any(
        fragment in message.lower()
        for fragment in ("name or service not known", "nodename nor servname provided", "temporary failure in name resolution")
    ):
        return (
            f"Could not resolve {host} from the local voice server. "
            f"Use the local OpenClaw gateway URL {DEFAULT_LOCAL_GATEWAY_URL} instead of the public Tailscale hostname."
        )
    return f"Could not reach the gateway at {normalized_url}: {message}"


async def validate_gateway_connection(*, url: str, token: str, model: str, session_key: str = "") -> dict[str, Any]:
    if not token:
        raise ValidationError("Enter a gateway token.")
    normalized_url = normalize_gateway_url(url)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if session_key.strip():
        headers["X-OpenClaw-Session-Key"] = session_key.strip()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                normalized_url,
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                    "stream": False,
                },
            )
    except httpx.HTTPError as exc:
        raise ValidationError(_friendly_connection_error(normalized_url, exc)) from exc
    if response.status_code >= 400:
        raise ValidationError(_read_error(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValidationError("Gateway response was not valid JSON.") from exc
    text = _extract_stream_text(payload).strip()
    if not text:
        raise ValidationError("Gateway response did not contain reply text.")
    return {"ok": True, "reply_preview": text[:80]}
