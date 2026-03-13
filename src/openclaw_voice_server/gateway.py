from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx

from .config import VoiceServerConfig
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

    candidates.extend(
        [
            payload.get("output_text"),
            payload.get("content"),
            payload.get("text"),
        ]
    )

    parts: list[str] = []
    for candidate in candidates:
        parts.extend(_collect_text_fragments(candidate))
    return "".join(parts)


def _summarize_payload(payload: dict[str, Any]) -> str:
    keys = sorted(payload.keys())
    summary = f"keys={keys[:8]}"
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice_keys = sorted(choices[0].keys())
        summary += f" choice_keys={choice_keys[:8]}"
    return summary


class OpenClawGatewayClient:
    def __init__(self, config: VoiceServerConfig):
        self.config = config

    def build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.config.gateway_token}",
            "Content-Type": "application/json",
        }
        if self.config.gateway_session_key:
            headers["X-OpenClaw-Session-Key"] = self.config.gateway_session_key
        if self.config.gateway_message_channel:
            headers["X-OpenClaw-Message-Channel"] = self.config.gateway_message_channel
        return headers

    def build_payload(self, text: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": text}],
            "stream": True,
        }
        if self.config.gateway_model:
            payload["model"] = self.config.gateway_model
        return payload

    def stream_reply(
        self,
        text: str,
        event_queue,
        abort_event: threading.Event | None = None,
        stream_handle: dict[str, Any] | None = None,
    ) -> None:
        request_started = time.time()
        try:
            if abort_event and abort_event.is_set():
                return
            with httpx.Client(timeout=120) as client:
                with client.stream(
                    "POST",
                    self.config.gateway_url,
                    headers=self.build_headers(),
                    json=self.build_payload(text),
                ) as response:
                    if stream_handle is not None:
                        def _close() -> None:
                            try:
                                response.close()
                            except Exception:
                                pass
                            try:
                                client.close()
                            except Exception:
                                pass

                        with stream_handle["lock"]:
                            stream_handle["close"] = _close

                    if abort_event and abort_event.is_set():
                        return

                    response.raise_for_status()
                    event_queue.put(
                        {
                            "type": "phase",
                            "name": "gateway_headers",
                            "at": time.time(),
                            "elapsed": time.time() - request_started,
                            "status_code": response.status_code,
                            "content_type": response.headers.get("content-type", ""),
                        }
                    )

                    content_type = response.headers.get("content-type", "")
                    if "text/event-stream" not in content_type:
                        raw_body = response.read().decode("utf-8", errors="replace").strip()
                        if raw_body:
                            try:
                                payload = json.loads(raw_body)
                                text_body = _extract_stream_text(payload)
                                if text_body:
                                    now = time.time()
                                    event_queue.put(
                                        {
                                            "type": "phase",
                                            "name": "llm_first_token",
                                            "at": now,
                                            "elapsed": now - request_started,
                                        }
                                    )
                                    event_queue.put(
                                        {
                                            "type": "chunk",
                                            "kind": "body",
                                            "text": text_body,
                                            "at": now,
                                        }
                                    )
                                    event_queue.put({"type": "final_text", "text": text_body})
                                    return
                                event_queue.put(
                                    {
                                        "type": "diagnostic",
                                        "message": (
                                            "Gateway returned non-SSE JSON without text "
                                            f"({content_type or 'unknown content-type'}; "
                                            f"{_summarize_payload(payload)})"
                                        ),
                                    }
                                )
                            except json.JSONDecodeError:
                                event_queue.put(
                                    {
                                        "type": "diagnostic",
                                        "message": (
                                            "Gateway returned non-SSE body "
                                            f"({content_type or 'unknown content-type'}): "
                                            f"{raw_body[:220]}"
                                        ),
                                    }
                                )
                        return

                    buf = ""
                    full_response: list[str] = []
                    first_delta_seen = False
                    first_chunk_sent = False
                    seen_data_lines = 0
                    ignored_lines: list[str] = []
                    ignored_payloads: list[str] = []

                    for line in response.iter_lines():
                        if abort_event and abort_event.is_set():
                            break
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            if len(ignored_lines) < 3:
                                ignored_lines.append(line[:220])
                            continue

                        data_str = line[5:].lstrip()
                        if data_str == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            if len(ignored_lines) < 3:
                                ignored_lines.append(data_str[:220])
                            continue

                        seen_data_lines += 1
                        delta = _extract_stream_text(chunk)
                        if delta:
                            if not first_delta_seen:
                                first_delta_seen = True
                                event_queue.put(
                                    {
                                        "type": "phase",
                                        "name": "llm_first_token",
                                        "at": time.time(),
                                        "elapsed": time.time() - request_started,
                                    }
                                )
                            full_response.append(delta)
                            buf += delta
                            while True:
                                sentence, buf = pop_sentence_chunk(buf)
                                if not sentence:
                                    break
                                first_chunk_sent = True
                                event_queue.put(
                                    {
                                        "type": "chunk",
                                        "kind": "sentence",
                                        "text": sentence,
                                        "at": time.time(),
                                    }
                                )
                            if not first_chunk_sent:
                                early_chunk, buf = pop_early_chunk(buf)
                                if early_chunk:
                                    first_chunk_sent = True
                                    event_queue.put(
                                        {
                                            "type": "chunk",
                                            "kind": "early",
                                            "text": early_chunk,
                                            "at": time.time(),
                                        }
                                    )
                        elif len(ignored_payloads) < 3:
                            ignored_payloads.append(_summarize_payload(chunk))

                    if abort_event and abort_event.is_set():
                        return

                    if buf.strip():
                        event_queue.put(
                            {
                                "type": "chunk",
                                "kind": "tail",
                                "text": buf,
                                "at": time.time(),
                            }
                        )

                    final_text = "".join(full_response).strip()
                    if not final_text:
                        diagnostics = [
                            f"status={response.status_code}",
                            f"content-type={content_type or 'unknown'}",
                            f"data-lines={seen_data_lines}",
                        ]
                        if ignored_payloads:
                            diagnostics.append(f"payloads={'; '.join(ignored_payloads)}")
                        if ignored_lines:
                            diagnostics.append(f"lines={'; '.join(ignored_lines)}")
                        event_queue.put(
                            {
                                "type": "diagnostic",
                                "message": "Gateway stream ended without text: "
                                + " | ".join(diagnostics),
                            }
                        )

                    event_queue.put({"type": "final_text", "text": final_text})
        except Exception as exc:
            if not (abort_event and abort_event.is_set()):
                event_queue.put({"type": "error", "error": str(exc), "at": time.time()})
        finally:
            if stream_handle is not None:
                with stream_handle["lock"]:
                    stream_handle["close"] = None
            event_queue.put({"type": "done"})

